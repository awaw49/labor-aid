"""仲裁时效起算与倒计时（纯规则，可单测）。

依据：《劳动争议调解仲裁法》第二十七条；例外见该条第四款。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

LABOR_PAY_TYPES = {"unpaid_wage", "overtime"}          # 劳动报酬类
STATUTORY_DEADLINE_DAYS = 365
URGENT_DAYS = 60


@dataclass
class DeadlineResult:
    start_rule: str
    start_date: date | None
    deadline: date | None
    days_left: int | None
    urgency: str                        # high | normal | none
    basis: list[str] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)
    disputed_window: str | None = None


def _d(v: Any) -> date | None:
    if isinstance(v, date):
        return v
    if not v:
        return None
    try:
        y, m, dd = str(v).replace("/", "-").split("-")[:3]
        return date(int(y), int(m), int(dd))
    except (ValueError, TypeError):
        return None


def compute_deadline(slots: dict, today: date | None = None) -> DeadlineResult:
    """slots 中只读取 start_date / end_date / still_employed / dispute_types /
    last_claim_date 五个字段。"""
    today = today or date.today()
    end = _d(slots.get("end_date"))
    start = _d(slots.get("start_date"))
    still = slots.get("still_employed") == "yes"
    types = set(slots.get("dispute_types") or [])
    basis = ["tiaojiezhongcai:27"]

    if still and types & LABOR_PAY_TYPES:
        return DeadlineResult(
            start_rule="劳动关系存续期间主张劳动报酬，不受一年仲裁时效限制",
            start_date=None, deadline=None, days_left=None, urgency="none",
            basis=basis,
            exceptions=["劳动关系一旦终止，应在终止之日起一年内提出（同条第四款）"],
        )

    if still:
        return DeadlineResult(
            start_rule="仍在职，且非劳动报酬争议：自知道或应当知道权利被侵害之日起一年",
            start_date=end or today, deadline=None, days_left=None, urgency="normal",
            basis=basis,
            exceptions=["在职期间请尽早固定证据；离职后再申请也需在一年内"],
        )

    if not end:
        return DeadlineResult(
            start_rule="缺少离职日期，无法计算时效",
            start_date=None, deadline=None, days_left=None, urgency="normal",
            basis=basis,
            exceptions=["请补充离职（或最后工作日）日期"],
        )

    if types & LABOR_PAY_TYPES:
        start_rule = "劳动关系终止后，拖欠劳动报酬应自终止之日起一年内提出"
    elif "termination" in types:
        start_rule = "解除/终止劳动合同争议，自解除或终止之日起一年"
    elif "no_contract" in types:
        start_rule = "未签书面合同二倍工资：按月分别起算一年时效（以每月应付之日为起点）"
    elif "annual_leave" in types:
        start_rule = "未休年休假工资争议，自劳动关系终止之日起一年（各地口径不一）"
    elif "social_insurance" in types:
        start_rule = "社保待遇损失赔偿，自知道或应当知道损失发生之日起一年"
    else:
        start_rule = "自知道或应当知道权利被侵害之日起一年"

    claim = _d(slots.get("last_claim_date"))
    if claim and claim <= today and claim >= end:
        start_date = claim
        start_rule += "；因向对方主张权利/向有关部门请求救济，时效中断后重新计算"
        basis = basis + ["tiaojiezhongcai:27"]
    else:
        start_date = end

    deadline = start_date + timedelta(days=STATUTORY_DEADLINE_DAYS)
    days_left = (deadline - today).days
    urgency = "high" if days_left <= URGENT_DAYS else "normal"
    if days_left < 0:
        urgency = "high"

    exceptions: list[str] = []
    if "no_contract" in types:
        exceptions.append("二倍工资按月计算时效：超出申请日前一年的月份可能已过时效（个案口径不同，需现场确认）")
    if days_left < 0:
        exceptions.append("已超过一年：可核查是否存在中断、中止事由（如曾书面主张权利、投诉、单位同意履行）")
    if "annual_leave" in types:
        exceptions.append("年休假工资性质存在争议，部分仲裁委按劳动报酬处理，建议尽早申请")

    return DeadlineResult(
        start_rule=start_rule, start_date=start_date, deadline=deadline,
        days_left=days_left, urgency=urgency, basis=basis, exceptions=exceptions,
    )
