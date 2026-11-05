"""报告可靠性断言器（目标 3：真实有效可靠）。

对每单测试会话：金额按《劳动合同法》47/82/85、劳动法 44/50、年休假 5 条的法条公式独立复算，
不照抄 calc.py 实现；引用逐条回溯到法条库；时效/窗口/热线/一裁终局线逐项断言。

用法: .venv/bin/python tools/verify_report.py
依赖: 服务在 http://127.0.0.1:8787 运行（manual 模式需 LLM 应答方在线）。
"""
from __future__ import annotations
import json
import re
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
BASE = "http://127.0.0.1:8787"
CITY_DIR = ROOT / "data" / "city"


def call(path, body=None):
    req = urllib.request.Request(BASE + path, method="POST",
                                 data=json.dumps(body or {}).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=300))


def get(path):
    return json.load(urllib.request.urlopen(BASE + path, timeout=60))


def load_city(name):
    files = {"北京市": "beijing.json", "上海市": "shanghai.json", "广州市": "guangzhou.json",
             "深圳市": "shenzhen.json", "杭州市": "hangzhou.json"}
    return json.load(open(CITY_DIR / files[name], encoding="utf-8"))


# ---------- 独立复算（法条口径） ----------
def statute_years(start: date, end: date) -> float:
    """《劳动合同法》47 条：每满一年 1 个月；6 个月以上不满 1 年按 1 年；不满 6 个月按 0.5。"""
    full = end.year - start.year - ((end.month, end.day) < (start.month, start.day))
    anniv = date(start.year + full, start.month, start.day)
    rem = (end - anniv).days
    if rem == 0:
        return float(full)
    months = (end.year - anniv.year) * 12 + end.month - anniv.month
    if end.day < anniv.day:
        months -= 1
    return float(full + 1) if months >= 6 else float(full + 0.5)


def recompute(case, rep, today: date, sid: str):
    """返回 {断言名: (期望值, 实际值)}；准绳=会话里已确认的槽位，公式=法条。"""
    city = load_city(rep["city"])
    p = city["params"]
    sess = get(f"/api/session/{sid}")
    conf = {k: v.get("value") for k, v in (sess.get("slots") or {}).items() if v.get("confirmed")}
    d = lambda s: date.fromisoformat(s) if s else None
    start, end = d(conf.get("start_date")), d(conf.get("end_date")) or today
    avg = float(conf.get("avg_wage") or 0)
    types = set(conf.get("dispute_types") or [])
    items = {it["key"]: it for it in rep["conclusion"]["calc_items"]}
    checks = {}

    legality = rep["understanding"]["termination"]["legality"]
    if "termination" in types and avg:
        years = statute_years(start, end) if start else 0.0
        cap = 3 * p["avg_wage_monthly"]
        capped = avg > cap
        base = min(avg, cap)
        years_n = min(years, 12.0) if capped else years
        n_amount = round(base * years_n, 2)
        illegal = legality == "likely_illegal"
        primary_key = "2n" if illegal else "n_or_2n"
        if legality == "uncertain" and not case["answers"].get("termination_evidence"):
            illegal = True
            primary_key = "2n"
        if conf.get("termination_by") == "mutual":
            primary_key = "n_amount_mutual"
        if conf.get("still_employed") != "yes" and start:
            if primary_key in items:
                checks[f"N/{primary_key}"] = (n_amount if primary_key != "2n" else round(n_amount * 2, 2),
                                              items[primary_key]["amount"])
            else:
                checks[f"N/{primary_key}"] = ("应有项", f"缺失:{list(items)}")
        elif "termination" in types and avg and not start:
            # 入职日期缺失：不允许出现 0 元金额行，必须有口径注记
            checks["入职缺失不出0元行"] = (True, not any(it["amount"] == 0 for it in items.values()))
            checks["入职缺失有注记"] = (True, any("入职日期" in n for n in rep["conclusion"]["calc_notes"]))

    if "no_contract" in types and conf.get("contract_state") == "none" and start and avg:
        begin = start + timedelta(days=30)
        stop = min(end, start + timedelta(days=365))
        window_start = max(begin, today - timedelta(days=365))
        claimable = max(0, int(round((stop - window_start).days / 30.44))) if stop > window_start else 0
        months = min(claimable, 11)
        if months and "double_wage" in items:
            checks["二倍工资"] = (round(avg * months, 2), items["double_wage"]["amount"])

    if "unpaid_wage" in types and conf.get("unpaid_amount"):
        if "unpaid_wage" in items:
            checks["欠薪"] = (float(conf["unpaid_amount"]), items["unpaid_wage"]["amount"])

    if "overtime" in types and conf.get("overtime_hours") and avg and "overtime" in items:
        hourly = avg / 21.75 / 8
        checks["加班费"] = (round(hourly * float(conf["overtime_hours"]) * 1.5, 2),
                           items["overtime"]["amount"])

    if "annual_leave" in types and conf.get("unused_leave_days") and avg and "annual_leave" in items:
        checks["年假"] = (round(avg / 21.75 * float(conf["unused_leave_days"]) * 2, 2),
                         items["annual_leave"]["amount"])

    total = round(sum(it["amount"] for it in rep["conclusion"]["calc_items"] if it.get("primary")), 2)
    checks["总额=Σprimary"] = (round(rep["conclusion"]["claim_amount"], 2), total)
    return checks


def check_citations(rep):
    bad = []
    con = rep["conclusion"]
    ids = set()
    for r in con["reasons"]:
        ids |= set(r.get("citations", []))
    for it in con["calc_items"]:
        ids |= {x for x in it.get("basis", "").split(";") if x}
    for l in con["gates"]:
        ids |= set(l.get("citations", []))
    for cid in ids:
        try:
            art = get(f"/api/law/{cid}")
            txt = art.get("text", "") if isinstance(art, dict) else ""
            if not txt or len(txt) < 10:
                bad.append((cid, "文本为空"))
        except Exception as e:
            bad.append((cid, str(e)[:40]))
    listed = {a["id"] for a in rep["citations"]["articles"]}
    for cid in ids:
        if cid not in listed:
            bad.append((cid, "未并入依据清单"))
    return bad


def check_structure(rep, city_name):
    con = rep["conclusion"]
    errs = []
    if rep["city"] != city_name:
        errs.append(f"城市口径错误: {rep['city']} ≠ {city_name}")
    p = load_city(city_name)["params"]
    expect_threshold = p["min_wage_monthly"] * 12
    if con["gates"] and any(l["status"] in ("pass", "warn") for l in con["gates"]):
        # 一裁终局线校验只在口径生效时才有意义
        for l in con["gates"]:
            if l["status"] == "out_of_scope":
                errs.append("覆盖城市不应 out_of_scope")
    if len(rep["hotlines"]) < 4:
        errs.append("热线缺失")
    if "12348" not in rep["disclaimer"]:
        errs.append("免责声明缺 12348")
    if not rep["venue"]:
        errs.append("venue 为空")
    if con["deadline"].get("days_left") is not None:
        dl = date.fromisoformat(con["deadline"]["deadline"])
        expect_days = (dl - date.today()).days
        if abs(expect_days - con["deadline"]["days_left"]) > 1:
            errs.append(f"时效天数: 报 {con['deadline']['days_left']} 应 {expect_days}")
    if not con["reasons"]:
        errs.append("结论理由为空")
    if not con["calc_items"] and con["decision"] != "cannot" and not rep.get("open_questions"):
        errs.append("无金额项但结论非 cannot 且无待确认项")
    return errs


CASES = [
    dict(tag="杭州·全类型", city="杭州市",
         story="我在杭州一家软件公司上班，2024年初入职，公司一直没跟我签书面合同，现在还欠我6000块工资，"
               "上个月老板直接让我走人，什么理由都不给，我还有5天年假没休，经常周末加班大概40个小时，月薪九千",
         story_types=["termination", "no_contract", "unpaid_wage", "overtime", "annual_leave"],
         answers={"employer_name": "杭州星澜软件有限公司", "employer_city": "杭州市", "still_employed": "no",
                  "start_date": "2024-01-01", "end_date": "2026-11-30", "avg_wage": "9000",
                  "contract_state": "none", "unpaid_amount": "6000", "overtime_hours": "40",
                  "unused_leave_days": "5", "termination_by": "employer", "prior_proceeding": "none",
                  "termination_reason": "老板让我走人，什么理由都不给",
                  "claims": ["compensation_2n", "double_wage", "wage"]}),
    dict(tag="深圳·合法解除走N", city="深圳市",
         story="我在深圳一家物流公司干了两年半，因为连续旷工三天被公司开除了，员工手册我签过字，制度里写旷工三天解除，"
               "月薪八千，去年入职的",
         story_types=["termination"],
         answers={"employer_name": "深圳顺捷物流有限公司", "employer_city": "深圳市", "still_employed": "no",
                  "start_date": "2024-05-06", "end_date": "2026-11-10", "avg_wage": "8000",
                  "contract_state": "one", "termination_by": "employer", "prior_proceeding": "none",
                  "termination_reason": "连续旷工三天，按员工手册解除，手册我签过字"}),
    dict(tag="北京·协商一致", city="北京市",
         story="我在北京一家广告公司干了三年，上个月公司跟我协商解除，签了协商解除协议但补偿一直拖着没给全，月薪两万五",
         story_types=["termination"],
         answers={"employer_name": "北京光影广告有限公司", "employer_city": "北京市", "still_employed": "no",
                  "start_date": "2023-11-01", "end_date": "2026-10-31", "avg_wage": "25000",
                  "contract_state": "one", "termination_by": "mutual", "prior_proceeding": "none",
                  "termination_reason": "协商解除签了协议，补偿拖着没给全"}),
]


def run_case(case):
    print(f"\n===== {case['tag']} =====")
    errs = []
    sid = call("/api/session")["session_id"]
    r = call(f"/api/session/{sid}/text", {"text": case["story"]})
    for _ in range(20):
        qs = []
        for m in r.get("messages", []):
            if m.get("kind") == "questions":
                qs = m.get("questions", [])
        if not qs:
            break
        slot = qs[0]["slot"]
        if slot not in case["answers"]:
            break
        r = call(f"/api/session/{sid}/answer", {"slot": slot, "value": case["answers"][slot]})
    try:
        rep = call(f"/api/session/{sid}/report", {})
    except Exception as e:
        print("  ✗ 报告生成失败:", str(e)[:120])
        return False

    today = date.today()
    # 1) 结构断言
    errs += check_structure(rep, case["city"])
    # 2) 引用回溯
    bad_cites = check_citations(rep)
    errs += [f"引用 {c}: {w}" for c, w in bad_cites]
    # 3) 金额复算（准绳=会话已确认槽位）
    for name, (want, got) in recompute(case, rep, today, sid).items():
        if isinstance(want, (int, float)) and isinstance(got, (int, float)):
            if abs(want - got) > 1:
                errs.append(f"{name}: 报告 {got} ≠ 法条复算 {want}")
        elif want != got:
            errs.append(f"{name}: {got} (期望 {want})")
    # 4) 一裁终局线
    p = load_city(case["city"])["params"]
    if rep["conclusion"]["claim_amount"] and p["one_final_award_threshold"] != p["min_wage_monthly"] * 12:
        errs.append("一裁终局线 ≠ 最低工资×12")

    if errs:
        for e in errs:
            print("  ✗", e)
        return False
    print(f"  ✓ 全部断言通过 | 金额 {rep['conclusion']['claim_amount']:,.0f} | "
          f"legality={rep['understanding']['termination']['legality']} | "
          f"时效 {rep['conclusion']['deadline']['days_left']} 天")
    return True


if __name__ == "__main__":
    ok = all(run_case(c) for c in CASES)
    print("\n结果:", "全部通过 ✓" if ok else "存在失败 ✗")
    sys.exit(0 if ok else 1)
