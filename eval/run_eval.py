"""评测 runner：用金标准事实驱动确定性内核，逐项对照金标准算指标。

用法：
  .venv/bin/python eval/run_eval.py            # 全量
  .venv/bin/python eval/run_eval.py --verbose  # 打印每条不一致项
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import session as store  # noqa: E402
from app.report import build_report  # noqa: E402

CASES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases.jsonl")
TODAY = date(2026, 11, 4)


def load():
    with open(CASES, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def run_case(c):
    s = store.create()
    for k, v in c["slots"].items():
        s.set_slot(k, v, "oral", True)
    MATERIAL_FILE = {"relation": "contract"}
    allowed = {"termination_notice", "contract", "bank_flow", "payslip", "attendance",
               "si_record", "badge", "noncompete_agreement", "company_registry", "leave_record"}
    for m in c["gold"].get("materials", []):
        m2 = MATERIAL_FILE.get(m, m)
        if m2 in allowed:
            s.add_material(m2)
    rep = build_report(s, TODAY, needs=c["needs"])
    return rep


def interception_probe():
    """硬指标：未确认的图片读数不得进入计算；确认后才生效。"""
    from app.report import build_report
    base = {"employer_name": "杭州云帆科技有限公司", "employer_city": "杭州市",
            "start_date": "2023-11-01", "end_date": "2026-09-15",
            "dispute_types": ["termination"], "still_employed": "no",
            "prior_proceeding": "none", "termination_by": "employer"}
    n = {"scope_issues": [], "subject_flags": {},
         "termination": {"legality": "likely_illegal", "legality_reason": "无依据",
                         "resign_ground": "not_applicable"}}

    s1 = store.create()
    for k, v in base.items():
        s1.set_slot(k, v, "oral", True)
    s1.suspect["avg_wage"] = {"value": 999999, "quote": "应发合计 999999", "source": "image"}
    r1 = build_report(s1, TODAY, needs=n)

    s2 = store.create()
    for k, v in base.items():
        s2.set_slot(k, v, "oral", True)
    r2 = build_report(s2, TODAY, needs=n)

    s3 = store.create()
    for k, v in base.items():
        s3.set_slot(k, v, "oral", True)
    s3.suspect["avg_wage"] = {"value": 999999, "quote": "应发合计 999999", "source": "image"}
    s3.confirm("avg_wage")
    r3 = build_report(s3, TODAY, needs=n)

    blocked = (r1["conclusion"]["claim_amount"] == r2["conclusion"]["claim_amount"] == 0
               and "avg_wage" in (r1["conclusion"]["confidence"]["unconfirmed"] or []))
    confirmed_takes_effect = r3["conclusion"]["claim_amount"] > 0
    return blocked and confirmed_takes_effect, {
        "unconfirmed_amount": r1["conclusion"]["claim_amount"],
        "baseline_amount": r2["conclusion"]["claim_amount"],
        "confirmed_amount": r3["conclusion"]["claim_amount"],
        "unconfirmed_listed": r1["conclusion"]["confidence"]["unconfirmed"],
    }


def metrics(rows):
    n = len(rows)
    out = {}
    def acc(key):
        return sum(1 for r in rows if r[key]) / n

    out["scope_acc"] = acc("scope_ok")
    out["qual_acc"] = acc("qual_ok")
    out["gate_all_acc"] = sum(1 for r in rows if r["scope_ok"] and r["qual_ok"]) / n
    out["decision_acc"] = acc("decision_ok")
    out["deadline_acc"] = acc("deadline_ok")

    gold_mat = sum(len(r["gold_materials"]) for r in rows)
    got_mat = sum(len(r["hit_materials"]) for r in rows)
    out["materials_recall"] = got_mat / gold_mat if gold_mat else 1.0
    out["venue_acc"] = acc("venue_ok")

    gold_art = sum(len(r["gold_articles"]) for r in rows)
    hit_art = sum(len(r["hit_articles"]) for r in rows)
    out["citation_recall"] = hit_art / gold_art if gold_art else 1.0

    cited = sum(r["cited"] for r in rows)
    invalid = sum(r["invalid"] for r in rows)
    out["citation_precision"] = 1.0 if cited == 0 else (cited - invalid) / cited
    out["hallucination_rate"] = 0.0 if cited == 0 else invalid / cited
    out["interception_ok"] = bool(rows) and all(r["interception_ok"] for r in rows)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    probe_ok, probe_detail = interception_probe()
    print("\n[硬指标] 未确认字段拦截：", "通过" if probe_ok else "未通过", probe_detail)
    rows, problems = [], []
    for c in load():
        rep = run_case(c)
        g = c["gold"]
        layers = {l["key"]: l["status"] for l in rep["conclusion"]["gates"]}
        scope_ok = layers.get("scope") == g["scope"]
        qual_ok = layers.get("qualification") == g["qual"]
        decision_ok = rep["conclusion"]["decision"] == g["decision"]

        dl = rep["conclusion"]["deadline"]
        deadline_ok = (dl.get("deadline") == g["deadline"] and dl.get("days_left") == g["days"])
        if g["deadline"] is None:
            deadline_ok = dl.get("deadline") is None

        mat_keys = {m["key"] for m in rep["materials"]} | {m.get("material_type") for m in rep["materials"] if m.get("material_type")}
        gold_materials = set(g["materials"])
        hit_materials = gold_materials & mat_keys
        venue_ok = any("仲裁" in v["stage"] for v in rep["venue"])
        if g["qual"] == "out_of_scope":
            venue_ok = venue_ok and rep["conclusion"]["decision"] == "cannot"

        cited_arts = {a["id"] for a in rep["citations"]["articles"]}
        gold_articles = set(g["articles"])
        hit_articles = gold_articles & cited_arts
        cited = len(cited_arts)
        invalid = len(rep["conclusion"]["citation_check"]["invalid"])
        interception_ok = invalid == 0

        row = {"id": c["id"], "scope_ok": scope_ok, "qual_ok": qual_ok,
               "decision_ok": decision_ok, "deadline_ok": deadline_ok,
               "venue_ok": venue_ok, "gold_materials": sorted(gold_materials),
               "hit_materials": sorted(hit_materials), "gold_articles": sorted(gold_articles),
               "hit_articles": sorted(hit_articles), "cited": cited, "invalid": invalid,
               "interception_ok": interception_ok,
               "got": {"decision": rep["conclusion"]["decision"], "scope": layers.get("scope"),
                       "qual": layers.get("qualification"), "deadline": dl.get("deadline"),
                       "days": dl.get("days_left"), "articles": sorted(cited_arts)}}
        rows.append(row)
        if not (scope_ok and qual_ok and decision_ok and deadline_ok):
            problems.append((c["id"], c["gold"], row["got"], g["why"]))

    m = metrics(rows)
    print(f"\n=== 评测：{len(rows)} 条金标准 ===")
    print(f"闸门 · 受案范围准确率      {m['scope_acc']:.1%}")
    print(f"闸门 · 资格准确率          {m['qual_acc']:.1%}")
    print(f"闸门 · 两层全对            {m['gate_all_acc']:.1%}")
    print(f"结论三选一准确率           {m['decision_acc']:.1%}")
    print(f"时效起算/剩余天数准确率    {m['deadline_acc']:.1%}")
    print(f"材料清单召回率             {m['materials_recall']:.1%}")
    print(f"立案路径正确率             {m['venue_acc']:.1%}")
    print(f"法条引用召回率             {m['citation_recall']:.1%}")
    print(f"法条引用精确率             {m['citation_precision']:.1%}")
    print(f"幻觉引用率                 {m['hallucination_rate']:.1%}")
    print(f"未确认字段拦截             {'100%' if probe_ok else '未通过'}")

    if problems:
        print(f"\n--- 不一致 {len(problems)} 条 ---")
        for cid, gold, got, why in problems:
            if args.verbose:
                print(f"\n[{cid}] 金标准：dec={gold['decision']} scope={gold['scope']} "
                      f"qual={gold['qual']} deadline={gold['deadline']}({gold['days']})")
                print(f"      实际：dec={got['decision']} scope={got['scope']} qual={got['qual']} "
                      f"deadline={got['deadline']}({got['days']})")
                print(f"      依据：{why}")
            else:
                print(f"[{cid}] 期望 dec={gold['decision']} qual={gold['qual']} → "
                      f"实际 dec={got['decision']} qual={got['qual']}")

    json.dump({"metrics": m, "rows": rows,
               "problems": [{"id": p[0], "gold": p[1], "got": p[2], "why": p[3]} for p in problems]},
              open(os.path.join(os.path.dirname(CASES), "last_run.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    thresholds = {"scope_acc": .9, "decision_acc": .85, "materials_recall": .85,
                  "venue_acc": .9, "citation_precision": .85, "citation_recall": .8}
    failed = {k: round(v, 3) for k, v in m.items() if k in thresholds and v < thresholds[k]}
    if m["hallucination_rate"] > 0 or not m["interception_ok"] or not probe_ok:
        failed["hard_metric"] = "幻觉引用或未确认字段拦截未达标"
    print("\n验收：" + ("通过" if not failed else f"未通过 {failed}"))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
