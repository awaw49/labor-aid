"""金额内核：N / 2N / 二倍工资 / 加班费 / 未休年假。

算术只接受已确认字段，保证可审计；"解除是否违法、辞职是否第 38 条事由"
这类语义判断由 app/needs.py（LLM）给出枚举，本模块只消费枚举，不做关键词猜测。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


def _d(v):
    if isinstance(v, date):
        return v
    if not v:
        return None
    try:
        y, m, dd = str(v).replace("/", "-").split("-")[:3]
        return date(int(y), int(m), int(dd))
    except (ValueError, TypeError):
        return None


@dataclass
class ServiceYears:
    start: date | None
    end: date | None
    years: float          # 用于 N 的年限（满 6 个月不满一年按 1 年，不满 6 个月按 0.5）
    raw_years: float
    months: int
    label: str


def service_years(start_v, end_v) -> ServiceYears:
    start, end = _d(start_v), _d(end_v) or date.today()
    if not start:
        return ServiceYears(None, None, 0.0, 0.0, 0, "缺失入职日期")
    if end < start:
        return ServiceYears(start, end, 0.0, 0.0, 0, "日期倒置")

    full_years = end.year - start.year - ((end.month, end.day) < (start.month, start.day))
    try:
        anniversary = date(start.year + full_years, start.month, start.day)
    except ValueError:                      # 2 月 29 日入职
        anniversary = date(start.year + full_years, start.month, 28)
    months = (end.year - anniversary.year) * 12 + end.month - anniversary.month
    if end.day < anniversary.day:
        months -= 1
    months = max(0, months)
    remainder_days = (end - anniversary).days

    if remainder_days == 0:
        years = float(full_years)
    elif months >= 6:
        years = float(full_years + 1)
    else:
        years = full_years + 0.5

    total_months = full_years * 12 + months
    label = f"{full_years} 年 {months} 个月" if full_years else f"{months} 个月"
    return ServiceYears(start, end, float(years), round((end - start).days / 365.0, 2),
                        total_months, label)


@dataclass
class CalcResult:
    items: list[dict] = field(default_factory=list)
    total: float = 0.0
    notes: list[str] = field(default_factory=list)

    def add(self, key, label, amount, basis, detail, primary=True, group=None):
        amount = round(float(amount), 2)
        self.items.append({"key": key, "label": label, "amount": amount,
                           "basis": basis, "detail": detail,
                           "primary": primary, "group": group})
        if primary:
            self.total += amount


def severance_base(avg_wage: float, city_avg_wage: float | None) -> tuple[float, bool]:
    """3 倍社平封顶（《劳动合同法》第 47 条第 2 款）。"""
    if not city_avg_wage:
        return avg_wage, False
    cap = city_avg_wage * 3
    return (cap, True) if avg_wage > cap else (avg_wage, False)


def calc_all(slots: dict, city: dict, today: date | None = None,
             termination: dict | None = None) -> CalcResult:
    """slots 必须全部是"已确认"字段。未确认字段不会出现在 slots_effective 中。
    termination：语义理解层的解除语义（legality / resign_ground）。"""
    r = CalcResult()
    p = city["params"]
    sy = service_years(slots.get("start_date"), slots.get("end_date"))
    avg = float(slots.get("avg_wage") or 0)
    types = set(slots.get("dispute_types") or [])
    by = slots.get("termination_by")
    termination = termination or {}

    if not avg:
        r.notes.append("缺少已确认的月平均应发工资，金额区间无法给出单值")
    base, capped = severance_base(avg, p.get("avg_wage_monthly")) if avg else (0, False)
    if capped:
        r.notes.append(f"月工资高于{city['city']}上年度职工月平均工资 3 倍（{p['avg_wage_monthly']}×3），"
                       f"基数按 {base:.0f} 元封顶，年限最高 12 年")

    # 1) 解除类
    if "termination" in types and slots.get("still_employed") == "yes":
        r.notes.append("你还在职，目前没有解除事实，经济补偿 / 赔偿金暂不计入；"
                       "如果已经被口头辞退，把最后工作日补上再算")
    elif "termination" in types and avg and sy.start:
        years_for_n = min(sy.years, 12.0) if capped else sy.years
        n_amount = base * years_for_n
        if by == "employer":
            legality = termination.get("legality")
            if legality == "likely_illegal":
                illegal = True
            elif legality == "likely_legal":
                illegal = False
            else:   # uncertain：无解除合法性的实体证据时按违法口径评估，由单位举证
                illegal = not slots.get("termination_evidence")
            r.add("n_or_2n", "经济补偿 N（备选）", n_amount, "laodonghetongfa:47",
                  f"工作年限 {sy.label} → 计 {years_for_n} 个月 × {base:.0f} 元",
                  primary=not illegal, group="termination")
            r.add("2n", "违法解除赔偿金 2N", n_amount * 2, "laodonghetongfa:87",
                  "单位解除且无合法事由时，按第 47 条标准的两倍支付",
                  primary=illegal, group="termination")
            if illegal:
                why = (termination.get("legality_reason") or "解除理由缺乏可成立的实体依据").rstrip("。；;，, ")
                r.notes.append(f"解除合法性评估：{why}，按 2N 评估")
        elif by == "employee":
            if termination.get("resign_ground") == "article38":
                r.add("n_amount_38", "被迫解除经济补偿 N", n_amount,
                      "laodonghetongfa:38;laodonghetongfa:46",
                      "以单位未足额支付报酬/未缴社保等第 38 条事由解除，仍可主张 N："
                      + (termination.get("resign_ground_reason") or ""))
            else:
                r.add("n_amount_0", "经济补偿（个人原因辞职）", 0.0, "laodonghetongfa:37",
                      "劳动者主动辞职且非第 38 条事由，原则上无经济补偿")
        elif by == "mutual":
            r.add("n_amount_mutual", "协商一致解除经济补偿 N", n_amount,
                  "laodonghetongfa:36;laodonghetongfa:46", "单位提出、协商一致解除，支付 N")
        else:
            r.add("n_or_2n_unknown", "经济补偿区间（解除主体不明）", n_amount,
                  "laodonghetongfa:46", "解除主体未确认，暂按 N 计，若系单位违法解除可升至 2N")

    if "termination" in types and avg and not sy.start:
        r.notes.append("入职日期未确认，工作年限算不出来，经济补偿/赔偿金金额先不给出——补上入职日期后自动补全，"
                       "不影响其他项与路径判断")

    # 2) 未签书面合同二倍工资（最多 11 个月）
    if "no_contract" in types and avg and slots.get("contract_state") == "none":
        start = _d(slots.get("start_date"))
        end = _d(slots.get("end_date")) or today or date.today()
        if start:
            from datetime import timedelta
            begin = start + timedelta(days=30)
            stop = min(end, start + timedelta(days=365))
            today_d = today or date.today()
            window_start = max(begin, today_d - timedelta(days=365))
            claimable = max(0, int(round((stop - window_start).days / 30.44))) if stop > window_start else 0
            months = min(claimable, 11)
            if months:
                r.add("double_wage", "未签书面合同二倍工资差额", avg * months,
                      "laodonghetongfa:82;sfjs2:6",
                      f"自用工满 1 个月次日起至满 1 年止，其中最近一年内的 {months} 个月 × {avg:.0f} 元"
                      + ("（更早月份已过按月计算的仲裁时效）" if claimable < int(round((stop - begin).days / 30.44)) else ""))
            else:
                r.notes.append("二倍工资期间已超过一年仲裁时效（按月分别计算），本次不计入标的额")

    if "no_contract" in types and slots.get("contract_state") == "two_plus":
        r.notes.append("已签两次固定期限合同：第二次到期后单位应订无固定期限；"
                       "若仍不订，可依《劳动合同法》第 82 条第 2 款主张二倍工资，需先确认第二次到期日")

    # 3) 加班费（按已确认的加班小时数；没有就只给提示）
    if "overtime" in types:
        hours = slots.get("overtime_hours")
        if hours and avg:
            hourly = avg / 21.75 / 8
            r.add("overtime", "加班费（按已确认加班小时）", hourly * float(hours) * 1.5,
                  "laodongfa:44", f"{hours} 小时 × 时薪 {hourly:.2f} × 1.5（工作日加班口径）")
        else:
            r.notes.append("加班时长未确认，本次不计算加班费金额，只给举证与主张路径")

    # 4) 未休年休假
    if "annual_leave" in types and avg:
        days = slots.get("unused_leave_days")
        if days:
            r.add("annual_leave", "未休年休假工资", avg / 21.75 * float(days) * 2,
                  "nianxiujia:5", f"{days} 天 × 日工资 {avg/21.75:.2f} × 200%（另 100% 已含在正常工资中）")

    # 5) 欠薪
    if "unpaid_wage" in types:
        owed = slots.get("unpaid_amount")
        if owed:
            r.add("unpaid_wage", "拖欠工资", float(owed), "laodongfa:50", "按已确认欠付金额")

    r.total = round(r.total, 2)
    return r
