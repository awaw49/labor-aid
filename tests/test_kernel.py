"""纯单元测试：金额内核 / 闸门 / 规整函数 / 城市 / 会话。不依赖 LLM，秒级跑完。

运行: .venv/bin/python -m pytest tests/ -q
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.kernel.calc import calc_all, service_years, severance_base
from app.kernel.deadline import compute_deadline
from app.kernel.gates import run_gates
from app.extract import norm_date, norm_money
from app import city as city_store
from app import session as store

HZ = city_store._load("杭州市")
TODAY = date(2026, 11, 6)


def needs(legality="likely_illegal"):
    """calc_all 的 termination 参数要的是解除语义本身（内层字典）。"""
    return {"legality": legality, "resign_ground": "not_applicable",
            "legality_reason": "", "resign_ground_reason": ""}


# ---------- 工龄（劳动合同法 47 条：满 6 个月进 1 年，不满 6 个月按半月） ----------
def test_years_exact():
    assert service_years("2023-11-01", "2026-11-01").years == 3.0

def test_years_plus_19days():
    assert service_years("2023-10-01", "2026-10-20").years == 3.5   # 3 年 + 19 天 → 3.5

def test_years_6months_plus():
    assert service_years("2025-04-01", "2026-10-15").years == 2.0   # 1 年 6 个半月 → 2

def test_years_missing_start():
    assert service_years(None, "2026-10-01").years == 0.0

# ---------- 封顶（47 条 2 款：3 倍社平封顶 + 12 年上限） ----------
def test_severance_cap():
    base, capped = severance_base(40000, 12116)
    assert capped and base == pytest.approx(36348)

def test_severance_no_cap():
    base, capped = severance_base(8000, 12116)
    assert not capped and base == 8000

# ---------- 违法解除 2N ----------
def _slots(**over):
    s = {"dispute_types": ["termination"], "still_employed": "no",
         "start_date": "2023-10-01", "end_date": "2026-10-20",
         "avg_wage": 9200, "termination_by": "employer", "contract_state": "one",
         "prior_proceeding": "none"}
    s.update(over)
    return s

def test_2n_illegal():
    r = calc_all(_slots(), HZ, TODAY, termination=needs("likely_illegal"))
    item = next(i for i in r.items if i["key"] == "2n")
    assert item["amount"] == pytest.approx(9200 * 3.5 * 2)
    assert item["primary"]

def test_n_legal():
    r = calc_all(_slots(termination_reason="旷工三天，制度解除"), HZ, TODAY, termination=needs("likely_legal"))
    n = next(i for i in r.items if i["key"] == "n_or_2n")
    assert n["primary"] and n["amount"] == pytest.approx(9200 * 3.5)
    two = next(i for i in r.items if i["key"] == "2n")
    assert not two["primary"]

def test_no_zero_amount_line_for_resignation():
    r = calc_all(_slots(termination_by="employee"), HZ, TODAY, termination=needs())
    assert not any(i["amount"] == 0 for i in r.items)
    assert any("个人原因辞职" in n for n in r.notes)

def test_beijing_cap_full_chain():
    bj = city_store._load("北京市")
    r = calc_all(_slots(avg_wage=40000, start_date="2023-10-01", end_date="2026-10-20"),
                 bj, TODAY, termination=needs("likely_illegal"))
    two = next(i for i in r.items if i["key"] == "2n")
    assert two["amount"] == pytest.approx(36348 * 3.5 * 2)

# ---------- 未签合同二倍工资（最多 11 个月，近一年时效窗口） ----------
def test_double_wage_window_expired_by_monthly_limitation():
    # 2024 年的二倍工资月份，按月算时效到 2026-11 已全部过期 → 不计入，但要有说明
    s = _slots(dispute_types=["no_contract"], contract_state="none",
               start_date="2024-01-01", end_date="2026-11-05", avg_wage=9000)
    r = calc_all(s, HZ, TODAY, termination=needs("likely_legal"))
    assert not any(i["key"] == "double_wage" for i in r.items)
    assert any("时效" in n for n in r.notes)

def test_double_wage_recent_window():
    # 未签合同持续至今：近一年内的月份可主张
    s = _slots(dispute_types=["no_contract"], contract_state="none",
               start_date="2026-05-01", end_date="2026-11-05", avg_wage=9000)
    r = calc_all(s, HZ, TODAY, termination=needs("likely_legal"))
    dw = next(i for i in r.items if i["key"] == "double_wage")
    assert dw["amount"] > 0

def test_double_wage_needs_start():
    s = _slots(dispute_types=["no_contract"], contract_state="none")
    s.pop("start_date")
    r = calc_all(s, HZ, TODAY, termination=needs())
    assert not any(i["key"] == "double_wage" for i in r.items)
    assert any("入职日期" in n for n in r.notes)

# ---------- 加班 / 年假 / 欠薪 ----------
def test_overtime_formula():
    s = _slots(dispute_types=["termination", "overtime"], overtime_hours=40)
    r = calc_all(s, HZ, TODAY, termination=needs("likely_legal"))
    ot = next(i for i in r.items if i["key"] == "overtime")
    assert ot["amount"] == pytest.approx(9200 / 21.75 / 8 * 40 * 1.5, abs=0.01)   # 内核保留两位小数

def test_annual_leave_formula():
    s = _slots(dispute_types=["termination", "annual_leave"], unused_leave_days=5)
    r = calc_all(s, HZ, TODAY, termination=needs("likely_legal"))
    al = next(i for i in r.items if i["key"] == "annual_leave")
    assert al["amount"] == pytest.approx(9200 / 21.75 * 5 * 2, abs=0.01)

def test_unpaid_wage():
    s = _slots(dispute_types=["termination", "unpaid_wage"], unpaid_amount=6000)
    r = calc_all(s, HZ, TODAY, termination=needs("likely_legal"))
    up = next(i for i in r.items if i["key"] == "unpaid_wage")
    assert up["amount"] == 6000

# ---------- 闸门 ----------
def test_gate_scope_pass():
    g = run_gates(_slots(), HZ, needs(), TODAY)
    assert g.layers[0].status == "pass" and g.can_arbitrate

def test_gate_social_insurance_routed_out():
    outer = {"scope_issues": [{"key": "social_insurance_backpay"}], "subject_flags": {},
             "termination": needs()}
    g = run_gates(_slots(dispute_types=["social_insurance"]), HZ, outer, TODAY)
    assert g.layers[0].status == "out_of_scope"

def test_gate_uncity_out_of_scope():
    g = run_gates(_slots(employer_city="桂林市"), HZ, needs(), TODAY)
    assert g.layers[1].status == "out_of_scope" and not g.can_arbitrate

def test_gate_prior_arbitration_fail():
    g = run_gates(_slots(prior_proceeding="arbitration_done"), HZ, needs(), TODAY)
    assert g.layers[1].status == "fail"

def test_gate_expired_deadline_fail():
    g = run_gates(_slots(end_date="2024-01-01"), HZ, needs(), TODAY)
    assert g.layers[1].status == "fail"        # 一年时效已过

# ---------- 时效 ----------
def test_deadline_one_year():
    dl = compute_deadline(_slots(), TODAY)
    assert dl.start_date == date(2026, 10, 20)
    assert dl.deadline == date(2027, 10, 20)
    assert dl.days_left == (date(2027, 10, 20) - TODAY).days

def test_deadline_employed_not_running():
    dl = compute_deadline(_slots(still_employed="yes"), TODAY)
    assert dl.days_left is None

# ---------- 规整函数 ----------
def test_norm_money_units():
    assert norm_money("1.2万") == 12000
    assert norm_money("9千") == 9000
    assert norm_money("12k") == 12000
    assert norm_money("9,200元") == 9200
    assert norm_money("随便") is None

def test_norm_date_rejects_fake():
    assert norm_date("2026-2-30") is None
    assert norm_date("2026-13-45") is None
    assert norm_date("2024-2-29") == "2024-02-29"     # 闰年合法
    assert norm_date("10月5日") is None                # 缺年份不猜

# ---------- 城市归一 ----------
def test_city_district_prefix():
    assert city_store.normalize("杭州市西湖区") == "杭州市"
    assert city_store.covered({"employer_city": "杭州市西湖区"})
    assert city_store.normalize("北京朝阳区") == "北京市"

def test_city_uncovered():
    assert not city_store.covered({"employer_city": "桂林市"})

# ---------- 会话 ----------
def test_session_lru_cap():
    for _ in range(205):
        store.create()
    assert len(store.SESSIONS) == 200

def test_session_id_unpredictable():
    a, b = store.create(), store.create()
    assert a.id != b.id and len(a.id) == 12

# ---------- 批次 J：业务规则补充 ----------
def test_low_wage_compliance_note():
    r = calc_all(_slots(avg_wage=2000), HZ, TODAY, termination=needs("likely_legal"))
    assert any("最低工资" in n for n in r.notes)

def test_min_wage_ok_no_note():
    r = calc_all(_slots(avg_wage=9000), HZ, TODAY, termination=needs("likely_legal"))
    assert not any("低于" in n and "最低工资" in n for n in r.notes)

def test_followup_askable_respects_skip_and_cap():
    from app.followup import askable
    slots = {"dispute_types": None}                          # 缺失 → 可问
    assert "dispute_types" in askable(slots, set(), {})
    assert "dispute_types" not in askable(slots, {"dispute_types"}, {})   # 用户跳过 → 不再问
    assert "dispute_types" not in askable(slots, set(), {"dispute_types": 2})  # 问满 2 次 → 不再问
    assert "dispute_types" in askable(slots, set(), {"dispute_types": 1})      # 只问过 1 次 → 还会问

def test_followup_missing_skips_end_date_when_employed():
    from app.followup import missing_slots
    slots = {"still_employed": "yes"}
    assert "end_date" not in missing_slots(slots)
    slots2 = {"still_employed": "no"}
    assert "end_date" in missing_slots(slots2)

def test_followup_generate_template_fallback(monkeypatch):
    import app.followup as fu
    from app.llm import LLMError
    def boom(*a, **k):
        raise LLMError("LLM down")
    monkeypatch.setattr(fu, "chat_json", boom)
    out = fu.generate("我在杭州上班月薪九千", {}, {}, set(), {})
    assert out and out[0]["kind"] == "ask" and out[0].get("text")   # 模板问题兜底，不空转

def test_needs_fingerprint_changes_with_story():
    # 指纹只含语义相关槽位（城市不影响解除合法性，刻意不在指纹里）
    from app.needs import fingerprint
    f1 = fingerprint(["我上个月被辞退了"], {})
    f2 = fingerprint(["我上个月被辞退了，还欠薪"], {})
    f3 = fingerprint(["我上个月被辞退了"], {})
    assert f1 != f2 and f1 == f3

def test_deadline_exception_monthly_note():
    s = _slots()
    dl = compute_deadline(s, TODAY)
    assert any("按月" in e for e in dl.exceptions) or dl.exceptions == []

def test_session_ttl_eviction():
    import time as _t
    sid = store.create().id
    store.SESSIONS[sid].created -= 25 * 3600
    store._evict_expired(max_age_s=24 * 3600)
    assert sid not in store.SESSIONS

def test_bridge_backlog_guard(monkeypatch, tmp_path):
    import app.llm as llm
    (tmp_path / "data" / "manual_llm").mkdir(parents=True)
    for i in range(5):
        (tmp_path / "data" / "manual_llm" / f"req_x{i}.json").write_text("{}")
    monkeypatch.setattr(llm.settings_store, "ROOT", str(tmp_path))
    with pytest.raises(llm.LLMError, match="积压"):
        llm._manual_exchange([{"role": "user", "content": "x"}], model="m", max_tokens=8, json_mode=False)



def test_rmb_upper_cases():
    from app.report import rmb_upper
    assert rmb_upper(64400) == "陆万肆仟肆佰元整"
    assert rmb_upper(100200000) == "壹亿零贰拾万元整"
    assert rmb_upper(100000001) == "壹亿零壹元整"
    assert rmb_upper(305) == "叁佰零伍元整"
    assert rmb_upper(0) == "零元整"


# ---------- 批次 M：追问减法（计划轮 / 合并 / 推导） ----------
def test_plan_round_pairs():
    from app.followup import plan_round
    assert plan_round(["start_date", "end_date", "avg_wage"]) == ["start_date", "end_date"]
    assert plan_round(["contract_state", "prior_proceeding"]) == ["contract_state", "prior_proceeding"]
    assert plan_round(["avg_wage", "prior_proceeding"]) == ["avg_wage"]       # 焦点题不打包
    assert plan_round(["start_date", "avg_wage"]) == ["start_date"]           # 没有自然配对不硬凑
    assert plan_round(["start_date"]) == ["start_date"]
    assert plan_round([]) == []

def test_missing_slots_no_claims_and_merged_employment():
    from app.followup import missing_slots
    m = missing_slots({})
    assert "claims" not in m                       # 诉求由事实推导，不再问
    assert "employer_name" not in m                # 公司全称不追问：从话语/材料顺手收
    assert "still_employed" not in m and "end_date" in m   # 在职/离职合成一题
    m2 = missing_slots({"end_date": "2026-10-01"})
    assert "still_employed" in m2                  # 有离职日才单独问在职

def test_next_questions_first_focus_solo():
    from app.followup import next_questions
    qs = next_questions({}, {}, set(), {})
    assert len(qs) == 1 and qs[0]["slot"] == "dispute_types"

def test_pick_semantic_caps_and_discipline():
    from app.followup import _pick_semantic
    missing = ["start_date", "end_date", "avg_wage"]
    ok = _pick_semantic([{"slot": "start_date", "text": "哪天进的？"},
                         {"slot": "end_date", "text": "哪天走的？"}], missing)
    assert len(ok) == 2
    solo = _pick_semantic([{"slot": "avg_wage", "text": "月薪多少？"},
                           {"slot": "start_date", "text": "哪天进的？"}], missing)
    assert len(solo) == 1 and solo[0]["slot"] == "avg_wage"   # 焦点题被打包时只留第一条
    bad = _pick_semantic([{"slot": "avg_wage", "text": ""}], missing)   # 空文本不收
    assert bad == []

def test_derive_claims_from_types():
    from app.report import derive_claims
    d = derive_claims({"termination", "no_contract"})
    assert {"compensation_2n", "compensation_n", "double_wage"} <= set(d)
    assert derive_claims({"social_insurance"}) == []


def test_completeness_excludes_merged_employment_from_total():
    from app.followup import completeness
    c = completeness({}, {}, set(), {})            # 冷启动：在职项并入离职日期，不重复计数
    assert "still_employed" not in c["missing"]
    assert c["total"] == len(c["missing"]) + len(c["not_collectable"])
    c2 = completeness({"end_date": "2026-10-20", "still_employed": "no"}, {}, set(), {})
    assert c2["total"] >= c2["done"]               # 有值后计数自洽
