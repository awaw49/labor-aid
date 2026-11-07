from datetime import date

from app.kernel.calc import calc_all, service_years, severance_base

CITY = {"params": {"avg_wage_monthly": 8537, "min_wage_monthly": 2660,
                   "one_final_award_threshold": 31920}}
T = date(2026, 11, 4)
NEEDS_ILLEGAL = {"legality": "likely_illegal", "legality_reason": "理由不成立",
                 "resign_ground": "not_applicable"}


def test_service_years_full_year_counts_one_month():
    sy = service_years("2023-11-01", "2026-11-01")
    assert sy.years == 3.0


def test_service_years_six_months_rounds_up():
    sy = service_years("2026-01-01", "2026-07-05")
    assert sy.years == 1.0


def test_service_years_under_six_months_is_half():
    sy = service_years("2026-05-01", "2026-08-01")
    assert sy.years == 0.5


def test_severance_cap_at_three_times_average():
    base, capped = severance_base(30000, 8537)
    assert capped and base == 8537 * 3


def test_no_cap_below_threshold():
    base, capped = severance_base(20000, 8537)
    assert not capped and base == 20000


def test_illegal_termination_2n_is_primary():
    r = calc_all({"start_date": "2023-11-01", "end_date": "2026-09-15", "avg_wage": 8600,
                  "dispute_types": ["termination"], "termination_by": "employer"}, CITY, T,
                 termination=NEEDS_ILLEGAL)
    primary = [i for i in r.items if i["primary"]]
    assert len(primary) == 1 and primary[0]["key"] == "2n"
    assert primary[0]["amount"] == 8600 * 3 * 2


def test_legal_termination_n_is_primary():
    r = calc_all({"start_date": "2023-11-01", "end_date": "2026-09-15", "avg_wage": 8600,
                  "dispute_types": ["termination"], "termination_by": "employer"}, CITY, T,
                 termination={"legality": "likely_legal"})
    primary = [i for i in r.items if i["primary"]]
    assert primary[0]["key"] == "n_or_2n"


def test_personal_resignation_no_zero_line_with_guidance():
    r = calc_all({"start_date": "2024-01-01", "end_date": "2026-01-01", "avg_wage": 8000,
                  "dispute_types": ["termination"], "termination_by": "employee"}, CITY, T,
                 termination={"resign_ground": "personal"})
    assert r.total == 0
    assert not any(i["amount"] == 0 for i in r.items)          # 不出 0 元金额行
    assert any("个人原因辞职" in n for n in r.notes)            # 给引导话术


def test_article38_resignation_keeps_n():
    r = calc_all({"start_date": "2024-01-01", "end_date": "2026-01-01", "avg_wage": 8000,
                  "dispute_types": ["termination"], "termination_by": "employee"}, CITY, T,
                 termination={"resign_ground": "article38"})
    assert r.total == 8000 * 2


def test_double_wage_capped_at_11_months():
    r = calc_all({"start_date": "2026-01-01", "end_date": "2026-11-04", "avg_wage": 8000,
                  "dispute_types": ["no_contract"], "contract_state": "none"}, CITY, T)
    dw = [i for i in r.items if i["key"] == "double_wage"]
    assert dw and 9 <= dw[0]["amount"] / 8000 <= 11


def test_double_wage_time_barred_after_year():
    r = calc_all({"start_date": "2023-01-01", "end_date": "2024-06-01", "avg_wage": 8000,
                  "dispute_types": ["no_contract"], "contract_state": "none"}, CITY, T)
    assert not [i for i in r.items if i["key"] == "double_wage"]
    assert any("时效" in n for n in r.notes)


def test_double_wage_only_recent_months_count():
    r = calc_all({"start_date": "2025-06-01", "end_date": "2026-03-15", "avg_wage": 8000,
                  "dispute_types": ["no_contract"], "contract_state": "none"}, CITY, T)
    dw = [i for i in r.items if i["key"] == "double_wage"][0]
    assert 1 <= dw["amount"] / 8000 <= 6


def test_overtime_requires_confirmed_hours():
    r = calc_all({"avg_wage": 8000, "dispute_types": ["overtime"]}, CITY, T)
    assert not [i for i in r.items if i["key"] == "overtime"]
    assert any("加班时长" in n for n in r.notes)


def test_annual_leave_200_percent():
    r = calc_all({"avg_wage": 8700, "dispute_types": ["annual_leave"],
                  "unused_leave_days": 5}, CITY, T)
    item = [i for i in r.items if i["key"] == "annual_leave"][0]
    assert item["amount"] == round(8700 / 21.75 * 5 * 2, 2)


def test_missing_wage_leaves_note():
    r = calc_all({"start_date": "2024-01-01", "end_date": "2026-01-01",
                  "dispute_types": ["termination"], "termination_by": "employer"}, CITY, T)
    assert r.total == 0
    assert any("工资" in n for n in r.notes)


def test_still_employed_termination_not_counted():
    r = calc_all({"start_date": "2024-06-01", "avg_wage": 8600, "still_employed": "yes",
                  "dispute_types": ["termination"], "termination_by": "employer",
                  "claims": ["compensation_2n"]}, CITY, T, termination=NEEDS_ILLEGAL)
    assert r.total == 0
    assert any("还在职" in n for n in r.notes)
