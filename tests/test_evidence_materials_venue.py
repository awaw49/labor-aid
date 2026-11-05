from app.kernel.evidence import score_evidence
from app.kernel.materials import build_materials
from app.kernel.venue import build_venue

SLOTS_T = {"dispute_types": ["termination"]}


def test_no_materials_is_weak():
    r = score_evidence([], SLOTS_T)
    assert r.level == "弱" and r.score < 50
    assert r.gaps


def test_contract_plus_notice_beats_contract_alone():
    a = score_evidence([{"type": "contract"}], SLOTS_T)
    b = score_evidence([{"type": "contract"}, {"type": "termination_notice"}], SLOTS_T)
    assert b.score > a.score


def test_original_copy_bonus():
    a = score_evidence([{"type": "contract", "original": False}], SLOTS_T)
    b = score_evidence([{"type": "contract", "original": True}], SLOTS_T)
    assert b.score > a.score


def test_gap_for_missing_termination_notice():
    r = score_evidence([{"type": "contract"}], SLOTS_T)
    assert any("解除" in g for g in r.gaps)


def test_employer_burden_listed():
    r = score_evidence([], SLOTS_T)
    items = "".join(x["item"] for x in r.employer_burden)
    assert "考勤" in items and "台账" in items


def test_materials_base_always_present():
    names = [m["key"] for m in build_materials(set())]
    assert names[:4] == ["application", "id_card", "company_registry", "relation"]


def test_materials_added_per_dispute_type():
    keys = {m["key"] for m in build_materials({"termination", "overtime"})}
    assert "termination_notice" in keys and "overtime_proof" in keys


def test_materials_no_duplicates():
    items = build_materials({"termination", "unpaid_wage"})
    keys = [m["key"] for m in items]
    assert len(keys) == len(set(keys))


def test_materials_mark_uploaded():
    items = build_materials({"termination"}, {"termination_notice"})
    hit = [m for m in items if m["key"] == "termination_notice"][0]
    assert hit["have"] is True


def test_venue_has_arbitration_court_and_aid():
    import json
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    city = json.load(open(os.path.join(root, "data", "city", "hangzhou.json"), encoding="utf-8"))
    blocks = build_venue(city, {}, {"days_left": 100})
    stages = " ".join(b["stage"] for b in blocks)
    assert "仲裁" in stages and "起诉" in stages and "法律援助" in stages


def test_venue_actions_are_clickable():
    import json
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    city = json.load(open(os.path.join(root, "data", "city", "hangzhou.json"), encoding="utf-8"))
    blocks = build_venue(city, {}, {"days_left": None})
    kinds = {a["kind"] for b in blocks for a in b["actions"]}
    assert {"tel", "url", "map", "copy"} & kinds
    tel = [a["value"] for b in blocks for a in b["actions"] if a["kind"] == "tel"]
    assert "0571-87258530" in tel


def test_venue_city_caliber_included():
    import json
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    city = json.load(open(os.path.join(root, "data", "city", "hangzhou.json"), encoding="utf-8"))
    blocks = build_venue(city, {}, {"days_left": 10})
    assert any("中河中路240号" in b["where"] for b in blocks)
