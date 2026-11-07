"""报告组装：严格四块（结论卡 / 材料清单 / 立案路径 / 法条与类案）+ 免责声明。"""
from __future__ import annotations

import os
from datetime import date

from . import city as city_store
from . import needs as needs_engine
from .kernel.calc import calc_all
from .kernel.evidence import score_evidence
from .kernel.gates import run_gates
from .kernel.materials import build_materials
from .kernel.venue import build_venue
from .kernel.worth import compute_worth
from .rag.relevant import relevant_articles
from .rag.retriever import CaseCorpus, LawCorpus

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
LAWS = LawCorpus()
CASES = CaseCorpus()

DISCLAIMER = ("本意见依据你确认的事实与你上传的材料生成，供咨询参考，不构成律师意见，"
              "不代理案件，也不预测胜诉结果。事实或材料有变化时结论可能不同；"
              "需要人工帮助，可拨打 12348 法律援助热线。")


def rmb_upper(n: float) -> str:
    """人民币大写：报告正式场合用。"""
    digits = "零壹贰叁肆伍陆柒捌玖"
    units = ["", "拾", "佰", "仟"]
    bigs = ["", "万", "亿", "万亿"]
    n = int(round(n))
    if n == 0:
        return "零元整"
    segs = []
    while n > 0:
        segs.append(n % 10000)
        n //= 10000
    out, zero_pending = [], False
    for i in range(len(segs) - 1, -1, -1):
        seg = segs[i]
        if seg == 0:
            zero_pending = bool(out)
            continue
        s = ""
        zero = False
        for pos in range(3, -1, -1):
            d = (seg // 10 ** pos) % 10
            if d:
                if zero:
                    s += "零"
                s += digits[d] + units[pos]
                zero = False
            else:
                zero = bool(s)
        if out and (zero_pending or seg < 1000):
            s = "零" + s
        zero_pending = False
        out.append(s + bigs[i])
    return "".join(out) + "元整"


CLAIMS_BY_TYPE = {
    "termination": ("compensation_2n", "compensation_n"),
    "no_contract": ("double_wage",),
    "unpaid_wage": ("wage",),
    "overtime": ("wage",),
    "annual_leave": ("annual_leave_pay",),
}


def derive_claims(types: set[str]) -> list[str]:
    """诉求从争议类型直接推导，不再单独问用户一轮（最终请求仍由用户在报告里自己取舍）。"""
    out: list[str] = []
    for t, claims in CLAIMS_BY_TYPE.items():
        if t in types:
            out.extend(claims)
    return sorted(set(out))


def build_report(session, today: date | None = None, missing_facts: list[str] | None = None,
                 needs: dict | None = None, open_questions: list[dict] | None = None) -> dict:
    today = today or date.today()
    slots = dict(session.confirmed_slots())
    types = set(slots.get("dispute_types") or [])
    if not slots.get("claims"):
        derived = derive_claims(types)
        if derived:
            slots["claims"] = derived
    missing_facts = missing_facts or []
    open_questions = open_questions or []

    CITY = city_store.resolve(slots)
    needs = needs or needs_engine.needs_for(session, today.isoformat())
    gates = run_gates(slots, CITY, needs, today)
    evidence = score_evidence(session.materials, slots)
    calc = calc_all(slots, CITY, today, termination=needs["termination"])
    worth = compute_worth(slots, gates, evidence, calc, CITY, termination=needs["termination"],
                          materials_given=bool(getattr(session, "materials", [])))

    if not gates.can_arbitrate:
        decision = "cannot"
        failing = next((l for l in gates.layers if l.status in ("fail", "out_of_scope")), gates.layers[0])
        label = "❌ 不能走仲裁，先看下面的指路"
        one_liner = f"卡在「{failing.name}」：{failing.message}"
        decision = "cannot"
    else:
        decision = worth.decision
        label = {"recommend": "✅ ", "better_alternative": "⚠️ ", "not_recommended": "❌ "}[decision] + worth.decision_label
        if open_questions:
            label = {"recommend": "可以先准备起来，材料齐了就提交",
                     "better_alternative": "可以走，但先试更快的路",
                     "not_recommended": worth.decision_label}[decision]
        one_liner = _one_liner(worth, gates, calc, CITY, evidence,
                           still_employed=slots.get("still_employed"))

    reasons, invalid = _validate_citations(worth.reasons)
    degraded = any(r["citations"] == [] for r in reasons) or not reasons
    if degraded:
        for r in reasons:
            if not r["citations"]:
                r["text"] += "（该条依据未能回溯到法条库，需人工咨询）"
        label = label + " · 部分结论需人工咨询"

    articles, invalid_articles = _collect_articles(reasons, calc, gates)
    articles = _merge_relevant(articles, relevant_articles(slots, needs))
    matched_cases = _cases_for(types)

    confidence = _confidence(session)


    rmb = rmb_upper(calc.total) if calc.total else ""

    return {
        "generated_at": today.isoformat(),
        "claim_amount_rmb": rmb,
        "city": CITY["city"], "caliber": CITY["caliber"], "verified_at": CITY["verified_at"],
        "conclusion": {
            "decision": decision,
            "label": label,
            "one_liner": one_liner,
            "score": worth.score,
            "gates": [l.__dict__ for l in gates.layers],
            "reasons": reasons,
            "deadline": gates.deadline,
            "dimensions": [d.__dict__ for d in worth.dimensions],
            "alternative": worth.alternative,
            "claim_amount": calc.total,
            "calc_items": calc.items,
            "calc_notes": calc.notes,
            "confidence": confidence,
            "citation_check": {"invalid": invalid + invalid_articles, "degraded": degraded},
        },
        "evidence": {
            "score": evidence.score, "level": evidence.level,
            "dimensions": evidence.dimensions, "gaps": evidence.gaps,
            "strong": evidence.strong, "employer_burden": evidence.employer_burden,
        },
        "understanding": {**needs},
        "materials": build_materials(types, {m["type"] for m in session.materials}),
        "venue": build_venue(CITY, slots, gates.deadline),
        "citations": {"articles": articles, "cases": matched_cases},
        "disclaimer": DISCLAIMER,
        "hotlines": CITY["hotlines"],
        "missing_facts": missing_facts,
        "open_questions": open_questions,
        "preliminary": bool(open_questions),
    }


def _one_liner(worth, gates, calc, city, evidence=None, still_employed=None) -> str:
    days = gates.deadline.get("days_left")
    if days is not None:
        tail = f"时效还剩 {days} 天。"
    elif still_employed == "no":
        tail = "最后工作日还没确认，时效先按没起算处理——确认日期后我给你精确到天的数。"
    else:
        tail = "如果还在职，时效还没开始跑。"
    if worth.decision == "recommend":
        return (f"按你确认的这些事实，建议去{city['city']}申请劳动仲裁："
                f"能主张的金额大约 {calc.total:,.0f} 元，" + tail)
    if worth.decision == "better_alternative" and worth.alternative:
        return f"可以仲裁，但先走「{worth.alternative['title']}」更快。" + tail
    return "按现在这些事实，仲裁不太划算，先补证据或者走别的路。" + tail


def _validate_citations(reasons: list[dict]) -> tuple[list[dict], list[str]]:
    out, invalid = [], []
    for r in reasons:
        good, bad = LAWS.by_ids([c for c in r.get("citations", [])])
        invalid += bad
        out.append({**r, "citations": [g["id"] for g in good],
                    "citation_titles": [f"{g['law']}{g['no_cn']}" for g in good]})
    return out, invalid


def _collect_articles(reasons, calc, gates) -> tuple[list[dict], list[str]]:
    ids = set()
    for r in reasons:
        ids.update(r["citations"])
    for it in calc.items:
        ids.update([x for x in it.get("basis", "").split(";") if x])
    for l in gates.layers:
        ids.update(l.citations or [])
    good, bad = LAWS.by_ids(sorted(ids))
    arts = [{"id": a["id"], "law": a["law"], "no_cn": a["no_cn"], "text": a["text"],
             "chapter": a["chapter"], "effective": a["effective"], "source": a["source"]}
            for a in good]
    arts.sort(key=lambda x: (x["law"], int(x["id"].split(":")[1])))
    return arts, bad


def _merge_relevant(articles: list[dict], extra: list[dict]) -> list[dict]:
    """把"应当一并告知"的法条并入依据清单（去重，保持条号顺序）。"""
    have = {a["id"] for a in articles}
    out = list(articles)
    for e in extra:
        cid = e["id"]
        if cid in have:
            continue
        a = LAWS.get(cid)
        if not a:
            continue
        out.append({"id": a["id"], "law": a["law"], "no_cn": a["no_cn"], "text": a["text"],
                    "chapter": a["chapter"], "effective": a["effective"], "source": a["source"],
                    "why": e["why"], "role": "supporting"})
        have.add(cid)
    out.sort(key=lambda x: (x["law"], int(x["id"].split(":")[1])))
    return out


def _cases_for(types: set[str]) -> list[dict]:
    out = []
    for c in CASES.match(types):
        out.append({
            "id": c["id"], "title": c["title"], "source": c["source"],
            "source_url": c["source_url"], "year": c["year"],
            "focus": c["focus"], "holding": c["holding"], "result": c["result"],
            "comparable": c["comparable"], "limit": c["limit"],
        })
    return out


def _confidence(session) -> dict:
    image_based, oral, pending = [], [], []
    for k, v in session.slots.items():
        if not v.get("confirmed"):
            continue
        label = k
        if v.get("source") == "image_confirmed":
            image_based.append(label)
        else:
            oral.append(label)
    pending = list(session.suspect.keys())
    level = "中"
    if image_based and len(oral) <= 3:
        level = "较高"
    if not image_based:
        level = "较低（全部依赖口述）"
    return {"level": level, "from_image": image_based, "from_oral": oral,
            "unconfirmed": pending}
