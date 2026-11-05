"""劳动仲裁初步咨询助手 · API。"""
from __future__ import annotations
import base64
import json
import os
import re
import time
from datetime import date

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import asr, city as city_store, config, extract, followup, report, session as store
from . import settings as settings_store
from .llm import LLMError, chat_json, probe
from .rag.retriever import LawCorpus, CaseCorpus

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "static")
DATA = config.DATA_DIR

app = FastAPI(title="劳动仲裁初步咨询助手", version="3.0")

DOC_NAMES = {"termination_notice": "解除劳动合同通知书", "contract": "劳动合同/录用通知",
             "payslip": "工资条", "bank_flow": "银行流水", "chat": "聊天记录截图",
             "attendance": "考勤/排班记录", "social_record": "社保缴纳记录", "other": "材料"}


def _fmt(v) -> str:
    if isinstance(v, float) and v.is_integer():
        return f"{int(v):,}"
    if isinstance(v, (int, float)):
        return f"{v:,}"
    return str(v)


def _doc_name(t: str) -> str:
    return DOC_NAMES.get(t, t)
LAWS = LawCorpus()
CASES = CaseCorpus()
SLOTS = json.load(open(os.path.join(DATA, "slots.json"), encoding="utf-8"))


ENUM_LABELS = {
    "contract_state": {"none": "一次没签", "one": "签过1次", "two_plus": "签过2次及以上"},
    "prior_proceeding": {"none": "没走过程序", "arbitration_done": "仲裁过", "court_done": "诉讼过", "settled": "签过和解/调解协议"},
    "still_employed": {"yes": "还在职", "no": "已离职"},
    "termination_by": {"employer": "单位提出解除", "employee": "自己辞职", "mutual": "协商一致解除"},
}
DISPUTE_LABELS = {"unpaid_wage": "欠薪", "termination": "解除", "no_contract": "未签合同",
                  "overtime": "加班费", "annual_leave": "年休假", "social_insurance": "社保",
                  "noncompete": "竞业限制", "other": "其他"}
CLAIM_LABELS = {"compensation_2n": "2N赔偿", "compensation_n": "N补偿", "double_wage": "二倍工资",
                "wage": "补发工资", "annual_leave_pay": "年假工资", "confirm_relation": "确认劳动关系",
                "unsure": "还没想好"}
ENUM_LABELS["termination_by"]["unknown"] = "不确定"


def _pretty_value(slot: str, value) -> str:
    if isinstance(value, list):
        return "、".join(_pretty_value(slot, v) for v in value)
    if isinstance(value, float) and value.is_integer():
        value = int(value)          # 8600.0 念出来像机器
    if slot == "dispute_types":
        return DISPUTE_LABELS.get(value, str(value))
    if slot == "claims":
        return CLAIM_LABELS.get(value, str(value))
    return ENUM_LABELS.get(slot, {}).get(value, str(value))


_FILLERS = ("行", "嗯", "好", "明白")


def _ack(slot: str, val_txt: str) -> str:
    """接话只在重复用户的值，语气词按值轮换——真人不会每句都"好，记下了"；
    值太长（比如公司全称）就不复述了，念一遍反而像机器。"""
    f = _FILLERS[len(val_txt) % len(_FILLERS)]
    head = f"{val_txt}，{f}，" if len(val_txt) <= 8 else f"{f}，"
    if slot in ("dispute_types", "claims"):
        if "还没想好" in val_txt:
            return "行，主张先不定，我按你说的事实来捋。"
        return head + "这几件分开记。"
    if slot in ("avg_wage", "unpaid_amount"):
        return head + "我按这个数算。"
    if slot in ("start_date", "end_date", "last_claim_date"):
        return head + "日子记下了。"
    return head + "记下了。"


# 输入框里常见的"答不上来"短语：当作"我不确定"处理，不报错、不反复问
_META_ANSWERS = {"不知道", "不清楚", "不知道啊", "记不清", "不记得", "没注意", "没看",
                 "没有", "没有啊", "不确定", "说不清", "忘了", "没写", "没给", "没发过"}


_CLOSING = {
    "没有了", "没了", "没别的了", "没别的", "就这些", "就这样", "先这样", "不说了", "不想说了",
    "给个结论", "给结论", "说结论", "直接说结论", "先给个结论", "给我个结论", "先给我个结论",
    "别问了", "先别问了", "不用问了", "问完了",
}


def _is_closing(text: str) -> bool:
    """用户明确表示说完了 / 要结论——这条规则不交给模型，避免偶发抽风后又把话题拖回去。"""
    t = re.sub(r"[\s。，,！!？?~、；;：:]+", "", text or "")
    t = re.sub(r"[吧啊呀呢哦哈]+$", "", t)
    return t in _CLOSING or t.endswith("给我个结论") or t.startswith("直接给结论")


def _meta_answer(text: str) -> bool:
    return text.strip().rstrip("。.!！？?") in _META_ANSWERS


class TextIn(BaseModel):
    text: str
    source: str = "text"


class AnswerIn(BaseModel):
    slot: str
    value: object


class ConfirmIn(BaseModel):
    slot: str
    value: object | None = None


def _state(s: store.Session) -> dict:
    return {
        "session_id": s.id,
        "slots": s.slots,
        "suspect": s.suspect,
        "conflicts": s.conflicts,
        "completeness": followup.completeness(s.all_slots(), s.suspect, s.skipped, s.asked),
        "questions": followup.next_questions(s.all_slots(), s.suspect, s.skipped, s.asked),
        "materials": s.materials,
    }


def _asked(s: store.Session, qs: list[dict]):
    """记下这一轮问过谁：问满两次的槽位自动放下。"""
    for q in qs:
        if q.get("kind") == "ask":
            s.asked[q["slot"]] = s.asked.get(q["slot"], 0) + 1


def _turn(s: store.Session, qs: list[dict], force_offer: bool = False) -> list[dict]:
    """一轮对话的收尾：有问题就继续问，没有问题就转为给意见，不能停在半空。"""
    if qs and not force_offer:
        _asked(s, qs)
        return [{"role": "assistant", "kind": "questions", "questions": qs}]
    if force_offer or not getattr(s, "offered", False):
        return [_offer(s)]
    return [{"role": "assistant", "kind": "ack",
             "text": "我这边问完了。你想到什么随时补，不想补的话直接看意见就行。"}]


def _offer(s: store.Session) -> dict:
    """律师主动收尾：不再追问，转为给出书面意见。"""
    s.offered = True
    return {"role": "assistant", "kind": "offer",
            "text": "我这边先按你已经说的情况，把意见写成一份书面的给你。",
            "action": "查看律师意见"}


def _followup_msgs(s: store.Session, qs: list[dict]) -> list[dict]:
    """追问；问无可问时由律师收尾，任何一条用户输入都要有回应。"""
    _asked(s, qs)
    if qs and not s.wrap_up:
        return [{"role": "assistant", "kind": "questions", "questions": qs}]
    return _turn(s, [])


@app.get("/api/health")
def health():
    return {"ok": True, "today": date.today().isoformat(), "city": city_store.resolve({})["city"],
            "laws": len(LAWS.articles), "cases": len(CASES.cases),
            "asr_model": os.path.exists(os.path.join(ROOT, "models", f"faster-whisper-{config.ASR_MODEL}", "model.bin"))}


@app.post("/api/session")
def new_session():
    s = store.create()
    s.messages.append({"role": "assistant", "kind": "intro",
                       "text": "坐吧，别急。事情从头说就行，记得多少说多少，说不清的地方咱们后头再补。"
                               "我这儿不做代理，听完只帮你捋三件事：该不该去仲裁、去了带什么、到哪儿交。"})
    return {**_state(s), "messages": s.messages}


@app.get("/api/session/{sid}")
def get_session(sid: str):
    s = store.get(sid)
    if not s:
        raise HTTPException(404, "session not found")
    return {**_state(s), "messages": s.messages}


@app.post("/api/session/{sid}/text")
def post_text(sid: str, body: TextIn):
    s = store.get(sid)
    if not s:
        raise HTTPException(404, "session not found")
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "empty text")
    s.story.append(text)
    s.messages.append({"role": "user", "kind": "text", "text": text, "source": body.source})

    if _is_closing(text):
        s.wrap_up = True
        msgs = _turn(s, [], force_offer=True)
        s.messages.extend(msgs)
        return {**_state(s), "messages": msgs, "extracted": {}}

    try:
        res = extract.extract_from_text(text, s.slots, followup.missing_brief(
            followup.missing_slots(s.all_slots()), s.all_slots()))
    except LLMError as e:
        # 上游抖动：把这条消息回滚，让前端原样重试，避免出现"说了但没被记住"
        s.story.pop()
        s.messages.pop()
        raise HTTPException(503, {"message": "模型服务刚抖了一下，正在重试", "retryable": True,
                                  "detail": str(e)[:120]})

    conflicts = []
    for slot, item in res["slots"].items():
        if slot in s.suspect:
            s.suspect.pop(slot, None)
        old = s.slots.get(slot)
        if old and old.get("confirmed") and old["value"] != item["value"]:
            if slot in ("dispute_types", "claims"):
                merged = sorted(set(old["value"]) | set(item["value"]))
                s.set_slot(slot, merged, "oral", True, item.get("evidence", ""))
                continue
            conflicts.append({"slot": slot, "old": old["value"], "new": item["value"],
                              "old_source": old.get("source"), "evidence": item.get("evidence", "")})
            s.conflicts = conflicts
            continue
        s.set_slot(slot, item["value"], item.get("source", "oral"), True, item.get("evidence", ""))
        if s.last_report:
            s.offered = False

    if not s.slots.get("dispute_types", {}).get("value"):
        inferred = []
        if s.slots.get("termination_by", {}).get("value") in ("employer", "employee", "mutual") or s.slots.get("end_date"):
            inferred.append("termination")
        if s.slots.get("unpaid_amount", {}).get("value"):
            inferred.append("unpaid_wage")
        if s.slots.get("contract_state", {}).get("value") == "none":
            inferred.append("no_contract")
        if inferred:
            s.set_slot("dispute_types", inferred, "inferred", True)

    got_new_facts = bool(res.get("slots")) or bool(res.get("conflicts"))
    # 谈话信号：不知道 / 不想说 / 要结论 —— 律师的做法是接住，然后换个话题
    meta_sig = res.get("meta") or {}
    signal, about = meta_sig.get("signal"), meta_sig.get("about_slot")
    ack = None
    if signal in ("unknown_answer", "refuse_details") and about:
        s.skipped.add(about)
        if signal == "unknown_answer":
            s.asked[about] = followup.MAX_ASK_PER_SLOT
        if about in ("claims", "dispute_types"):
            ack = None
        else:
            ack = {"role": "assistant", "kind": "ack",
                   "text": ("没事，记不清就记不清，先放着——回头翻翻工资条或者合同，上面一般都有。"
                            if signal == "unknown_answer" else
                            "行，不说也没事，我不问了。意见里我把这块写成‘没问到’，按保守的算。")}
    elif signal == "want_report":
        s.wrap_up = True
    pause_only = (signal == "refuse_details" and not about and not got_new_facts)

    msgs = []
    if res.get("summary"):
        summ = res["summary"].strip()
        if any(k in summ for k in ("对吧", "对吗", "是不是", "对不对")):
            # 模型自己已经问过"对吧"，保留它原来的问号，只补句末标点
            if summ[-1] not in "。！？…":
                summ += "。"
        else:
            summ = summ.rstrip("。！？… ") + "。"
            # 这轮听出了新事实才需要复述确认；纯接话/安抚不再补"我理解得对吗"
            if got_new_facts and len(summ) >= 12:
                summ += "我这么理解对吧？哪儿说错了你直接改。"
        msgs.append({"role": "assistant", "kind": "summary", "text": summ})
    for c in conflicts:
        meta = followup.BY_ID.get(c["slot"], {})
        msgs.append({"role": "assistant", "kind": "conflict",
                     "text": f"等等，这儿对不上——{meta.get('label', c['slot'])}你先前说「{c['old']}」，"
                             f"这回说「{c['new']}」。哪个准？",
                     "slot": c["slot"]})
    if ack:
        msgs.append(ack)
    if s.wrap_up:
        msgs.extend(_turn(s, [], force_offer=True))
    elif pause_only:
        msgs.append({"role": "assistant", "kind": "pause",
                     "text": "不着急，等你缓过来咱接着说，或者随时点下面的「看律师意见」。"})
    else:
        msgs.extend(_followup_msgs(s, followup.semantic_from_extract(
            res, s.all_slots(), s.suspect, s.skipped, s.asked)))
    s.messages.extend(msgs)
    return {**_state(s), "messages": msgs, "extracted": res["slots"]}


@app.post("/api/session/{sid}/answer")
def answer(sid: str, body: AnswerIn):
    s = store.get(sid)
    if not s:
        raise HTTPException(404, "session not found")
    slot, value = body.slot, body.value
    meta = followup.BY_ID.get(slot, {})

    if value == "__skip__":
        s.skipped.add(slot)
        ack = {"role": "assistant", "kind": "ack",
               "text": "行，这个就不填了。结论里我写清楚这块没问到、按保守的算——想起来随时补。"}
        s.messages.append(ack)
        msgs = [ack] + _turn(s, followup.generate(s.text(), s.all_slots(), s.suspect, s.skipped, s.asked))
        s.messages.extend(msgs[1:])
        return {**_state(s), "messages": msgs}

    if value == "__unsure__":
        s.asked[slot] = followup.MAX_ASK_PER_SLOT   # 说不清的不反复问
        return {"help": followup.help_for(slot), **_state(s)}

    if slot == "end_date" and value == "still_employed":
        s.set_slot("still_employed", "yes", "user", True)
        s.slots.pop("end_date", None)
        s.suspect.pop("end_date", None)
        qs = followup.next_questions(s.all_slots(), s.suspect, s.skipped, s.asked)
        ack_onjob = {"role": "assistant", "kind": "ack", "text": "还在职，那就不算离职日。"}
        msgs = [ack_onjob] + _turn(s, qs)
        s.messages.extend(msgs[1:])
        return {**_state(s), "messages": msgs}
    if slot in ("start_date", "end_date", "last_claim_date"):
        v = extract.norm_date(value)
        if not v:
            if isinstance(value, str) and _meta_answer(value):
                s.asked[slot] = followup.MAX_ASK_PER_SLOT
                return {"help": followup.help_for(slot), **_state(s)}
            raise HTTPException(422, "日期需要能确定年月日，例如 2026-03-15；说不清可以点「我不确定」")
        value = v
    if slot in ("avg_wage", "unpaid_amount"):
        v = extract.norm_money(value)
        if not v:
            if isinstance(value, str) and _meta_answer(value):
                s.asked[slot] = followup.MAX_ASK_PER_SLOT
                return {"help": followup.help_for(slot), **_state(s)}
            raise HTTPException(422, "金额没读懂，请填数字，例如 8600；说不清可以点「我不确定」")
        value = v
    if slot in ("dispute_types", "claims"):
        value = value if isinstance(value, list) else [value]
    if slot == "end_date" and value == "still_employed":
        s.set_slot("still_employed", "yes", "user", True)
        slot, value = "still_employed", "yes"

    s.set_slot(slot, value, "user", True)
    if slot == "still_employed" and value == "yes":
        s.slots.pop("end_date", None)
    s.suspect.pop(slot, None)
    s.conflicts = [c for c in s.conflicts if c["slot"] != slot]
    val_txt = _pretty_value(slot, value)
    ack = {"role": "assistant", "kind": "ack", "text": _ack(slot, val_txt)}
    s.messages.append(ack)
    qs = followup.generate(s.text(), s.all_slots(), s.suspect, s.skipped, s.asked)
    msgs = [ack] + _turn(s, qs)
    s.messages.extend(msgs[1:])
    return {**_state(s), "messages": msgs}


@app.post("/api/session/{sid}/image")
async def upload_image(sid: str, file: UploadFile = File(...)):
    s = store.get(sid)
    if not s:
        raise HTTPException(404, "session not found")
    raw = await file.read()
    if len(raw) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "图片过大（>12MB）")
    mime = file.content_type or "image/jpeg"
    b64 = base64.b64encode(raw).decode()

    try:
        data = extract.extract_from_image(b64, mime, raw)
    except LLMError as e:
        raise HTTPException(503, {"message": "图片识别暂时不可用，请再试一次", "retryable": True,
                                  "detail": str(e)[:120]})

    doc_type = data.get("doc_type") or "other"
    material_type = extract.DOC_TO_MATERIAL.get(doc_type, "wage_claim_log")
    s.add_material(material_type, {"doc_type": doc_type, "readable": data.get("readable"),
                                   "notes": data.get("notes", "")})

    suspected = extract.image_to_suspected(data)
    conflicts = []
    for slot, item in suspected.items():
        confirmed = s.slots.get(slot)
        if confirmed and confirmed.get("confirmed"):
            if confirmed["value"] != item["value"]:
                conflicts.append({"slot": slot, "old": confirmed["value"], "new": item["value"],
                                  "old_source": confirmed.get("source"), "quote": item.get("quote", "")})
            continue
        s.suspect[slot] = item

    s.messages.append({"role": "user", "kind": "image", "text": f"[发了张{_doc_name(doc_type)}]"})
    head = f"这张是{_doc_name(doc_type)}，{data.get('readable') or '能看清'}。"
    if suspected:
        pairs = "；".join(
            f"{followup.BY_ID[k]['label']} {_fmt(v['value']).rstrip('。；;，,、 ')}"
            for k, v in suspected.items())
        body = (f"上面写着：{pairs}。你扫一眼对得上吗——你点头之前，这些数我不往账上算。")
    else:
        body = "没读出能直接用的日期或者数字。要不补拍一张清楚点的，要不你直接跟我说。"
    msgs = [{"role": "assistant", "kind": "image_read", "text": head + body}]
    for c in conflicts:
        meta = followup.BY_ID.get(c["slot"], {})
        msgs.append({"role": "assistant", "kind": "conflict", "slot": c["slot"],
                     "text": f"这上头写的是「{c['new']}」，可你先前跟我说的是「{c['old']}」——{meta.get('label', c['slot'])}到底哪个对？"})
    qs = followup.generate(s.text(), s.all_slots(), s.suspect, s.skipped, s.asked)
    msgs.extend(_turn(s, qs))
    s.messages.extend(msgs)
    return {**_state(s), "messages": msgs, "doc_type": doc_type,
            "new_suspect": {k: v["value"] for k, v in suspected.items()},
            "raw_fields": data.get("fields"), "ocr_engine": data.get("ocr_engine"),
            "ocr_warning": data.get("ocr_warning")}


@app.post("/api/session/{sid}/confirm")
def confirm(sid: str, body: ConfirmIn):
    s = store.get(sid)
    if not s:
        raise HTTPException(404, "session not found")
    if body.value is not None:
        v = body.value
        slot = body.slot
        if slot in ("start_date", "end_date", "last_claim_date"):
            v = extract.norm_date(v)
        elif slot in ("avg_wage", "unpaid_amount"):
            v = extract.norm_money(v)
        s.set_slot(slot, v, "image_confirmed", True)
        s.suspect.pop(slot, None)
    else:
        if body.slot not in s.suspect:
            raise HTTPException(422, "该槽位没有待确认的图片读数")
        s.confirm(body.slot)
    qs = followup.generate(s.text(), s.all_slots(), s.suspect, s.skipped, s.asked)
    return {**_state(s), "messages": [{"role": "assistant", "kind": "questions", "questions": qs}] if qs else []}


@app.post("/api/session/{sid}/asr")
async def asr_upload(sid: str, file: UploadFile = File(...)):
    s = store.get(sid)
    if not s:
        raise HTTPException(404, "session not found")
    raw = await file.read()
    if len(raw) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "音频过大（>12MB）")
    try:
        res = asr.transcribe(raw, suffix=".webm")
    except asr.ASRError as e:
        raise HTTPException(503, str(e))
    del raw
    return {"transcript": res["text"], "segments": res["segments"], "duration": res["duration"],
            "notice": "录音只用于本次转写，转写完成即从服务端删除。"}


@app.post("/api/session/{sid}/report")
def make_report(sid: str):
    s = store.get(sid)
    if not s:
        raise HTTPException(404, "session not found")
    if not s.slots.get("dispute_types", {}).get("value"):
        raise HTTPException(409, {
            "message": "我还没听明白你要解决的是哪件事——是欠薪、被辞退、没签合同，还是别的？先说一句我再给意见。",
            "missing": [{"slot": "dispute_types", "label": "争议类型"}],
        })
    meta = followup.BY_ID
    open_slots = followup.missing_slots(s.all_slots())
    open_questions = [{"slot": m, "label": meta[m]["label"]} for m in open_slots]
    rep = None
    last_err = None
    for attempt in range(2):
        try:
            rep = report.build_report(s, open_questions=open_questions)
            break
        except LLMError as e:
            last_err = e
            time.sleep(1.0 + attempt)
    if rep is None:
        raise HTTPException(503, {"message": "模型服务这会儿不稳定，稍等几秒再点一次", "retryable": True,
                                  "detail": str(last_err)[:100]})
    s.last_report = rep
    return rep


@app.post("/api/session/{sid}/rebuttal")
def rebuttal(sid: str):
    s = store.get(sid)
    if not s:
        raise HTTPException(404, "session not found")
    facts = json.dumps(s.confirmed_slots(), ensure_ascii=False)
    prompt = f"""你是公司方的 HR / 代理律师。基于以下劳动者确认的事实，列出公司最可能提出的 5 条抗辩，
每条给出：抗辩点、公司会拿什么证据、劳动者应当如何应对（需要什么材料/引用哪条法）。
只允许引用这些法条 ID：{", ".join(a['id'] for a in LAWS.articles[:5])} 以及
laodonghetongfa:39,40,46,47,82,87; tiaojiezhongcai:6,27; sfjs2:6,7,16。
事实：{facts}
输出 JSON：{{"items":[{{"attack":"...","evidence":"...","reply":"...","citations":["laodonghetongfa:39"]}}]}}"""
    try:
        data = chat_json([{"role": "user", "content": prompt}], max_tokens=1600)
    except LLMError as e:
        raise HTTPException(502, f"抗辩预演失败：{e}")
    items = []
    for it in data.get("items", [])[:5]:
        good, _bad = LAWS.by_ids(it.get("citations") or [])
        items.append({**it, "citations": [g["id"] for g in good],
                      "citation_titles": [f"{g['law']}{g['no_cn']}" for g in good]})
    return {"items": items}


class SettingsIn(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    text_model: str | None = None
    vision_model: str | None = None
    vision_enabled: bool | None = None
    local_ocr_fallback: bool | None = None
    timeout: float | None = None
    temperature: float | None = None
    mode: str | None = None
    manual_timeout: float | None = None


class ProbeIn(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


@app.get("/api/settings")
def get_settings():
    d = settings_store.public()
    d["ocr_local_available"] = __import__("app.ocr", fromlist=["available"]).available()
    return d


@app.post("/api/settings")
def save_settings(body: SettingsIn):
    patch = {k: v for k, v in body.dict().items() if v is not None}
    if patch.get("api_key") and "…" in patch["api_key"]:
        patch.pop("api_key")
    settings_store.save(patch)
    return settings_store.public()


@app.post("/api/settings/reset")
def reset_settings():
    settings_store.reset()
    return settings_store.public()


@app.post("/api/settings/test")
def test_settings(body: ProbeIn):
    cfg = settings_store.load()
    if cfg.get("mode") == "manual":
        return {"ok": True, "base_url": "manual", "model": "human-in-session",
                "reply": "会话内人工应答模式，不调用远端 API"}
    base = body.base_url or cfg["base_url"]
    key = body.api_key or cfg["api_key"]
    if key and "…" in key:
        key = cfg["api_key"]
    return probe(base, key, body.model or cfg["text_model"])


@app.get("/api/slots")
def slots_meta():
    return {"slots": SLOTS, "city": city_store.resolve({})["city"],
            "covered_cities": list(city_store.FILES)}


@app.get("/api/city")
def city_meta():
    return {**city_store.resolve({}), "covered_cities": list(city_store.FILES)}


@app.get("/api/laws")
def laws_index():
    return {"laws": [{"id": l["id"], "title": l["title"], "category": l["category"],
                      "effective": l["effective"], "promulgated": l["promulgated"],
                      "count": len(l["articles"]), "source": l["source"]}
                     for l in LAWS.laws.values()]}


@app.get("/api/laws/{law_id}")
def law_detail(law_id: str):
    law = LAWS.laws.get(law_id)
    if not law:
        raise HTTPException(404, "law not found")
    return law


@app.get("/api/law/{citation_id}")
def one_article(citation_id: str):
    a = LAWS.get(citation_id)
    if not a:
        raise HTTPException(404, "article not found")
    return {k: v for k, v in a.items() if k != "tokens"}


@app.get("/api/search")
def search(q: str, limit: int = 8):
    return {"results": LAWS.search(q, limit)}


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
