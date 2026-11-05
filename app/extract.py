"""事实抽取：文字/语音转写 → 槽位；图片 → LLM 语义识读 → 疑似的字段（必须用户确认）。

没有任何关键词规则兜底：看图、读 OCR 文本、把内容映射到案情槽位全部由模型语义完成；
模型不可用就把错误如实报给用户，绝不退回写死的词表。
"""
from __future__ import annotations
import json
import re

from . import ocr
from . import settings as settings_store
from .llm import chat_json, chat_image, LLMError

SLOT_IDS = ["employer_name", "employer_city", "start_date", "end_date", "termination_by",
            "termination_reason", "contract_state", "avg_wage", "dispute_types",
            "prior_proceeding", "still_employed", "claims",
            "unpaid_amount", "overtime_hours", "unused_leave_days", "last_claim_date"]

ENUMS = {
    "termination_by": {"employer", "employee", "mutual", "unknown"},
    "contract_state": {"none", "one", "two_plus", "unknown"},
    "prior_proceeding": {"none", "arbitration_done", "court_done", "settled"},
    "still_employed": {"yes", "no", "unknown"},
}
MULTI = {"dispute_types", "claims"}

DATE_RE = re.compile(r"(\d{4})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})")
MONEY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(万|千|k|K)?")

UNREADABLE = ("看不清", "无法辨认", "无法识别", "不清晰", "未知", "未显示", "无", "null", "N/A", "略")


def norm_date(v):
    if not v:
        return None
    s = str(v).strip()
    m = DATE_RE.search(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})", s)
    if m:
        return None  # 缺年份不猜，交给追问
    return None


def norm_money(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("元", "").strip()
    m = MONEY_RE.search(s)
    if not m:
        return None
    n = float(m.group(1))
    unit = m.group(2)
    if unit in ("万",):
        n *= 10000
    elif unit in ("千", "k", "K"):
        n *= 1000
    return round(n, 2)


def resolve_year(iso: str, evidence: str, today=None) -> str:
    """用户/模型没写年份时，按"最近一次发生的该月日"补年份，而不是让模型猜。
    证据里出现四位年份就原样保留。"""
    from datetime import date as _date
    today = today or _date.today()
    if not iso or re.search(r"(19|20)\d{2}", evidence or ""):
        return iso
    try:
        y, m, d = [int(x) for x in iso.split("-")]
    except ValueError:
        return iso
    year = today.year if (m, d) <= (today.month, today.day) else today.year - 1
    return f"{year:04d}-{m:02d}-{d:02d}"


def _coerce(slot: str, value):
    if value is None:
        return None
    if slot in ("start_date", "end_date", "last_claim_date"):
        return norm_date(value)
    if slot in ("avg_wage", "unpaid_amount"):
        return norm_money(value)
    if slot in ENUMS:
        v = str(value).strip()
        return v if v in ENUMS[slot] else None
    if slot in MULTI:
        vals = value if isinstance(value, list) else [value]
        allowed = {
            "dispute_types": {"unpaid_wage", "termination", "no_contract", "overtime",
                              "annual_leave", "social_insurance", "noncompete", "other"},
            "claims": {"compensation_2n", "compensation_n", "double_wage", "wage",
                       "annual_leave_pay", "confirm_relation", "unsure"},
        }[slot]
        return [v for v in vals if v in allowed] or None
    return str(value).strip()


EXTRACT_SYSTEM = """你是劳动仲裁初步咨询系统的"事实抽取器"，不是法律意见生成器。
只做一件事：把用户口语里已经明确说出的事实，抽取成给定槽位。
硬规则：
1. 只抽取用户明确说出的信息；没说的不要猜、不要补全、不要根据常理推断。
2. 日期必须能确定年月日才填，只说了"3月"或"去年"就不要填。
3. 金额填"应发"工资；如果用户说的是实发/到手，也填入但在 evidence 里注明"实发"。
4. 枚举值必须从给定取值中选择，不确定就用 unknown 或不填。
5. 每条都要给 evidence：用户原话的连续片段（≤40 字）。
6. 用户前后矛盾时不要替他选，把两个说法都放进 conflicts。
7. summary 是你说给来访者听的话，不是报告摘要：大白话、短句，能提一句他自己的原话更好
   （"你说 3 月 15 号那天 HR 让你明天别来了，工资发到 2 月"），不列字段名、不用"您"、
   不写"根据您提供的信息"这类书面腔。
   他这次只补了一个数字或者一个日期，就一句话甚至半句（"八千六，行"）带过；
   一个字都没听出新东西，summary 留空，别硬复述；纯安抚/跑题回应不确认（确认由系统按是否有新事实自动决定）。
8. 来访者提到拉横幅、堵门、堵领导、武力讨薪、威胁网络曝光等过激做法时：summary 先接住他的气话，
   再温和劝一句（横幅堵门解决不了问题还容易把自己搭进去），把话头引回合法稳妥的渠道；不评判、不说教、不吓唬。

槽位与取值：
- employer_name: 公司全称（字符串）
- employer_city: 城市名全称（如 杭州市/北京市/上海市/广州市/深圳市；用户只说简称就写全称）
- start_date / end_date: YYYY-MM-DD
- termination_by: employer(单位提出) | employee(自己辞职) | mutual(协商一致) | unknown
- termination_reason: 单位给的理由原话（字符串）
- contract_state: none(一次没签) | one(签过1次) | two_plus(2次及以上) | unknown
- avg_wage: 数字（元/月）
- dispute_types: 数组，取自 [unpaid_wage, termination, no_contract, overtime, annual_leave, social_insurance, noncompete, other]
  只要叙述涉及被辞退、被开除、被迫离职、辞职后主张补偿，数组里必须有 termination；涉及没签书面合同必须有 no_contract；涉及欠发工资必须有 unpaid_wage
- prior_proceeding: none | arbitration_done | court_done | settled
- still_employed: yes | no | unknown
- claims: 数组，取自 [compensation_2n, compensation_n, double_wage, wage, annual_leave_pay, confirm_relation, unsure]
- unpaid_amount: 数字（元），用户说"欠我 X 元工资"时填
- unused_leave_days: 数字，用户说"X 天年假没休"时填
- overtime_hours: 数字，用户说"加班 X 小时"时填
- last_claim_date: YYYY-MM-DD，用户说"我某天催过/投诉过"时填

输出 JSON：
{"slots": {"槽位名": {"value": ..., "evidence": "原话"}},
 "conflicts": [{"slot": "...", "a": "...", "b": "..."}],
 "summary": "一两句大白话，把你听懂的事说回给来访者听（不含任何法律判断）",
 "followup": {"slot": "...", "text": "...", "why": "..."},
 "meta": {"signal": "none", "about_slot": ""}}
没有把握的槽位直接不要出现在 slots 里。

meta.signal 识别来访者这句话的"谈话信号"（不是案情事实）：
- unknown_answer：来访者对某个缺口表示"不知道/不清楚/记不清/没注意"（about_slot 填对应槽位，判断不了就空）
- refuse_details：来访者明确表示"不想说/不方便说/这是隐私/别问这个"（about_slot 同上）
- want_report：来访者想结束提问、直接要结论（"别问了""直接给我结论""就这样吧""没有了""就这些""没别的了"）
- none：正常叙述案情或回答问题
注意：来访者说"不知道"的同时若还说了别的事实，facts 照常抽取，signal 也照样给。"""


def extract_from_text(text: str, known: dict, missing: list[dict] | None = None) -> dict:
    known_brief = {k: v.get("value") for k, v in known.items() if v.get("confirmed")}
    from datetime import date
    from .followup import FOLLOWUP_RULES
    today = date.today().isoformat()
    messages = [
        {"role": "system", "content": EXTRACT_SYSTEM + FOLLOWUP_RULES
         + f"\n\n今天是 {today}。用户说\"今年\"按 {today[:4]} 年换算，说\"去年\"按 {int(today[:4])-1} 年换算；只说了月日没说年份的，不要猜，直接不填。"},
        {"role": "user", "content": f"已知（用户已确认）的槽位：{json.dumps(known_brief, ensure_ascii=False)}\n\n"
                                    f"【可问缺口】：{json.dumps(missing or [], ensure_ascii=False)}\n\n"
                                    f"用户这次说的话：\n{text}"},
    ]
    data = chat_json(messages, max_tokens=1400)
    out = {}
    for slot, item in (data.get("slots") or {}).items():
        if slot not in SLOT_IDS:
            continue
        val = _coerce(slot, item.get("value"))
        if val in (None, "", []):
            continue
        ev = (item.get("evidence") or "")[:80]
        if slot in ("start_date", "end_date", "last_claim_date"):
            val = resolve_year(val, ev)
        out[slot] = {"value": val, "evidence": ev, "source": "oral"}
    return {"slots": out, "conflicts": data.get("conflicts") or [],
            "summary": data.get("summary") or "",
            "followups": data.get("followup") or data.get("followups") or [],
            "meta": data.get("meta") or {}}


def _norm(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5]", "", str(s or "")).lower()


def _unreadable(v) -> bool:
    t = str(v).strip()
    if not t:
        return True
    return any(t == u or t.startswith(u) for u in UNREADABLE)


def _num_variants(v) -> list[str]:
    s = str(v)
    out = {s}
    if re.fullmatch(r"\d+(\.\d+)?", s):
        n = float(s)
        out.add(str(int(n)) if n == int(n) else f"{n:g}")
        if n == int(n):
            out.add(f"{int(n):,}")
    return [x for x in out if x]


def _grounded(t: str, ground: str) -> bool:
    """一段内容是否有 OCR 原文依据：整串匹配，或其中的日期/数字以原文字形出现。"""
    nt = _norm(t)
    if nt and nt in ground:
        return True
    for m in re.finditer(r"(\d{4})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})", t):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            for v in (f"{y}年{mo}月{d}日", f"{y}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}",
                      f"{y}/{mo}/{d}", f"{y}.{mo}.{d}"):
                if _norm(v) in ground:
                    return True
    for m in re.finditer(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d{4,}", t):
        for v in _num_variants(m.group(0)):
            nv = _norm(v)
            if nv and nv in ground:
                return True
    return False


IMAGE_SYSTEM = """你在读一张劳动争议相关材料的照片。先通读整份材料理解它在说什么，
再只提取你亲眼看到的内容；看不清就说看不清，禁止脑补。

doc_type 取值：
termination_notice（解除通知/辞退邮件/离职证明）、contract（劳动合同/录用通知）、payslip（工资条）、
bank_flow（银行流水）、chat（微信钉钉聊天截图）、attendance（考勤排班）、social_record（社保记录）、other

只输出这个 JSON，不要解释：
{
 "doc_type": "...",
 "readable": "清晰|部分可读|模糊",
 "employer": "用人单位名称，没有就空字符串",
 "dates": [{"text": "原文片段", "meaning": "入职|离职|解除|签署|发放|其他"}],
 "amounts": [{"text": "原文片段", "label": "应发合计|实发|基本工资|月工资|转账金额|其他", "value": 8600}],
 "reason": "解除理由的原话，没有就空字符串",
 "suspects": [{"slot": "...", "value": ..., "quote": "支撑该值的原文片段"}],
 "notes": "一句话：这份材料能证明什么、缺什么"
}

suspects 是你读懂整份材料后，映射到案情槽位的语义结果，slot 只能取：
- employer_name：用人单位全称（聊天里的联系人姓名不是用人单位）
- start_date：入职/到岗日期（工资条的"发放日期"、落款的"出具日期"都不是入职）
- end_date：解除/离职/最后工作日
- avg_wage：月应发工资（数字，元）。工资条看"应发合计"；录用通知看写明的月工资；
  银行流水中每月固定转入的工资额（自己判断哪笔是固定工资，不要把零散转账加总）；
  材料上定不出月工资就不要输出这一项
- termination_reason：单位给的解除理由原话（仅解除通知或聊天记录里有）

硬规则：
1. suspects 每项的 quote 必须是材料上连续出现的原文片段（≤40 字），没有原文依据就不要输出该项。
2. value：日期写成 YYYY-MM-DD，材料只有月日没写年就写成 "MM-DD"；金额写纯数字，不要计算、不要合计推断。
3. 发放日期属于"发放"，不能当作入职或离职日期。
4. 不给任何法律结论。"""

OCR_STRUCT_SYSTEM = """下面是一张劳动争议相关材料经本机 OCR 得到的逐行文本（可能有错字）。
先通读理解这份材料是什么、在说什么，再做结构化。

只输出这个 JSON，不要解释：
{
 "doc_type": "termination_notice|contract|payslip|bank_flow|chat|attendance|social_record|other",
 "readable": "清晰|部分可读|模糊",
 "employer": "用人单位名称，没有就空字符串",
 "dates": [{"text": "OCR 原文片段", "meaning": "入职|离职|解除|签署|发放|其他"}],
 "amounts": [{"text": "OCR 原文片段", "label": "应发合计|实发|基本工资|月工资|转账金额|其他", "value": 8600}],
 "reason": "解除理由的原话，没有就空字符串",
 "suspects": [{"slot": "...", "value": ..., "quote": "支撑该值的 OCR 原文片段"}],
 "notes": "一句话：这份材料能证明什么、缺什么"
}

suspects 是你读懂材料后映射到案情槽位的语义结果，slot 只能取：
employer_name（用人单位全称，"王经理""张三"这类人名不是）、start_date（入职日期）、
end_date（解除/离职日期）、avg_wage（月应发工资：工资条看"应发合计"，流水看每月固定转入额，定不出就不填）、
termination_reason（单位给的解除理由，仅解除通知或聊天记录里有）。

硬规则：
1. suspects 每项 quote 必须是 OCR 文本里连续出现的片段（可跨换行，≤40 字），没有依据就不要输出。
2. value：日期尽量 YYYY-MM-DD，只有月日没年就写 "MM-DD"；金额是纯数字，不要计算、不要推断。
3. 发放日期属于"发放"，不能当入职/离职日期。
4. 不给任何法律结论。"""


def _parse_json(raw: str) -> dict:
    text = raw.strip()
    m = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    i, j = text.find("{"), text.rfind("}")
    if i >= 0 and j > i:
        text = text[i:j + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"识图未返回合法 JSON：{raw[:300]}") from e


def verify_structured(data: dict, ocr_text: str) -> tuple[dict, list[str]]:
    """用本机 OCR 原文核对每一项引用；对不上的一律丢弃（防幻觉，不是关键词规则）。"""
    dropped: list[str] = []
    if not ocr_text.strip():
        return data, dropped
    ground = _norm(ocr_text)
    emp = data.get("employer") or ""
    if emp and _norm(emp) not in ground:
        data["employer"] = ""
        dropped.append("employer")
    keep_dates = []
    for x in data.get("dates") or []:
        if _grounded(x.get("text") or "", ground):
            keep_dates.append(x)
        else:
            dropped.append(f"dates.{x.get('meaning')}")
    data["dates"] = keep_dates
    keep_amts = []
    for x in data.get("amounts") or []:
        t = x.get("text") or ""
        ok_val = x.get("value") is not None and _grounded(str(x.get("value")), ground)
        if _grounded(t, ground) or ok_val:
            keep_amts.append(x)
        else:
            dropped.append(f"amounts.{x.get('label')}")
    data["amounts"] = keep_amts
    if data.get("reason"):
        r = _norm(data["reason"])[:12]
        if r and r not in ground:
            data["reason"] = ""
            dropped.append("reason")
    keep_sus = []
    for s in data.get("suspects") or []:
        q = _norm(s.get("quote") or "")
        v = str(s.get("value") if s.get("value") is not None else "")
        if (q and q in ground) or _grounded(v, ground):
            keep_sus.append(s)
        else:
            dropped.append(f"suspects.{s.get('slot')}")
    data["suspects"] = keep_sus
    return data, dropped


def extract_from_image(image_b64: str, mime: str, image_bytes: bytes | None = None) -> dict:
    """识图全程走 LLM：开视觉就模型直接看图，没开就本机 OCR 出文字后交给文本模型语义结构化。
    模型不可用就抛错给用户，不做关键词规则兜底。"""
    import base64
    cfg = settings_store.load()
    raw_bytes = image_bytes or base64.b64decode(image_b64)

    ocr_text, ocr_err = "", None
    if ocr.available():
        try:
            ocr_text = ocr.recognize(raw_bytes)["text"]
        except ocr.OCRError as e:
            ocr_err = str(e)

    if cfg.get("vision_enabled") and cfg.get("vision_model"):
        prompt = IMAGE_SYSTEM
        if ocr_text:
            prompt += "\n\n同一张图的本机 OCR 文本（可用来核对原文，可能有错字）：\n" + ocr_text[:3000]
        data = _parse_json(chat_image(prompt, image_b64, mime, max_tokens=1000))
        data, dropped = verify_structured(data, ocr_text)
        data["ocr_engine"] = "视觉模型" + ("（本机 OCR 已核对原文）" if ocr_text else "")
        data["quote_dropped"] = dropped
        if dropped:
            data["ocr_warning"] = "无原文依据已丢弃：" + "、".join(dropped[:8])
        return data

    if not cfg.get("local_ocr_fallback"):
        raise LLMError("视觉模型未开启，且本机 OCR 兜底未开启（可在设置里打开）")
    if not ocr_text.strip():
        return {"doc_type": "other", "readable": "模糊", "employer": "", "dates": [], "amounts": [],
                "suspects": [], "reason": "", "notes": "", "recognized": False,
                "ocr_engine": "macOS Vision", "ocr_error": ocr_err or "没有识别到文字",
                "ocr_warning": "本机 OCR 没有读出文字，视觉模型又未开启，无法识读这份材料"}
    data = chat_json([
        {"role": "system", "content": OCR_STRUCT_SYSTEM},
        {"role": "user", "content": "OCR 文本：\n" + ocr_text[:4000]},
    ], max_tokens=1000)
    data, dropped = verify_structured(data, ocr_text)
    data["ocr_engine"] = "本机 OCR（macOS Vision，离线）+ 文本模型语义结构化"
    data["quote_dropped"] = dropped
    if dropped:
        data["ocr_warning"] = "无原文依据已丢弃：" + "、".join(dropped[:8])
    return data


DOC_TO_MATERIAL = {
    "termination_notice": "termination_notice",
    "contract": "contract",
    "payslip": "payslip",
    "bank_flow": "bank_flow",
    "chat": "chat_record",
    "attendance": "attendance",
    "social_record": "social_record",
    "other": "wage_claim_log",
}

IMAGE_SUSPECT_SLOTS = {"employer_name", "start_date", "end_date", "avg_wage", "termination_reason"}


def image_to_suspected(data: dict, today_year: int | None = None) -> dict:
    """LLM 的语义 suspects → 疑似槽位（全部未确认，等用户点头）。
    这里只做格式归一（日期/金额），不再做任何内容判断。"""
    from datetime import date
    year = today_year or date.today().year
    suspected: dict = {}
    for s in data.get("suspects") or []:
        slot = str(s.get("slot") or "").strip()
        if slot not in IMAGE_SUSPECT_SLOTS or slot in suspected:
            continue
        quote = str(s.get("quote") or "")[:60]
        raw = str(s.get("value") if s.get("value") is not None else "").strip()
        if slot in ("start_date", "end_date"):
            v = norm_date(raw)
            if not v:
                m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})", raw)
                if not (m and 1 <= int(m.group(1)) <= 12 and 1 <= int(m.group(2)) <= 31):
                    continue
                v, missing_year = f"{year:04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}", True
            else:
                missing_year = not re.search(r"\d{4}", raw)
            suspected[slot] = {"value": v, "quote": quote, "source": "image",
                               "doc_type": data.get("doc_type"), "needs_year": missing_year, "raw": raw}
        elif slot == "avg_wage":
            v = norm_money(raw)
            if not v or v <= 0:
                continue
            suspected[slot] = {"value": v, "quote": quote, "source": "image",
                               "doc_type": data.get("doc_type"), "needs_year": False, "raw": raw}
        else:
            if not raw or _unreadable(raw):
                continue
            suspected[slot] = {"value": raw[:120], "quote": quote or raw[:60], "source": "image",
                               "doc_type": data.get("doc_type"), "needs_year": False, "raw": raw}
    return suspected
