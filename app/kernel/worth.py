"""值得性六维加权：规则实现，输出可解释分项与三选一结论。"""
from __future__ import annotations

from dataclasses import dataclass, field

WEIGHTS = {
    "amount_cost": 0.25,
    "evidence": 0.25,
    "one_final": 0.10,
    "enforcement": 0.15,
    "alternative": 0.10,
    "urgency": 0.15,
}
LABELS = {
    "amount_cost": "标的额与成本比",
    "evidence": "证据强度",
    "one_final": "一裁终局影响",
    "enforcement": "执行可能性",
    "alternative": "替代路径优越性",
    "urgency": "时效剩余",
}


@dataclass
class Dimension:
    key: str
    label: str
    weight: float
    score: int
    note: str


@dataclass
class WorthResult:
    score: int
    decision: str                 # recommend | better_alternative | not_recommended
    decision_label: str           # 展示用的一句话（如「建议仲裁」）
    dimensions: list[Dimension] = field(default_factory=list)
    reasons: list[dict] = field(default_factory=list)
    alternative: dict | None = None
    claim_amount: float = 0.0

    def to_dict(self):
        return {
            "score": self.score, "decision": self.decision,
            "decision_label": self.decision_label,
            "dimensions": [d.__dict__ for d in self.dimensions],
            "reasons": self.reasons, "alternative": self.alternative,
            "claim_amount": self.claim_amount,
        }


def _amount_score(amount: float, money_claim: bool = False) -> tuple[int, str]:
    if amount <= 0:
        if money_claim:
            return 50, "金额还算不出来（缺工资基数或离职日），但诉求本身是金钱请求，先把数算清"
        return 30, "诉求里没有可计算的金额（确认/抗辩类），金额维度按中性处理"
    if amount < 3000:
        return 25, f"标的额约 {amount:,.0f} 元，低于一个月工资量级，时间成本可能超过收益"
    if amount < 8000:
        return 45, f"标的额约 {amount:,.0f} 元，扣除误工与往返成本后收益有限"
    if amount < 20000:
        return 65, f"标的额约 {amount:,.0f} 元，值得投入一次仲裁"
    if amount < 50000:
        return 80, f"标的额约 {amount:,.0f} 元，明显高于程序成本"
    return 90, f"标的额约 {amount:,.0f} 元，程序成本占比低"


def compute_worth(slots: dict, gates, evidence, calc, city: dict,
                  termination: dict | None = None, materials_given: bool = True) -> WorthResult:
    p = city["params"]
    types = set(slots.get("dispute_types") or [])
    amount = calc.total if calc else 0.0
    termination = termination or {}
    dims: list[Dimension] = []

    money_claims = {"compensation_2n", "compensation_n", "double_wage", "wage", "annual_leave_pay"}
    a_score, a_note = _amount_score(amount, bool(set(slots.get("claims") or []) & money_claims))
    dims.append(Dimension("amount_cost", LABELS["amount_cost"], WEIGHTS["amount_cost"], a_score, a_note))

    if not materials_given:
        dims.append(Dimension("evidence", LABELS["evidence"], WEIGHTS["evidence"], 60,
                              "材料还没上传：结论先按你口述的事实给；照清单备齐材料，这块分会更准"))
    else:
        dims.append(Dimension("evidence", LABELS["evidence"], WEIGHTS["evidence"],
                              evidence.score, f"证据强度 {evidence.level}（{evidence.score}/100）；"
                              + ("有书证支撑关键事实" if evidence.score >= 70 else "关键事实仍缺口述支撑")))

    threshold = p["one_final_award_threshold"]
    one_final_types = {"unpaid_wage", "termination", "overtime", "annual_leave", "social_insurance"}
    if amount and amount <= threshold and (types & one_final_types):
        dims.append(Dimension("one_final", LABELS["one_final"], WEIGHTS["one_final"], 85,
                              f"标的额 {amount:,.0f} 元未超过{city['city']}一裁终局线 {threshold:,} 元"
                              f"（最低工资 {p['min_wage_monthly']}×12）："
                              "裁决作出即生效，单位不能起诉只能申请撤销，对劳动者有利"))
    elif amount > threshold:
        dims.append(Dimension("one_final", LABELS["one_final"], WEIGHTS["one_final"], 60,
                              f"标的额 {amount:,.0f} 元超过{city['city']}一裁终局线 {threshold:,} 元，单位不服可起诉，周期可能延长"))
    else:
        dims.append(Dimension("one_final", LABELS["one_final"], WEIGHTS["one_final"], 60,
                              "金额还没算出来，确认工资与工作年限后再看是否在一裁终局线内"))

    status = slots.get("company_status")
    if status == "abnormal":
        e_score, e_note = 20, "单位已停业/失联：即使胜诉也可能执行不到钱，优先考虑财产保全线索"
    elif status == "normal":
        e_score, e_note = 85, "单位正常经营：裁决后执行可行性较高"
    elif not slots.get("employer_name"):
        e_score, e_note = 50, ("公司全称还没从话里或材料里拿到——不影响算钱；"
                               "立案前用「电子营业执照」小程序确认全称与存续状态即可")
    else:
        e_score, e_note = 55, "单位经营状态未确认：先在「电子营业执照」小程序查是否注销、吊销或经营异常"
    dims.append(Dimension("enforcement", LABELS["enforcement"], WEIGHTS["enforcement"], e_score, e_note))

    alt = None
    alt_score, alt_note = 65, "未发现明显更优的替代路径"
    if "unpaid_wage" in types and amount and amount <= 10000 and status != "abnormal":
        alt = {"key": "supervision", "title": "先走劳动保障监察投诉（欠薪快速通道）",
               "why": f"欠薪 {amount:,.0f} 元、单位仍在经营：监察投诉通常比仲裁快，且可并行",
               "tel": "12333"}
        alt_score, alt_note = 35, "欠薪金额不大且单位仍在经营，监察投诉更快"
    elif "termination" in types and amount and amount <= 3000 and status == "normal":
        alt = {"key": "mediation", "title": "先申请调解或协商",
               "why": "标的额很小，调解结案更快且不伤关系", "tel": "12348"}
        alt_score, alt_note = 40, "标的额很小，调解/协商更划算"
    dims.append(Dimension("alternative", LABELS["alternative"], WEIGHTS["alternative"], alt_score, alt_note))

    days = gates.deadline.get("days_left")
    if days is None and slots.get("still_employed") == "yes":
        u_score, u_note = 50, "仍在职：时效未开始跑，但关系成本需要考虑"
    elif days is None:
        u_score, u_note = 50, "时效起算点未确认"
    elif days < 0:
        u_score, u_note = 90, "已超过一年时效，需先解决时效障碍"
    elif days <= 60:
        u_score, u_note = 90, f"仅剩 {days} 天，属最高优先级，应立刻准备材料"
    elif days <= 180:
        u_score, u_note = 70, f"剩余 {days} 天，建议一个月内提交"
    else:
        u_score, u_note = 55, f"剩余 {days} 天，时间相对充裕"
    dims.append(Dimension("urgency", LABELS["urgency"], WEIGHTS["urgency"], u_score, u_note))

    total = round(sum(d.score * d.weight for d in dims))

    defense_only = ("noncompete" in types
                    and not (money_claims & set(slots.get("claims") or []))
                    and "confirm_relation" not in (slots.get("claims") or []))
    personal_quit = (slots.get("termination_by") == "employee"
                     and (termination or {}).get("resign_ground") == "personal")
    if defense_only:
        decision, label = "not_recommended", "不用主动去，等对方主张时再抗辩"
    elif personal_quit and total < 62:
        decision, label = "not_recommended", "按现在的情况没有经济补偿，不用为此申请仲裁"

    elif total >= 62 and not (alt and total < 70):
        decision, label = "recommend", "建议仲裁"
    elif alt:
        decision, label = "better_alternative", "可仲裁，但有更好的路"
    else:
        decision, label = "not_recommended", "先别急着提交，把材料补齐再说"

    reasons = _build_reasons(dims, slots, gates, evidence, amount, alt, termination,
                             city=city, threshold=threshold)
    return WorthResult(score=total, decision=decision, decision_label=label,
                       dimensions=dims, reasons=reasons, alternative=alt, claim_amount=amount)


def _build_reasons(dims, slots, gates, evidence, amount, alt, termination: dict,
                   city: dict, threshold: int) -> list[dict]:
    types = set(slots.get("dispute_types") or [])
    reasons = []
    term = termination or {}

    if "noncompete" in types and not (set(slots.get("claims") or []) & {"compensation_n", "compensation_2n", "wage"}):
        reasons.append({
            "text": "竞业限制只对高级管理人员、高级技术人员和其他负有保密义务的人有效；普通岗位通常不受约束，不必主动申请仲裁",
            "citations": ["laodonghetongfa:24", "laodonghetongfa:23"], "source": "规则"})
    elif slots.get("termination_by") == "employee" and term.get("resign_ground") == "personal":
        reasons.append({
            "text": "自己提出辞职、且不属于未足额发工资或未依法缴社保等情形，原则上没有经济补偿",
            "citations": ["laodonghetongfa:37", "laodonghetongfa:46"], "source": "规则"})
    elif "termination" in types and slots.get("termination_by") == "employer":
        legality = termination.get("legality")
        if legality == "likely_legal":
            reasons.append({
                "text": "解除由单位提出，且你叙述的事实显示存在可成立的解除事由，按 N（经济补偿）评估；"
                        "若能证明事由不成立或程序违法，可升格主张 2N",
                "citations": ["laodonghetongfa:47", "laodonghetongfa:87"],
                "source": "规则",
            })
        else:
            why = termination.get("legality_reason")
            reasons.append({
                "text": "解除由单位提出，理由难以成立" + (f"（{why}）" if why else "") +
                        "，按违法解除评估，可主张 2N（经济补偿的两倍）",
                "citations": ["laodonghetongfa:87", "laodonghetongfa:47"],
                "source": "规则",
            })
    elif "no_contract" in types and slots.get("contract_state") == "none":
        reasons.append({
            "text": "未订立书面劳动合同，可主张自用工满一个月次日起的二倍工资差额（最多 11 个月）",
            "citations": ["laodonghetongfa:82", "sfjs2:6"],
            "source": "规则",
        })
    elif "unpaid_wage" in types:
        reasons.append({
            "text": "拖欠劳动报酬属受案范围，且在职期间主张不受一年时效限制",
            "citations": ["laodonghetongfa:50", "tiaojiezhongcai:27"],
            "source": "规则",
        })
    elif "social_insurance" in types:
        reasons.append({
            "text": "因单位未缴社保导致的待遇损失可主张赔偿（要求补缴本身走行政渠道）",
            "citations": ["shebaofa:63"],
            "source": "规则",
        })
    else:
        reasons.append({
            "text": "争议事项属于《劳动争议调解仲裁法》第二条受案范围，可以申请仲裁",
            "citations": ["tiaojiezhongcai:2"],
            "source": "规则",
        })

    days = gates.deadline.get("days_left")
    if days is not None and days <= 60:
        reasons.append({
            "text": f"仲裁时效仅剩 {days} 天，属最高优先级，应立即提交申请以保住权利",
            "citations": ["tiaojiezhongcai:27"], "source": "规则",
        })
    else:
        if evidence.strong:
            reasons.append({
                "text": f"现有材料：{'、'.join(evidence.strong[:3])}；证据强度 {evidence.score}/100（{evidence.level}）",
                "citations": ["tiaojiezhongcai:6"], "source": "规则",
            })
        else:
            reasons.append({
                "text": "目前还没有书证，关键事实只有口述，先把材料清单里的东西补上",
                "citations": ["tiaojiezhongcai:6"], "source": "规则",
            })

    personal_quit = (slots.get("termination_by") == "employee"
                     and (termination or {}).get("resign_ground") == "personal")
    if personal_quit or ("noncompete" in types and amount <= 0):
        pass
    elif amount and amount <= threshold:
        reasons.append({
            "text": f"标的额约 {amount:,.0f} 元，未超过{city['city']}一裁终局线 {threshold:,} 元，裁决作出即生效，单位不能起诉",
            "citations": ["tiaojiezhongcai:47", "tiaojiezhongcai:48"], "source": "规则",
        })
    elif amount <= 0:
        reasons.append({
            "text": "按现在的事实算不出可主张的金额，先把事实或材料补齐，再判断值不值得去",
            "citations": ["tiaojiezhongcai:6"], "source": "规则",
        })
    elif alt:
        reasons.append({"text": alt["why"], "citations": ["jiancha:9", "laodonghetongfa:85"], "source": "规则"})
    else:
        reasons.append({
            "text": f"标的额约 {amount:,.0f} 元，扣除程序成本后仍值得主张",
            "citations": ["laodonghetongfa:47"], "source": "规则",
        })
    return reasons[:3]
