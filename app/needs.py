"""语义理解层：把用户的口语叙述交给 LLM 理解，输出确定性内核能消费的枚举结果。

这里不做任何关键词匹配。用户"想要什么、属于什么情形"一律由模型语义判断；
判定结果以固定枚举 + 原话证据返回，供闸门 / 金额内核做可审计的计算。
"""
from __future__ import annotations

import hashlib
import json

from .llm import chat_json

SCOPE_KEYS = ["social_insurance_backpay", "housing_fund", "work_injury_recognization",
              "personnel_dispute", "criminal", "supervision_only"]

NEEDS_SYSTEM = """你是劳动仲裁初步咨询系统的"需求理解器"。把用户说过的全部话连起来读，
用语义理解他遇到了什么事、他的身份情形、以及解除争议的法律语义。禁止只凭个别词下结论——
同一个词在不同上下文里含义不同，必须看整段叙述。

只输出这个 JSON，不要解释：
{
 "scope_issues": [{"key": "...", "evidence": "用户原话片段"}],
 "subject_flags": {
   "retired_or_reemployment": {"value": "yes|no|unknown", "evidence": "原话或空"},
   "student_intern": {"value": "yes|no|unknown", "evidence": "原话或空"}
 },
 "termination": {
   "legality": "likely_illegal|likely_legal|uncertain|not_applicable",
   "legality_reason": "一句话法律分析",
   "resign_ground": "article38|personal|unknown|not_applicable",
   "resign_ground_reason": "一句话法律分析"
 }
}

字段语义（枚举必须精确从这里选）：

scope_issues 数组——用户诉求里"不归劳动仲裁管"或"有更快通道"的部分，没有就给空数组：
- social_insurance_backpay：用户要求单位补缴社保/调整缴费基数（若用户要的是"未缴社保造成的损失赔偿"，不算此项）
- housing_fund：住房公积金缴存/补缴
- work_injury_recognization：工伤认定、劳动能力鉴定、伤残等级本身
- personnel_dispute：事业单位在编/编制内人员的人事争议
- criminal：仅当用户的核心诉求就是追究对方刑事责任（如"我要让他坐牢""我已经报案了"）。
  用户只是顺带问"能不能报警""要不要报警"，而真实诉求仍是讨薪/赔偿的，不算此项
- supervision_only：用户诉求就是单纯举报违法用工（如只投诉超时加班），自身没有金钱主张时才算；
  顺带提到"同事说可以找劳动监察"不算

subject_flags——叙述里能否看出用户身份情形；看不出就 unknown，禁止从"年龄大""干得久"猜：
- retired_or_reemployment：已退休/达到退休年龄/退休返聘/领养老金
- student_intern：在校学生实习/兼职

termination——只有争议包含"解除/辞退/辞职"才填，否则两个都填 not_applicable：
- legality：单位解除时，结合用户给的理由判断该解除在用户叙述的事实下是否站得住脚。
  likely_illegal=理由明显不成立或无依据（如"业务调整""岗位取消"且无过错陈述、试用期不合格但无录用条件考核）；
  likely_legal=用户自述存在严重违纪、旷工、盗窃、打架、不能胜任经培训仍不胜任、客观情况重大变化等实体事由；
  uncertain=叙述信息不足以判断。
- resign_ground：自己辞职时，辞职原因是否属于《劳动合同法》第38条事由
  （未及时足额支付劳动报酬、未依法缴纳社保、未按约提供劳动保护或劳动条件等）。
  article38=用户明确说了这类事由；personal=个人原因（家里有事、找到新工作等）；unknown=没说清。

evidence 一律给用户原话的连续片段；没有原话支撑就给空字符串。不给任何法律建议。
措辞要求：用"你"或"当事人"指代来访者，不要写"用户"；理由一句话说清即可。"""


def fingerprint(story: list[str], slots: dict) -> str:
    """输入指纹：叙述或相关槽位变了才重新理解。"""
    payload = json.dumps({
        "story": story,
        "slots": {k: slots.get(k) for k in sorted(slots)
                  if k in ("dispute_types", "termination_by", "termination_reason",
                           "still_employed", "end_date", "prior_proceeding")},
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def analyze(story: list[str], slots: dict, today: str) -> dict:
    """全部口述 + 已确认槽位 → 语义理解结果（枚举 + 证据）。LLM 不可用就抛错，不做关键词兜底。"""
    narrative = "\n".join(f"- {t}" for t in story) or "（用户还没有说过话）"
    confirmed = {k: v for k, v in slots.items() if v not in (None, "", [], "unknown")}
    data = chat_json([
        {"role": "system", "content": NEEDS_SYSTEM},
        {"role": "user", "content": f"今天是 {today}。\n用户说过的全部话：\n{narrative}\n\n"
                                    f"已确认的槽位：{json.dumps(confirmed, ensure_ascii=False)}"},
    ], max_tokens=1000)

    issues, seen = [], set()
    for item in data.get("scope_issues") or []:
        key = str(item.get("key") or "").strip()
        if key in SCOPE_KEYS and key not in seen:
            seen.add(key)
            issues.append({"key": key, "evidence": str(item.get("evidence") or "")[:80]})

    def _flag(name: str) -> dict:
        raw = (data.get("subject_flags") or {}).get(name) or {}
        value = raw.get("value") if raw.get("value") in ("yes", "no", "unknown") else "unknown"
        return {"value": value, "evidence": str(raw.get("evidence") or "")[:80]}

    term_raw = data.get("termination") or {}
    legality = term_raw.get("legality")
    if legality not in ("likely_illegal", "likely_legal", "uncertain", "not_applicable"):
        legality = "not_applicable"
    ground = term_raw.get("resign_ground")
    if ground not in ("article38", "personal", "unknown", "not_applicable"):
        ground = "not_applicable"
    return {
        "scope_issues": issues,
        "subject_flags": {"retired_or_reemployment": _flag("retired_or_reemployment"),
                          "student_intern": _flag("student_intern")},
        "termination": {"legality": legality,
                        "legality_reason": str(term_raw.get("legality_reason") or "")[:200],
                        "resign_ground": ground,
                        "resign_ground_reason": str(term_raw.get("resign_ground_reason") or "")[:200]},
    }


def needs_for(session, today: str) -> dict:
    """会话级缓存：输入指纹没变就复用上一次的语义理解。"""
    slots = session.confirmed_slots()
    fp = fingerprint(session.story, slots)
    if session.needs is not None and session.needs_fp == fp:
        return session.needs
    needs = analyze(session.story, slots, today)
    session.needs, session.needs_fp = needs, fp
    return needs
