import os
from datetime import date

from app.rag.retriever import CaseCorpus, LawCorpus
from app.report import build_report
from tests.conftest import make_session, needs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = date(2026, 11, 4)
LAWS = LawCorpus()
CASES = CaseCorpus()


def test_corpus_has_12_laws_and_700_articles():
    assert len(LAWS.laws) == 12
    assert len(LAWS.articles) >= 700


def test_exact_article_lookup():
    a = LAWS.get("laodonghetongfa:87")
    assert a and "二倍" in a["text"] and a["no_cn"] == "第八十七条"


def test_missing_article_returns_none():
    assert LAWS.get("laodonghetongfa:999") is None
    assert LAWS.get("nope:1") is None


def test_search_finds_double_wage_article():
    ids = [x["id"] for x in LAWS.search("未签书面劳动合同 二倍工资", 8)]
    assert any(i == "laodonghetongfa:82" for i in ids)


def test_fake_citation_is_reported_invalid():
    good, bad = LAWS.by_ids(["laodonghetongfa:87", "laodonghetongfa:1234"])
    assert [g["id"] for g in good] == ["laodonghetongfa:87"]
    assert bad == ["laodonghetongfa:1234"]


def test_case_matching_by_type():
    got = CASES.match({"no_contract"})
    assert got and all(c["tags"] for c in got)


def test_case_text_has_sources():
    for c in CASES.cases:
        # 官方案例给出可核对的官网链接；公开裁判文书只摘录要旨，不给外链
        assert c["source_url"] == "" or c["source_url"].startswith("https://")
        assert c["source"] and c["holding"] and c["comparable"] and c["limit"]


SLOTS = {"employer_name": "杭州云帆科技有限公司", "employer_city": "杭州市",
         "start_date": "2023-11-01", "end_date": "2026-09-15", "avg_wage": 8600,
         "dispute_types": ["termination", "no_contract"], "still_employed": "no",
         "prior_proceeding": "none", "termination_by": "employer",
         "termination_reason": "试用期不合格", "contract_state": "none",
         "claims": ["compensation_2n", "double_wage"]}
N = needs(legality="likely_illegal", legality_reason="试用期主张不成立")


def report(slots=None, materials=None, n=None):
    s = make_session({**SLOTS, **(slots or {})}, materials=materials or ["termination_notice", "contract"])
    return build_report(s, T, needs=n or N)


def test_report_has_four_blocks():
    r = report()
    assert r["conclusion"] and r["materials"] and r["venue"] and r["citations"]
    assert r["disclaimer"] and r["hotlines"]


def test_report_never_cites_outside_corpus():
    r = report()
    assert r["conclusion"]["citation_check"]["invalid"] == []
    assert all(LAWS.get(a["id"]) for a in r["citations"]["articles"])


def test_report_decision_recommend_with_evidence():
    r = report()
    assert r["conclusion"]["decision"] == "recommend"


def test_report_blocks_when_out_of_scope():
    r = report({"dispute_types": ["social_insurance"]},
               n=needs(scope=["social_insurance_backpay"]))
    assert r["conclusion"]["decision"] == "cannot"


def test_report_downgrade_when_no_citations(monkeypatch):
    from app import report as report_mod
    monkeypatch.setattr(report_mod.LAWS, "by_ids", lambda ids: ([], list(ids)))
    r = report()
    assert r["conclusion"]["citation_check"]["degraded"] is True
    assert "人工咨询" in r["conclusion"]["label"]


def test_unconfirmed_image_value_not_in_calc():
    s = make_session(SLOTS, materials=["contract"], suspect={"avg_wage": {"value": 99999, "quote": "x"}})
    s.suspect["avg_wage"] = {"value": 99999, "quote": "x"}
    s.slots["avg_wage"]["confirmed"] = False
    r = build_report(s, T, needs=N)
    assert r["conclusion"]["claim_amount"] != 99999 * 6


def test_cases_attached_have_comparable_and_limit():
    r = report()
    assert r["citations"]["cases"]
    for c in r["citations"]["cases"]:
        assert c["comparable"] and c["limit"]
        assert c["source_url"] == "" or c["source_url"].startswith("https://")


def test_materials_have_burden_and_how():
    r = report()
    for m in r["materials"]:
        assert m["burden"] and m["how"] and m["purpose"]


def test_deadline_in_report_matches_rule():
    r = report()
    assert r["conclusion"]["deadline"]["deadline"] == "2027-09-15"
