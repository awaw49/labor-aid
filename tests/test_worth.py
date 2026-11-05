from datetime import date

from app.kernel.calc import calc_all
from app.kernel.evidence import score_evidence
from app.kernel.gates import run_gates
from app.kernel.worth import WEIGHTS, compute_worth

T = date(2026, 11, 4)
CITY = {"params": {"avg_wage_monthly": 8537, "min_wage_monthly": 2660,
                   "one_final_award_threshold": 31920},
        "city": "杭州市", "caliber": "", "verified_at": ""}
NEEDS = {"legality": "likely_illegal", "legality_reason": "理由不成立",
         "resign_ground": "not_applicable"}


def build(slots, materials, needs=None):
    n = {"scope_issues": [], "subject_flags": {},
         "termination": needs or NEEDS}
    g = run_gates(slots, {**CITY, "arbitration": [], "online": [], "court": {}, "supervision": {},
                          "legal_aid": {}, "hotlines": []}, n, T) if False else run_gates(slots, CITY_FULL(), n, T)
    e = score_evidence(materials, slots)
    c = calc_all(slots, CITY, T, termination=n["termination"])
    w = compute_worth(slots, g, e, c, CITY, termination=n["termination"])
    return w, g, e, c


def CITY_FULL():
    import json
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return json.load(open(os.path.join(root, "data", "city", "hangzhou.json"), encoding="utf-8"))


STRONG = [{"type": "contract"}, {"type": "bank_flow"}, {"type": "termination_notice"}]
SLOTS = {"employer_name": "杭州云帆科技有限公司", "employer_city": "杭州市",
         "start_date": "2023-11-01", "end_date": "2026-09-15", "avg_wage": 8600,
         "dispute_types": ["termination"], "still_employed": "no",
         "prior_proceeding": "none", "termination_by": "employer", "company_status": "normal"}


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_strong_evidence_recommends():
    w, *_ = build(SLOTS, STRONG)
    assert w.decision == "recommend"
    assert w.score >= 62


def test_thin_evidence_does_not_recommend():
    w, *_ = build(SLOTS, [])
    assert w.decision in ("not_recommended", "better_alternative")
    assert w.score < 62


def test_small_wage_claim_prefers_supervision():
    slots = {**SLOTS, "avg_wage": 2000, "dispute_types": ["unpaid_wage"],
             "start_date": "2026-06-01", "end_date": "2026-10-01", "unpaid_amount": 4000}
    w, *_ = build(slots, [{"type": "bank_flow"}])
    assert w.alternative and w.alternative["key"] == "supervision"
    assert w.decision == "better_alternative"


def test_abnormal_company_lowers_enforcement():
    slots = {**SLOTS, "company_status": "abnormal"}
    w, *_ = build(slots, STRONG)
    dims = {d.key: d for d in w.dimensions}
    assert dims["enforcement"].score <= 20


def test_one_final_threshold_applies():
    slots = {**SLOTS, "avg_wage": 3000}
    w, *_ = build(slots, STRONG)
    dims = {d.key: d for d in w.dimensions}
    assert dims["one_final"].score == 85


def test_urgency_high_when_expiring():
    slots = {**SLOTS, "end_date": "2025-12-01"}
    w, g, *_ = build(slots, STRONG)
    assert w.dimensions[-1].key == "urgency"
    assert {d.key: d for d in w.dimensions}["urgency"].score == 90


def test_reasons_always_three_with_citations():
    w, *_ = build(SLOTS, STRONG)
    assert len(w.reasons) == 3
    for r in w.reasons:
        assert r["citations"] and all(":" in c for c in r["citations"])


def test_claim_amount_matches_calc():
    w, *_, c = build(SLOTS, STRONG)
    assert w.claim_amount == c.total
