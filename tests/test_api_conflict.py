"""接口级测试：冲突必回问、未确认图片值不进计算、确认后才生效。

LLM 在这里被替换成固定返回（只替换外部模型，不替换被测逻辑）。
"""
from fastapi.testclient import TestClient

from app import extract as extract_mod
from app.main import app

client = TestClient(app)


def _stub(monkeypatch, slots, followups=None, summary="好的"):
    def fake(text, known, brief=None):
        return {"slots": slots, "conflicts": [], "summary": summary,
                "followups": followups or [], "meta": {}}
    monkeypatch.setattr(extract_mod, "extract_from_text", fake)


def test_conflict_is_asked_not_silently_overwritten(monkeypatch):
    sid = client.post("/api/session").json()["session_id"]
    _stub(monkeypatch, {"avg_wage": {"value": 8000.0, "evidence": "八千", "source": "oral"}})
    client.post(f"/api/session/{sid}/text", json={"text": "我一个月八千"})
    _stub(monkeypatch, {"avg_wage": {"value": 8600.0, "evidence": "八千六", "source": "oral"}})
    r = client.post(f"/api/session/{sid}/text", json={"text": "不对，是八千六"}).json()
    kinds = [m["kind"] for m in r["messages"]]
    assert "conflict" in kinds
    assert r["conflicts"] and r["conflicts"][0]["slot"] == "avg_wage"
    assert r["slots"]["avg_wage"]["value"] == 8000.0        # 未被悄悄覆盖

    fixed = client.post(f"/api/session/{sid}/answer",
                        json={"slot": "avg_wage", "value": 8600}).json()
    assert fixed["slots"]["avg_wage"]["value"] == 8600.0
    assert not fixed["conflicts"]


def test_unconfirmed_image_value_waits_for_click(monkeypatch):
    sid = client.post("/api/session").json()["session_id"]
    monkeypatch.setattr(extract_mod, "extract_from_image",
                        lambda b64, mime, raw=None: {
                            "doc_type": "payslip", "readable": "清晰",
                            "employer": "杭州云帆科技有限公司",
                            "dates": [], "reason": "", "amounts": [],
                            "suspects": [{"slot": "avg_wage", "value": 8600,
                                          "quote": "应发合计 8,600.00"}],
                            "notes": "", "ocr_engine": "stub"})
    files = {"file": ("p.png", b"\x89PNG\r\n\x1a\n", "image/png")}
    r = client.post(f"/api/session/{sid}/image", files=files).json()
    assert "avg_wage" in r["suspect"]
    assert r["slots"].get("avg_wage") is None               # 未确认不写槽位
    assert any(q.get("kind") == "confirm" for q in r["questions"])

    c = client.post(f"/api/session/{sid}/confirm", json={"slot": "avg_wage"}).json()
    assert c["slots"]["avg_wage"]["value"] == 8600
    assert c["slots"]["avg_wage"]["source"] == "image_confirmed"
    assert not c["suspect"]


def test_report_asks_when_claim_type_unknown(monkeypatch):
    """律师不会在不知道你要解决什么时下结论，但也不会因为缺金额就拒绝给意见。"""
    sid = client.post("/api/session").json()["session_id"]
    r = client.post(f"/api/session/{sid}/report", json={})
    assert r.status_code == 409
    assert "missing" in r.json()["detail"]


def test_report_works_without_wage_and_marks_open_questions(monkeypatch):
    from app import needs as needs_mod
    monkeypatch.setattr(needs_mod, "needs_for", lambda *a, **k: {
        "scope_issues": [],
        "subject_flags": {"retired_or_reemployment": {"value": "no", "evidence": ""},
                          "student_intern": {"value": "no", "evidence": ""}},
        "termination": {"legality": "likely_illegal", "legality_reason": "无依据",
                        "resign_ground": "not_applicable", "resign_ground_reason": ""},
    })
    sid = client.post("/api/session").json()["session_id"]
    _stub(monkeypatch, {"dispute_types": {"value": ["termination"], "evidence": "把我开了", "source": "oral"},
                        "termination_by": {"value": "employer", "evidence": "公司让我走的", "source": "oral"}})
    client.post(f"/api/session/{sid}/text", json={"text": "公司把我开了"})
    r = client.post(f"/api/session/{sid}/report", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["preliminary"] is True
    assert any(q["label"] for q in body["open_questions"])


def test_unknown_answer_is_not_asked_twice(monkeypatch):
    sid = client.post("/api/session").json()["session_id"]
    _stub(monkeypatch, {"dispute_types": {"value": ["termination"], "evidence": "被开", "source": "oral"}})
    client.post(f"/api/session/{sid}/text", json={"text": "我被开了"})
    for _ in range(3):
        client.post(f"/api/session/{sid}/answer", json={"slot": "employer_name", "value": "不清楚"})
    state = client.get(f"/api/session/{sid}").json()
    asked = [q["slot"] for q in state["questions"]]
    assert "employer_name" not in asked or state["completeness"]["done"] >= 1


def test_turn_never_leaves_dialog_hanging():
    """没问题可问时必须转成给意见，不能只回一句就停住。"""
    from app import session as store
    from app.main import _turn
    s = store.create()
    first = _turn(s, [])
    assert first[0]["kind"] == "offer"
    second = _turn(s, [])
    assert second[0]["kind"] == "ack" and "看意见" in second[0]["text"]


def test_answer_with_no_more_questions_offers_opinion(monkeypatch):
    from app import followup as followup_mod
    sid = client.post("/api/session").json()["session_id"]
    monkeypatch.setattr(followup_mod, "next_questions", lambda *a, **k: [])
    r = client.post(f"/api/session/{sid}/answer", json={"slot": "employer_city", "value": "杭州市"}).json()
    kinds = [m["kind"] for m in r["messages"]]
    assert "offer" in kinds


def test_closing_phrases_go_straight_to_opinion(monkeypatch):
    from app.main import _is_closing
    for t in ["没有了", "就这些", "先这样吧", "给我个结论", "别问了"]:
        assert _is_closing(t) is True
    for t in ["公司还欠我一个月工资", "我在杭州上班"]:
        assert _is_closing(t) is False

    sid = client.post("/api/session").json()["session_id"]
    r = client.post(f"/api/session/{sid}/text", json={"text": "没有了"}).json()
    assert [m["kind"] for m in r["messages"]] == ["offer"]
