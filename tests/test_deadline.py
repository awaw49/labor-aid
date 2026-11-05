from datetime import date, timedelta

from app.kernel.deadline import compute_deadline

T = date(2026, 11, 4)


def test_termination_one_year_from_end():
    r = compute_deadline({"end_date": "2026-03-15", "still_employed": "no",
                          "dispute_types": ["termination"]}, T)
    assert r.deadline == date(2027, 3, 15)
    assert r.days_left == (date(2027, 3, 15) - T).days
    assert r.urgency == "normal"


def test_wage_claim_in_service_has_no_limit():
    r = compute_deadline({"still_employed": "yes", "dispute_types": ["unpaid_wage"]}, T)
    assert r.deadline is None and r.days_left is None
    assert "不受一年" in r.start_rule


def test_wage_claim_after_leaving_runs_from_end():
    r = compute_deadline({"end_date": "2026-01-10", "still_employed": "no",
                          "dispute_types": ["unpaid_wage"]}, T)
    assert r.deadline == date(2027, 1, 10)
    assert "终止" in r.start_rule


def test_interruption_restarts_clock():
    r = compute_deadline({"end_date": "2025-01-10", "still_employed": "no",
                          "dispute_types": ["termination"], "last_claim_date": "2026-06-01"}, T)
    assert r.start_date == date(2026, 6, 1)
    assert r.deadline == date(2027, 6, 1)
    assert "中断" in r.start_rule


def test_expired_deadline_is_negative_and_urgent():
    r = compute_deadline({"end_date": "2024-01-01", "still_employed": "no",
                          "dispute_types": ["termination"]}, T)
    assert r.days_left < 0
    assert r.urgency == "high"
    assert any("超过一年" in e for e in r.exceptions)


def test_missing_end_date_does_not_guess():
    r = compute_deadline({"still_employed": "no", "dispute_types": ["termination"]}, T)
    assert r.deadline is None and r.days_left is None
    assert "缺少离职日期" in r.start_rule


def test_no_contract_mentions_monthly_time_bar():
    r = compute_deadline({"end_date": "2026-05-01", "still_employed": "no",
                          "dispute_types": ["no_contract"]}, T)
    assert "按月" in r.start_rule
    assert any("二倍工资" in e for e in r.exceptions)


def test_annual_leave_flags_uncertainty():
    r = compute_deadline({"end_date": "2026-05-01", "still_employed": "no",
                          "dispute_types": ["annual_leave"]}, T)
    assert any("年休假" in e for e in r.exceptions)


def test_urgency_threshold_60_days():
    end = (T - timedelta(days=320)).isoformat()
    r = compute_deadline({"end_date": end, "still_employed": "no",
                          "dispute_types": ["termination"]}, T)
    assert 0 <= r.days_left <= 60
    assert r.urgency == "high"


def test_still_employed_non_wage_has_no_deadline():
    r = compute_deadline({"still_employed": "yes", "dispute_types": ["termination"]}, T)
    assert r.deadline is None
    assert "仍在职" in r.start_rule
