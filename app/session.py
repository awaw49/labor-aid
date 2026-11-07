"""会话状态：只在内存；图片与音频处理完即丢弃，不落盘、不进 RAG。"""
from __future__ import annotations

import secrets
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Session:
    id: str
    created: float = field(default_factory=time.time)
    slots: dict = field(default_factory=dict)          # slot -> {value, source, confirmed, evidence, quote}
    suspect: dict = field(default_factory=dict)        # slot -> 未确认的图片读数
    conflicts: list = field(default_factory=list)
    materials: list = field(default_factory=list)      # 只存材料类型与确认状态，不存图片本身
    messages: list = field(default_factory=list)
    story: list = field(default_factory=list)          # 用户口述/转写文本，供语义理解层使用
    needs: dict | None = None                          # 语义理解结果（枚举+证据），随输入指纹缓存
    needs_fp: str | None = None
    asked: dict = field(default_factory=dict)          # slot -> 已问过的次数（每槽最多问 2 次）
    skipped: set = field(default_factory=set)          # 用户明确"不知道/不想说"的槽位，不再追问
    wrap_up: bool = False                              # 用户要求结束追问、直接看结论
    offered: bool = False                              # 律师已主动给出书面意见
    last_report: dict | None = None

    def set_slot(self, slot: str, value, source: str, confirmed: bool, evidence: str = "", quote: str = ""):
        self.slots[slot] = {"value": value, "source": source, "confirmed": confirmed,
                            "evidence": evidence, "quote": quote,
                            "at": time.strftime("%Y-%m-%d %H:%M:%S")}

    def confirm(self, slot: str, value=None):
        item = self.suspect.get(slot) or self.slots.get(slot)
        if not item:
            return None
        v = value if value is not None else item["value"]
        self.set_slot(slot, v, "image_confirmed" if slot in self.suspect else item.get("source", "user"),
                      True, item.get("quote", ""), item.get("quote", ""))
        self.suspect.pop(slot, None)
        return v

    def confirmed_slots(self) -> dict:
        return {k: v["value"] for k, v in self.slots.items() if v.get("confirmed")}

    def all_slots(self) -> dict:
        return {k: v["value"] for k, v in self.slots.items()}

    def text(self) -> str:
        # 语义层只看最近 40 条口述，防超长会话把 prompt 撑爆
        return "\n".join(self.story[-40:])

    def say(self, kind: str, text: str, **extra) -> dict:
        """带时间戳的消息（前端 title 悬停可见）。"""
        m = {"role": "assistant", "kind": kind, "text": text, "at": time.strftime("%H:%M:%S"), **extra}
        self.messages.append(m)
        return m

    def add_material(self, material_type: str, meta: dict | None = None):
        for m in self.materials:
            if m["type"] == material_type:
                m["count"] = m.get("count", 1) + 1
                m.update(meta or {})
                return
        self.materials.append({"type": material_type, "confirmed": True,
                               "original": True, "count": 1, **(meta or {})})


SESSIONS: dict[str, Session] = {}
MAX_SESSIONS = 200          # 内存保护：超出后按最早创建时间淘汰


def _evict_expired(max_age_s: int = 24 * 3600):
    now = time.time()
    for sid in [sid for sid, s in SESSIONS.items() if now - s.created > max_age_s]:
        SESSIONS.pop(sid, None)


def create() -> Session:
    _evict_expired()
    while len(SESSIONS) >= MAX_SESSIONS:
        oldest = min(SESSIONS.values(), key=lambda s: s.created)
        SESSIONS.pop(oldest.id, None)
    s = Session(id=secrets.token_hex(6))
    SESSIONS[s.id] = s
    return s


def get(sid: str) -> Session | None:
    return SESSIONS.get(sid)
