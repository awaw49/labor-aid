"""追问机制：像接待律师面谈——一轮要么问一个焦点，要么把一对事实小题一口气问完。

节奏规则：
1. 材料读数有疑义时，先确认材料读数（一次一条）。
2. 否则由 LLM 结合整段谈话生成"此刻最该问的事"：一个焦点，或同一件事的两小步
   （如入职日期+离职日期、公司全称+城市），措辞自然、引用用户原话。
3. 槽位集合与选项仍由确定性层供给，保证答案可进内核计算；LLM 不可用时退回模板计划轮。
"""
from __future__ import annotations

import json
import os

from .llm import LLMError, chat_json

SLOTS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "slots.json")
SLOTS = json.load(open(SLOTS_PATH, encoding="utf-8"))
BY_ID = {s["id"]: s for s in SLOTS["blocking"] + SLOTS["optional"]}

# 缺了会算错钱 / 判错时效的优先级（仅用作兜底顺序与给模型的候选说明）。
# claims 刻意不在列：诉求由事实推导（report.derive_claims），不多问用户一轮。
# employer_name 刻意不在列：全称不影响任何金额与闸门，只从话语/材料里顺手收，
# 立案前在报告「材料清单」里确认即可——开场就盘问"营业执照全名"不是咨询该有的样子。
PRIORITY = ["dispute_types", "employer_city", "still_employed", "end_date",
            "termination_by", "avg_wage", "contract_state", "start_date",
            "prior_proceeding", "termination_reason"]
MAX_PER_ROUND = 2
MAX_ASK_PER_SLOT = 2          # 同一槽位最多问 2 次：问两次还不清楚就放下，不纠缠

# 只能单独问的：情绪敏感（谁提的解除/理由/工资）或本身就是多选大题
SOLO = {"dispute_types", "termination_by", "termination_reason", "avg_wage", "still_employed"}
# 真人律师会一口气问完的事实性小组合
PAIRS = [("start_date", "end_date"),
         ("contract_state", "prior_proceeding")]

FOLLOWUP_RULES = """followup——像一位坐在对面的接待律师，决定"此刻问什么"：
- 用户刚说完话，你先在心里对照【可问缺口】，挑出对结论影响最大的事来问。
- 一般只问一个焦点；只有两个缺口本来就属于同一件事的两小步
  （如入职日期+离职日期、公司全称+在哪个城市、签没签合同+之前走过仲裁没），
  才允许问两条，且要像一口气说完的一句自然话，各管一个 slot。
- followup 可以是单个对象，也可以是两个对象的数组；拿不准就给一个。
- slot 只能从【可问缺口】里选；用户这次的话已经补上的缺口不要再问。
- 用户已经表示"说不清/不想说"的缺口不会出现在【可问缺口】里，那是刻意拿掉的，不要试图绕回去问。
- text 要像人当面说话：自然衔接用户最后一句话，必要时引用他自己的原话
  （如"你刚说公司让你明天不用来……"），先接住半句，再问事实。
- 不下法律结论，不吓唬人，不罗列三个以上问题，不用"首先/其次"。

说话方式（比什么都重要——一像机器人，用户就不肯往下说了）：
- 短句、口语，一句一个意思。称呼用"你"，不用"您"。
- 上面这些词禁的是 text 和 summary 里给用户看的话；JSON 的字段名（slots 等）照旧，不受影响。
- 禁止出现在对话里的词：系统、字段、槽位、录入、更新、标注、口径、参与计算、信息缺失、已记录。
- 不要给问题加"为什么问"的前缀，把理由揉进话里（"这个得问准，差一天时效就不一样了"）。
- 同样禁止指令性尾巴："原话就行""说具体点""举个例子"这类 coaching 词不要出现——
  要求揉进问题本身（"公司当时是怎么跟你说的？"就够了）。
- 不复述字段名，不说"关于……"、"根据您提供的信息"、"我理解您的意思是"这种书面腔。
- 可以用"嗯""行""你看""这样""那"起头，也可以说得含糊一点（"大概""差不多"），
  但不要卖萌、不要连用感叹号、不要"亲"这类客服腔。
- 追问不是审问：用户答得含糊，就把问题缩到一个能答的小口子上（"那年是 22 年还是 23 年？"）。
- 用户说得不确切（"大概八千多"），就顺着往下问一个能定案的数，别重复原问题。"""


def missing_slots(slots: dict) -> list[str]:
    out = []
    for sid in PRIORITY:
        if sid in ("termination_by", "termination_reason"):
            if "termination" not in (slots.get("dispute_types") or []):
                continue
        if sid == "end_date" and slots.get("still_employed") == "yes":
            continue    # 在职者没有离职日期，不算缺口
        if sid == "contract_state":
            if "no_contract" not in (slots.get("dispute_types") or []) and slots.get("contract_state"):
                continue
        v = slots.get(sid)
        if v in (None, "", [], "unknown"):
            out.append(sid)
    # 在职/离职合成一题：离职日期卡的「我还在职」按钮已经把 still_employed 一起答了
    if "end_date" in out:
        out = [s for s in out if s != "still_employed"]
    return out


def plan_round(askable: list[str]) -> list[str]:
    """这一轮开口问哪些：要么一个焦点，要么一对自然成组的事实小题。"""
    if not askable:
        return []
    first, rest = askable[0], list(askable[1:])
    if first in SOLO or not rest:
        return [first]
    for a, b in PAIRS:
        if first in (a, b) and (b if first == a else a) in rest:
            return [first, b if first == a else a]
    return [first]


def askable(slots: dict, skipped: set, asked: dict) -> list[str]:
    """还会开口问的缺口 = 缺失 − 用户拒答 − 问满两次的。"""
    return [s for s in missing_slots(slots)
            if s not in skipped and asked.get(s, 0) < MAX_ASK_PER_SLOT]


def missing_brief(missing: list[str], slots: dict) -> list[dict]:
    """给模型的缺口候选（含已有值的语境，便于模型判断衔接）。
    优先给完整的问句，只有没有问句时才退回示例值——"例：2023-04-01"不是给人看的问法。"""
    return [{"slot": sid, "label": BY_ID[sid]["label"],
             "ask_for": BY_ID[sid].get("question") or BY_ID[sid].get("placeholder", "")}
            for sid in missing]


def completeness(slots: dict, suspect: dict, skipped: set | None = None, asked: dict | None = None) -> dict:
    skipped = skipped or set()
    asked = asked or {}
    need = [s for s in PRIORITY if not (s in ("termination_by", "termination_reason")
            and "termination" not in (slots.get("dispute_types") or []))]
    if slots.get("still_employed") == "yes":
        need = [s for s in need if s != "end_date"]
    # 离职日期要问的时候，「我还在职」芯片会顺带答掉在职项，不把它计进待办总数
    if "end_date" in askable(slots, skipped, asked):
        need = [s for s in need if s != "still_employed"]
    done = [s for s in need if slots.get(s) not in (None, "", [], "unknown")]
    return {"done": len(done), "total": len(need), "missing": askable(slots, skipped, asked),
            "pending_confirm": list(suspect.keys()),
            "not_collectable": sorted(set(missing_slots(slots)) - set(askable(slots, skipped, asked)))}


def _fmt(v) -> str:
    if isinstance(v, float) and v.is_integer():
        return f"{int(v):,}"
    if isinstance(v, (int, float)):
        return f"{v:,}"
    return str(v)


def _confirm_question(sid: str, item: dict) -> dict:
    meta = BY_ID.get(sid, {})
    pretty = _fmt(item["value"])
    return {
        "slot": sid, "kind": "confirm",
        "text": f"我看了你发的材料，{meta.get('label', sid)}那儿写的是「{pretty}」——对得上吧？",
        "quote": item.get("quote", ""),
        "options": [{"value": "yes", "label": "对，就是这个"},
                    {"value": "no", "label": "不对，我改"}],
        "suspected": pretty,
        "help": meta.get("help", ""),
    }


SKIP_OPTION = {"value": "__skip__", "label": "这题先跳过"}


def _template_question(sid: str) -> dict:
    meta = BY_ID[sid]
    q = {
        "slot": sid, "kind": "ask",
        "text": meta["question"],
        "why": meta.get("why", ""),
        "options": [dict(o) for o in meta.get("chips", [])]
                   + [{"value": "__unsure__", "label": "我不确定"}, dict(SKIP_OPTION)],
        "help": meta.get("help", ""),
        "type": meta.get("type", "text"),
        "placeholder": meta.get("placeholder", ""),
    }
    if meta.get("type") == "multi":
        q["multi"] = True
    return q


def _one(qs: list[dict]) -> list[dict]:
    return qs[:MAX_PER_ROUND]


def next_questions(slots: dict, suspect: dict, skipped: set | None = None, asked: dict | None = None) -> list[dict]:
    """轻量版（无 LLM）：先确认材料读数（一次一条），再按计划轮问 1-2 个缺口。"""
    skipped, asked = skipped or set(), asked or {}
    for sid, item in list(suspect.items())[:1]:
        return [_confirm_question(sid, item)]
    return [_template_question(sid) for sid in plan_round(askable(slots, skipped, asked))]


def _assembled_ask(sid: str, text: str) -> dict:
    meta = BY_ID[sid]
    return {"slot": sid, "kind": "ask", "text": text, "semantic": True,
            "options": [dict(o) for o in meta.get("chips", [])]
            + [{"value": "__unsure__", "label": "我不确定"}, dict(SKIP_OPTION)],
            "help": meta.get("help", ""), "type": meta.get("type", "text"),
            "placeholder": meta.get("placeholder", ""),
            "multi": meta.get("type") == "multi"}


def _pick_semantic(raw, missing: list[str]) -> list[dict]:
    """把模型给的 followup（单个或列表）过滤成计划轮允许的 1-2 条。"""
    if isinstance(raw, dict):
        raw = [raw]
    picked = []
    for fu in raw or []:
        sid = str(fu.get("slot") or "")
        text = str(fu.get("text") or "").strip()
        if sid in missing and text:
            picked.append(_assembled_ask(sid, text))
        if len(picked) >= MAX_PER_ROUND:
            break
    # 计划轮纪律：焦点题（敏感/多选）不打包，乱配对也不如单问
    if len(picked) == 2:
        ids = [q["slot"] for q in picked]
        if ids[0] in SOLO or ids[1] in SOLO or not _paired(ids[0], ids[1], missing):
            return picked[:1]
    return picked


def _paired(a: str, b: str, askable_list: list[str]) -> bool:
    return any({a, b} == {x, y} for x, y in PAIRS) or all(s not in SOLO for s in (a, b))


def semantic_from_extract(res: dict, slots: dict, suspect: dict,
                          skipped: set | None = None, asked: dict | None = None) -> list[dict]:
    """文字路径：语义追问与抽取合并成一次调用，这里过滤成 1-2 条。"""
    skipped, asked = skipped or set(), asked or {}
    for sid, item in list(suspect.items())[:1]:
        return [_confirm_question(sid, item)]
    missing = askable(slots, skipped, asked)
    picked = _pick_semantic(res.get("followups"), missing)
    if picked:
        return picked
    return [_template_question(sid) for sid in plan_round(missing)]


def generate(story: str, slots: dict, suspect: dict,
             skipped: set | None = None, asked: dict | None = None) -> list[dict]:
    """图片/回答后的语义追问：整段叙述 + 当前槽位 → LLM 生成下一件事。
    仅在需要结合谈话语境挑问题时使用；纯点选答案走 next_questions，不花这次等待。"""
    skipped, asked = skipped or set(), asked or {}
    for sid, item in list(suspect.items())[:1]:
        return [_confirm_question(sid, item)]
    missing = askable(slots, skipped, asked)
    if not missing:
        return []
    confirmed = {k: v for k, v in slots.items() if v not in (None, "", [], "unknown")}
    try:
        data = chat_json([
            {"role": "system", "content": "你是法律援助中心的接待律师，正面对面接待来访者。"
                                          "你的任务是决定\"此刻只问哪一件事\"，只输出 JSON，不要解释。\n"
                                          + FOLLOWUP_RULES},
            {"role": "user", "content": f"来访者说过的全部话：\n{story or '（还没有说过话）'}\n\n"
                                        f"已确认的槽位：{json.dumps(confirmed, ensure_ascii=False)}\n"
                                        f"【可问缺口】：{json.dumps(missing_brief(missing, slots), ensure_ascii=False)}\n\n"
                                        "输出 JSON：{\"followup\":{\"slot\":\"...\",\"text\":\"...\",\"why\":\"...\"}}"},
        ], max_tokens=500)
    except LLMError:
        return [_template_question(sid) for sid in plan_round(missing)]   # 语义追问不可用：对话不中断
    picked = _pick_semantic(data.get("followup") or data.get("followups"), missing)
    if picked:
        return picked
    return [_template_question(sid) for sid in plan_round(missing)]


def wrap_up_text(slots: dict, skipped: set, asked: dict) -> str | None:
    """还能问的都问完了（或用户都不想答）时给一句收尾话术。"""
    if askable(slots, skipped, asked) or not missing_slots(slots):
        return None
    left = sorted(set(missing_slots(slots)) - set(askable(slots, skipped, asked)))
    names = "、".join(BY_ID[s]["label"] for s in left)
    return ("该问的差不多问完了，" + names + "这几样先放一放。结论里我写清楚哪块没问到、哪块是按保守估的。"
            "你要是想起来什么，随时补；不想补了，就点「生成结论卡」。")


def help_for(slot: str) -> dict:
    meta = BY_ID.get(slot, {})
    return {"slot": slot, "help": meta.get("help", ""), "why": meta.get("why", ""),
            "options": meta.get("chips", [])}
