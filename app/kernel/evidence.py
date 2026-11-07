"""证据强度打分：材料类型 × 是否书证 × 是否原件 × 争议类型的关键证据。纯规则。"""
from __future__ import annotations

from dataclasses import dataclass, field

# 材料类型 → (显示名, 分值说明)
MATERIAL_TYPES = {
    "contract": ("书面劳动合同/录用通知", "劳动关系 + 工资标准 + 岗位"),
    "bank_flow": ("银行工资流水", "劳动关系 + 工资标准"),
    "payslip": ("工资条", "工资构成与应发额"),
    "tax_record": ("个税申报记录", "工资标准（单位申报）"),
    "social_record": ("社保缴纳记录", "劳动关系 + 在职期间"),
    "termination_notice": ("解除通知/辞退邮件", "解除事实、主体、日期、理由"),
    "resignation_cert": ("离职证明", "解除事实与日期"),
    "chat_record": ("微信/钉钉聊天记录", "加班安排、口头辞退、调岗降薪"),
    "attendance": ("考勤/打卡/排班记录", "出勤、加班时长、休假记录"),
    "badge": ("工牌/工作证/工作群", "事实劳动关系"),
    "wage_claim_log": ("催讨记录（书面/聊天）", "时效中断 + 欠薪事实"),
    "witness": ("同事证言", "辅助证明"),
}

ALIASES = {"si_record": "social_record", "leave_record": "attendance",
           "noncompete_agreement": "contract", "company_registry": "badge",
           "tax": "tax_record", "chat": "chat_record", "payslip_record": "payslip"}

BURDEN_ON_EMPLOYER = [
    ("考勤记录、加班审批记录", "《劳动争议调解仲裁法》第六条：与争议事项有关的证据属于用人单位掌握管理的，用人单位应当提供"),
    ("工资支付台账、工资发放记录", "工资台账由单位保管，劳动者主张欠发时单位应提供"),
    ("解除劳动合同的决定及依据", "单位解除的，由单位对解除合法性举证"),
    ("规章制度及公示、告知记录", "单位以严重违纪解除时，须证明制度合法有效且已告知"),
]

# 争议类型 → 关键证据（类型, 分值）
SPECIFIC = {
    "unpaid_wage": [("bank_flow", 22), ("payslip", 20)],
    "overtime": [("attendance", 22), ("chat_record", 10)],
    "annual_leave": [("attendance", 22)],
    "social_insurance": [("social_record", 22)],
    "noncompete": [("contract", 22)],
    "no_contract": [("badge", 14), ("bank_flow", 14)],
    "confirm_relation": [("badge", 14), ("social_record", 16)],
    "termination": [("termination_notice", 20)],
}


@dataclass
class EvidenceResult:
    score: int
    level: str
    dimensions: dict
    gaps: list[str] = field(default_factory=list)
    strong: list[str] = field(default_factory=list)
    employer_burden: list[dict] = field(default_factory=list)


def _canon(t: str) -> str:
    return ALIASES.get(t, t)


def score_evidence(materials: list[dict], slots: dict) -> EvidenceResult:
    have = {_canon(m["type"]) for m in materials if m.get("confirmed", True)}
    types = set(slots.get("dispute_types") or [])

    relation = 0
    for t, w in (("contract", 30), ("bank_flow", 24), ("social_record", 20),
                 ("attendance", 12), ("badge", 10), ("chat_record", 8)):
        if t in have:
            relation = max(relation, w)

    wage = 0
    for t, w in (("payslip", 25), ("bank_flow", 24), ("tax_record", 22), ("contract", 16)):
        if t in have:
            wage = max(wage, w)

    termination = 0
    if "termination" in types:
        for t, w in (("termination_notice", 25), ("resignation_cert", 18), ("chat_record", 13)):
            if t in have:
                termination = max(termination, w)
    else:
        termination = 18

    specific = 0
    for t in types:
        for key, w in SPECIFIC.get(t, []):
            if key in have:
                specific = max(specific, w)
    if not specific:
        specific = 8

    original_bonus = 6 if any(m.get("original") for m in materials) else 0
    raw = relation + wage + termination + specific + original_bonus
    maximum = 30 + 25 + (25 if "termination" in types else 18) + 22 + 6
    score = max(0, min(100, round(raw * 100 / maximum)))

    gaps: list[str] = []
    strong: list[str] = []
    if relation < 20:
        gaps.append("缺少能直接证明劳动关系的书证（合同/流水/社保记录），建议先补银行流水或社保记录")
    if wage < 20:
        gaps.append("工资标准证据偏弱：个税 App 的收入纳税明细可以替代工资条")
    if "termination" in types and "termination_notice" not in have:
        gaps.append("没有书面解除通知：请截图 HR 的微信/钉钉辞退消息，或提供离职证明")
    if "overtime" in types and "attendance" not in have:
        gaps.append("加班缺打卡/排班记录：可申请仲裁委向单位调取考勤（单位掌握管理的由单位举证）")
    if "annual_leave" in types and "attendance" not in have:
        gaps.append("年休假缺请假/考勤记录：先导出 OA 或考勤系统的年假余额")
    if "social_insurance" in types and "social_record" not in have:
        gaps.append("社保争议缺参保缴费记录：「电子社保卡」小程序可查并截图")
    for t in sorted(have):
        if t in MATERIAL_TYPES:
            strong.append(MATERIAL_TYPES[t][0])

    level = "强" if score >= 75 else ("中" if score >= 50 else "弱")
    return EvidenceResult(
        score=score, level=level,
        dimensions={"劳动关系": relation, "工资标准": wage, "解除事实": termination,
                    "争议关键证据": specific, "原件加分": original_bonus},
        gaps=gaps, strong=strong,
        employer_burden=[{"item": i, "rule": r} for i, r in BURDEN_ON_EMPLOYER],
    )
