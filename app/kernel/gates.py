"""三层漏斗闸门：受案范围 / 资格 / （值得性由 worth.py 负责）。

"用户遇到了什么"由语义理解层（app/needs.py，LLM）判定并以枚举传入；
本模块只负责把枚举结果接到法条路由与时效计算上，保证判定可回溯、可单测。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date

from .deadline import compute_deadline
from .. import city as city_store

# 《劳动争议调解仲裁法》第二条六类受案范围
ARTICLE_2_CATEGORIES = [
    {"no": 1, "text": "因确认劳动关系发生的争议", "types": ["confirm_relation", "no_contract"]},
    {"no": 2, "text": "因订立、履行、变更、解除和终止劳动合同发生的争议", "types": ["termination", "no_contract"]},
    {"no": 3, "text": "因除名、辞退和辞职、离职发生的争议", "types": ["termination"]},
    {"no": 4, "text": "因工作时间、休息休假、社会保险、福利、培训以及劳动保护发生的争议", "types": ["overtime", "annual_leave", "social_insurance"]},
    {"no": 5, "text": "因劳动报酬、工伤医疗费、经济补偿或者赔偿金等发生的争议", "types": ["unpaid_wage", "termination"]},
    {"no": 6, "text": "法律、法规规定的其他劳动争议", "types": ["noncompete", "other"]},
]

# 不归仲裁的情形 → 指路表
ROUTES = {
    "social_insurance_backpay": {
        "title": "社保补缴 / 社保缴费基数",
        "reason": "社会保险费的征缴属行政管理，不属劳动争议仲裁受案范围（要求补缴不给结论，只指路）",
        "to": "社保经办机构 / 税务部门 / 劳动保障监察",
        "actions": [
            {"kind": "tel", "label": "拨打 12333 咨询补缴", "value": "12333"},
            {"kind": "text", "label": "到用人单位所在区社保经办窗口申请稽核", "value": "稽核补缴"},
        ],
        "article": "shebaofa:63",
    },
    "housing_fund": {
        "title": "住房公积金",
        "reason": "住房公积金争议由住房公积金管理中心处理，不属劳动仲裁",
        "to": "住房公积金管理中心",
        "actions": [{"kind": "tel", "label": "拨打 12329", "value": "12329"}],
        "article": None,
    },
    "work_injury_recognization": {
        "title": "工伤认定 / 伤残等级",
        "reason": "工伤认定与劳动能力鉴定属人社部门行政程序，是工伤保险待遇的前置程序，不能直接仲裁",
        "to": "用人单位所在地人社部门工伤认定机构",
        "actions": [
            {"kind": "tel", "label": "拨打 12333 问工伤认定窗口", "value": "12333"},
            {"kind": "text", "label": "准备：工伤认定申请表、劳动关系证明、医疗诊断证明", "value": "工伤认定材料"},
        ],
        "article": "gongshang:17",
    },
    "personnel_dispute": {
        "title": "事业单位在编人员人事争议",
        "reason": "在编人员人事争议适用人事争议仲裁（另一套规则与机构）",
        "to": "人事争议仲裁委员会（人社部门）",
        "actions": [{"kind": "tel", "label": "拨打 12333 问人事争议仲裁", "value": "12333"}],
        "article": None,
    },
    "criminal": {
        "title": "涉嫌拒不支付劳动报酬罪等刑事问题",
        "reason": "是否构成犯罪由司法机关认定，本系统不作任何定性",
        "to": "公安机关 / 检察院",
        "actions": [{"kind": "tel", "label": "报警 110", "value": "110"}],
        "article": None,
    },
    "supervision_only": {
        "title": "单纯违法用工举报（未缴社保、超时加班等）",
        "reason": "此类事项可走劳动保障监察投诉，可能比仲裁更快；监察与仲裁可以并行",
        "to": "劳动保障监察机构",
        "actions": [{"kind": "tel", "label": "拨打 12333 投诉", "value": "12333"}],
        "article": "jiancha:9",
    },
}

@dataclass
class Layer:
    key: str
    name: str
    status: str                      # pass | warn | fail | out_of_scope
    message: str
    detail: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    route: dict | None = None


@dataclass
class GateResult:
    layers: list[Layer]
    can_arbitrate: bool
    scope_issues: list[str]
    mapped_categories: list[dict]
    deadline: dict

    def to_dict(self):
        return {
            "layers": [l.__dict__ for l in self.layers],
            "can_arbitrate": self.can_arbitrate,
            "scope_issues": self.scope_issues,
            "mapped_categories": self.mapped_categories,
            "deadline": self.deadline,
        }


def scope_issues_from_needs(needs: dict) -> list[str]:
    """语义理解结果 → 受案范围问题（只保留有路由表 entries 的 key，保持顺序去重）。"""
    seen, out = set(), []
    for i in needs.get("scope_issues") or []:
        key = str(i.get("key") or "")
        if key in ROUTES and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def map_categories(types: set[str]) -> list[dict]:
    hit = []
    for c in ARTICLE_2_CATEGORIES:
        if types & set(c["types"]):
            hit.append({"no": c["no"], "text": c["text"]})
    return hit or [{"no": 6, "text": ARTICLE_2_CATEGORIES[5]["text"]}]


def run_gates(slots: dict, city: dict, needs: dict, today: date | None = None) -> GateResult:
    today = today or date.today()
    types = set(slots.get("dispute_types") or [])
    issues = scope_issues_from_needs(needs)
    layers: list[Layer] = []

    # ---------- 第一层：受案范围 ----------
    if issues:
        primary = ROUTES[issues[0]]
        layers.append(Layer(
            key="scope", name="第一层 · 归不归劳动仲裁管", status="out_of_scope",
            message=primary["reason"],
            detail=[f"另涉及：{ROUTES[i]['title']}（{ROUTES[i]['to']}）" for i in issues[1:]],
            citations=[primary["article"]] if primary["article"] else [],
            route=primary,
        ))
        scope_fail = True
    else:
        cats = map_categories(types)
        layers.append(Layer(
            key="scope", name="第一层 · 归不归劳动仲裁管", status="pass",
            message="属于《劳动争议调解仲裁法》第二条规定的受案范围：" + "；".join(c["text"] for c in cats),
            citations=["tiaojiezhongcai:2"],
        ))
        scope_fail = False

    # ---------- 第二层：资格 ----------
    qual_detail: list[str] = []
    qual_status = "pass"
    qual_citations = ["tiaojiezhongcai:2"]

    # 主体（身份情形由语义理解层判定）
    flags = needs.get("subject_flags") or {}
    retired = (flags.get("retired_or_reemployment") or {}).get("value")
    intern = (flags.get("student_intern") or {}).get("value")
    if retired == "yes":
        qual_status = "warn"
        qual_detail.append("叙述里提到已退休或返聘：这种情况通常按劳务关系处理，先确认关系性质再决定走哪条路")
    if intern == "yes":
        qual_status = "warn"
        qual_detail.append("叙述里提到在校实习：一般不认定为劳动关系，按劳务/实习协议处理")
    if not slots.get("employer_name"):
        qual_status = "warn"
        qual_detail.append("缺少用人单位全称：无法确认被申请人与管辖")

    # 时效
    dl = compute_deadline(slots, today)
    deadline_dict = {
        "start_rule": dl.start_rule,
        "start_date": dl.start_date.isoformat() if dl.start_date else None,
        "deadline": dl.deadline.isoformat() if dl.deadline else None,
        "days_left": dl.days_left,
        "urgency": dl.urgency,
        "basis": dl.basis,
        "exceptions": dl.exceptions,
    }
    if dl.days_left is not None and dl.days_left < 0:
        qual_status = "fail"
        qual_detail.append(f"已超过一年仲裁时效（{dl.start_rule}）")
    elif dl.days_left is not None:
        qual_citations.append("tiaojiezhongcai:27")
        qual_detail.append(f"时效起算：{dl.start_rule}；剩余 {dl.days_left} 天")

    # 管辖（口径文件目前覆盖北上广深杭五城；未覆盖城市不冒用任何城市的金额）
    city_name = city_store.normalize(slots.get("employer_city"))
    if city_name and not city_store.covered(slots):
        qual_status = "out_of_scope"
        qual_detail.append(f"{city_name}的仲裁窗口与金额线（社平工资封顶、最低工资）不在本系统覆盖内；"
                           "受案范围、时效、解除合法性的判断按国家法律全国通用，金额请按当地口径确认")
    elif not city_name:
        qual_status = "warn" if qual_status == "pass" else qual_status
        qual_detail.append("用人单位所在地未确认：管辖需按“用人单位所在地或劳动合同履行地”确定")

    # 一事不再理
    prior = slots.get("prior_proceeding") or "none"
    if prior in ("arbitration_done", "court_done"):
        qual_status = "fail"
        qual_detail.append("同一请求已有生效裁决/判决：一事不再理，不能重复申请（裁决被撤销的除外）")
        qual_citations.append("sfjs1:6")
    elif prior == "settled":
        qual_status = "warn" if qual_status == "pass" else qual_status
        qual_detail.append("已签和解/调解协议：原则上不再受理；如存在欺诈、胁迫或重大误解，可另行主张撤销，但不承诺结果")

    layer2 = Layer(
        key="qualification", name="第二层 · 够不够格申请", status=qual_status,
        message={
            "pass": "主体、时效、管辖、是否重复申请，四项都没有障碍",
            "warn": "可以申请，但有关键事项需先确认",
            "fail": "存在硬性障碍，暂不具备申请条件",
            "out_of_scope": (f"你这事本身归劳动仲裁管，但我的金额口径目前只覆盖北京、上海、广州、深圳、杭州五城，"
                             f"{city_name}的具体数字我不猜"),
        }[qual_status],
        detail=qual_detail, citations=sorted(set(qual_citations)),
    )
    if qual_status == "out_of_scope":
        layer2.route = {
            "title": "跨城市办理",
            "reason": "金额口径与窗口信息备了北京、上海、广州、深圳、杭州五城；你的争议类型本身可以仲裁，"
                      f"{city_name}的具体数字我不猜",
            "to": "当地劳动人事争议仲裁委员会（一般设在区/县人社局）",
            "actions": [{"kind": "tel", "label": "拨打当地 12333", "value": "12333"}],
        }
    layers.append(layer2)

    can = (not scope_fail) and qual_status in ("pass", "warn")
    return GateResult(
        layers=layers, can_arbitrate=can, scope_issues=issues,
        mapped_categories=map_categories(types), deadline=deadline_dict,
    )
