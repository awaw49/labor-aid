"""运行时可配置的模型 API 设置（存 data/settings.json，网页里可改）。"""
from __future__ import annotations

import json
import os
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "settings.json")

# 可选：支持仓库根目录的 .env（复制 .env.example 即可），没装 python-dotenv 也能跑
try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - 未安装可选依赖时走这里
    load_dotenv = None
if load_dotenv is not None:
    load_dotenv(os.path.join(ROOT, ".env"))

DEFAULTS = {
    # 默认留空：不预设任何第三方中转地址，避免把个人使用的中转站当成项目默认值。
    # 首次启动请在页面右上角「设置」里填写你自己的 OpenAI 兼容地址（形如 https://host/v1）。
    "base_url": "",
    # 密钥不进代码：优先读环境变量 LABOR_AID_API_KEY，或在网页「设置」里粘贴
    # （粘贴后存 data/settings.json，该文件已列入 .gitignore，不入库）
    "api_key": "",
    "text_model": "deepseek-flash",
    "vision_model": "deepseek-v4.1-flash",
    "vision_enabled": True,
    "local_ocr_fallback": True,
    "timeout": 120,
    "temperature": 0.1,
    "mode": "api",           # api = 调远端模型；manual = 会话内人工应答（演示用）
    "manual_timeout": 600,
}

_lock = threading.Lock()
_cache: dict | None = None


def load() -> dict:
    global _cache
    with _lock:
        if _cache is None:
            data = dict(DEFAULTS)
            if os.path.exists(PATH):
                try:
                    with open(PATH, encoding="utf-8") as f:
                        data.update(json.load(f))
                except json.JSONDecodeError:
                    pass
            # 密钥优先级：页面设置（data/settings.json）> 环境变量 > 空
            if not data.get("api_key"):
                data["api_key"] = os.environ.get("LABOR_AID_API_KEY", "")
            _cache = data
        return dict(_cache)


def save(patch: dict) -> dict:
    global _cache
    with _lock:
        data = dict(_cache or DEFAULTS)
        for k in DEFAULTS:
            if k in patch and patch[k] not in (None, ""):
                data[k] = patch[k]
        data["timeout"] = float(data["timeout"])
        data["temperature"] = float(data["temperature"])
        data["vision_enabled"] = bool(data["vision_enabled"])
        data["local_ocr_fallback"] = bool(data["local_ocr_fallback"])
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        with open(PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        _cache = data
        return dict(data)


def reset() -> dict:
    global _cache
    with _lock:
        if os.path.exists(PATH):
            os.remove(PATH)
        _cache = dict(DEFAULTS)
        return dict(_cache)


def public() -> dict:
    d = load()
    key = d["api_key"]
    masked = key[:6] + "…" + key[-4:] if len(key) > 12 else "…"
    return {**d, "api_key": masked, "api_key_set": bool(key)}
