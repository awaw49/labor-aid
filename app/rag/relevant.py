"""按争议类型与案件情形选择"应当一并告知"的法条（规则表，不是模型生成）。

只返回条号；是否真实存在由 LawCorpus 校验，校验不过就丢弃。
"""
from __future__ import annotations

BASE_TERMINATION = ["laodonghetongfa:46", "laodonghetongfa:47", "laodonghetongfa:87"]

BY_TYPE = {
    "termination": BASE_TERMINATION,
    "no_contract": ["laodonghetongfa:10", "laodonghetongfa:14", "laodonghetongfa:82"],
    "unpaid_wage": ["laodonghetongfa:30", "laodonghetongfa:50"],
    "overtime": ["laodongfa:41", "laodongfa:44"],
    "annual_leave": ["nianxiujia:3", "nianxiujia:5"],
    "social_insurance": ["shebaofa:58", "shebaofa:63"],
    "noncompete": ["laodonghetongfa:23", "laodonghetongfa:24"],
    "confirm_relation": ["laodonghetongfa:7", "laodonghetongfa:10"],
}

BY_CLAIM = {
    "compensation_2n": ["laodonghetongfa:87"],
    "compensation_n": ["laodonghetongfa:46"],
    "double_wage": ["laodonghetongfa:82", "sfjs2:6"],
    "wage": ["laodonghetongfa:50"],
    "annual_leave_pay": ["nianxiujia:5"],
    "confirm_relation": ["laodonghetongfa:7"],
}


def relevant_articles(slots: dict, needs: dict | None = None) -> list[dict]:
    types = set(slots.get("dispute_types") or [])
    claims = set(slots.get("claims") or [])
    out: list[dict] = []
    seen: set[str] = set()

    def add(cid: str, why: str):
        if cid and cid not in seen:
            seen.add(cid)
            out.append({"id": cid, "why": why})

    for t in sorted(types):
        for cid in BY_TYPE.get(t, []):
            add(cid, f"争议类型：{t}")
    for c in sorted(claims):
        for cid in BY_CLAIM.get(c, []):
            add(cid, f"诉求：{c}")

    term = (needs or {}).get("termination") or {}
    if "termination" in types:
        if term.get("legality") == "likely_legal":
            add("laodonghetongfa:39", "单位主张合法解除的实体依据")
        if term.get("resign_ground") == "article38":
            add("laodonghetongfa:38", "被迫解除的法定事由")
        elif slots.get("termination_by") == "employee":
            add("laodonghetongfa:37", "劳动者主动辞职")
        if slots.get("termination_by") == "mutual":
            add("laodonghetongfa:36", "协商一致解除")
    special = set(slots.get("special_status") or [])
    if "pregnancy" in special or "三期" in str(slots.get("termination_reason") or ""):
        add("laodonghetongfa:42", "三期女职工解除限制")
    reason = str(slots.get("termination_reason") or "")
    if any(k in reason for k in ("调岗", "降薪", "降职")):
        add("laodonghetongfa:35", "变更劳动合同需协商一致")
    if "no_contract" in types and slots.get("contract_state") == "two_plus":
        add("laodonghetongfa:14", "连续订立二次固定期限合同后的无固定期限")
    return out
