from datetime import date

from app.kernel.gates import map_categories, run_gates, scope_issues_from_needs
from tests.conftest import needs

CITY = None
T = date(2026, 11, 4)


def city():
    import json
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return json.load(open(os.path.join(root, "data", "city", "hangzhou.json"), encoding="utf-8"))


BASE = {"employer_name": "杭州云帆科技有限公司", "employer_city": "杭州市",
        "start_date": "2023-11-01", "end_date": "2026-09-15", "avg_wage": 8600,
        "dispute_types": ["termination"], "still_employed": "no",
        "prior_proceeding": "none", "termination_by": "employer"}


def gate(slots=None, n=None):
    return run_gates({**BASE, **(slots or {})}, city(), n or needs(), T)


def test_scope_pass_for_termination():
    g = gate()
    assert g.layers[0].status == "pass"
    assert g.can_arbitrate


def test_scope_backpay_routes_to_administration():
    g = gate({"dispute_types": ["social_insurance"]}, needs(scope=["social_insurance_backpay"]))
    assert g.layers[0].status == "out_of_scope"
    assert not g.can_arbitrate
    assert "社保" in g.layers[0].route["to"]


def test_scope_housing_fund_route():
    g = gate({}, needs(scope=["housing_fund"]))
    assert g.layers[0].route["actions"][0]["value"] == "12329"


def test_scope_work_injury_route():
    g = gate({}, needs(scope=["work_injury_recognization"]))
    assert "工伤" in g.layers[0].route["title"] or "工伤" in g.layers[0].message


def test_scope_criminal_never_concludes():
    g = gate({}, needs(scope=["criminal"]))
    assert g.layers[0].status == "out_of_scope"
    assert "定性" in g.layers[0].message


def test_multiple_scope_issues_listed_in_detail():
    g = gate({}, needs(scope=["housing_fund", "criminal"]))
    assert "住房公积金" in g.layers[0].message
    assert any("刑事" in d for d in g.layers[0].detail)


def test_subject_retired_warns():
    g = gate({}, needs(retired="yes"))
    assert g.layers[1].status == "warn"
    assert any("退休" in d for d in g.layers[1].detail)


def test_subject_intern_warns():
    g = gate({}, needs(intern="yes"))
    assert any("实习" in d for d in g.layers[1].detail)


def test_time_bar_fails_qualification():
    g = gate({"end_date": "2024-01-01"})
    assert g.layers[1].status == "fail"
    assert not g.can_arbitrate


def test_covered_city_uses_own_caliber():
    g = gate({"employer_city": "上海市"})
    assert g.layers[1].status == "pass"
    assert g.can_arbitrate


def test_city_alias_resolves():
    g = gate({"employer_city": "上海"})
    assert g.layers[1].status == "pass"


def test_uncovered_city_is_out_of_scope():
    g = gate({"employer_city": "南京市"})
    assert g.layers[1].status == "out_of_scope"
    assert not g.can_arbitrate


def test_prior_award_blocks():
    g = gate({"prior_proceeding": "arbitration_done"})
    assert g.layers[1].status == "fail"


def test_settlement_only_warns():
    g = gate({"prior_proceeding": "settled"})
    assert g.layers[1].status == "warn"
    assert g.can_arbitrate


def test_missing_employer_name_warns():
    g = gate({"employer_name": None})
    assert g.layers[1].status == "warn"


def test_deadline_present_in_gate_output():
    g = gate()
    assert g.deadline["deadline"] == "2027-09-15"
    assert g.deadline["days_left"] > 0


def test_categories_map_to_article_two():
    cats = map_categories({"termination", "unpaid_wage"})
    nos = {c["no"] for c in cats}
    assert 2 in nos and 5 in nos


def test_scope_issues_filter_unknown_keys():
    assert scope_issues_from_needs({"scope_issues": [{"key": "nonsense"}]}) == []


def test_scope_issues_dedupe():
    got = scope_issues_from_needs({"scope_issues": [{"key": "housing_fund"},
                                                    {"key": "housing_fund"}]})
    assert got == ["housing_fund"]
