"""本机 OCR（macOS Vision 框架，离线、不联网、不落盘）。当配置的模型不支持图片时作为兜底。"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "tools", "ocr", "vision_ocr")


class OCRError(RuntimeError):
    pass


def available() -> bool:
    return os.path.exists(BIN) and os.access(BIN, os.X_OK)


def recognize(image_bytes: bytes) -> dict:
    if not available():
        raise OCRError("本机 OCR 不可用（缺少 tools/ocr/vision_ocr）")
    fd, path = tempfile.mkstemp(suffix=".png")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(image_bytes)
        p = subprocess.run([BIN, path], capture_output=True, text=True, timeout=60)
        if p.returncode != 0:
            raise OCRError(p.stdout[:200] or p.stderr[:200])
        data = json.loads(p.stdout)
        if data.get("error"):
            raise OCRError(data["error"])
        lines = [l for l in data.get("lines", []) if l.get("text", "").strip()]
        # Vision 的 y 轴自下而上，按版面从上到下排序
        lines.sort(key=lambda l: (-l.get("y", 0), l.get("x", 0)))
        return {"lines": lines, "text": "\n".join(l["text"] for l in lines)}
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
