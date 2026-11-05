"""城市口径注册表：目前覆盖五城，口径文件在 data/city/<id>.json（每份都带 verified_at 与来源注记）。

resolve() 负责把会话里已确认的 employer_city 接到对应口径上：
- 覆盖城市 → 对应口径文件
- 未确认 / 未覆盖城市 → 杭州口径仅作展示兜底，闸门（gates.py）会明确提示覆盖范围并指路，不冒用金额。
"""
from __future__ import annotations
import json
import os

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "city")

FILES = {
    "北京市": "beijing.json",
    "上海市": "shanghai.json",
    "广州市": "guangzhou.json",
    "深圳市": "shenzhen.json",
    "杭州市": "hangzhou.json",
}

# 用户手打简称 → 全称（与 slots.json 的 chips 值保持同源）
ALIASES = {
    "北京": "北京市", "上海": "上海市", "广州": "广州市",
    "深圳": "深圳市", "杭州": "杭州市",
}

_cache: dict[str, dict] = {}


def _load(name: str) -> dict:
    if name not in _cache:
        path = os.path.join(DATA, FILES[name])
        _cache[name] = json.load(open(path, encoding="utf-8"))
    return _cache[name]


def normalize(value: str | None) -> str:
    v = str(value or "").strip()
    return ALIASES.get(v, v)


def resolve(slots: dict) -> dict:
    name = normalize(slots.get("employer_city"))
    return _load(name) if name in FILES else _load("杭州市")


def covered(slots: dict) -> bool:
    return normalize(slots.get("employer_city")) in FILES
