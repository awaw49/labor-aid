"""LLM 接入（OpenAI 兼容），参数在运行时从 data/settings.json 读取，网页里可改。

mode = "api"：调远端模型。
mode = "manual"：会话内人工应答——把完整请求写到 data/manual_llm/req_*.json，
等外部（演示时由人在会话里）写回 resp_*.txt，用于无 API 时检验语义理解效果。
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import uuid
from pathlib import Path

import httpx

from . import settings as settings_store


class LLMError(RuntimeError):
    pass


def _strip_json(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    i, j = text.find("{"), text.rfind("}")
    if i >= 0 and j > i:
        text = text[i:j + 1]
    return text


def _manual_exchange(messages: list[dict], *, model: str, max_tokens: int, json_mode: bool) -> str:
    root = Path(settings_store.ROOT) / "data" / "manual_llm"
    root.mkdir(parents=True, exist_ok=True)
    import glob as _g
    backlog = len(_g.glob(str(root / "req_*.json")))
    if backlog >= 5:
        raise LLMError(f"桥路积压 {backlog} 条——应答方不在线，先恢复应答方")
    rid = time.strftime("%H%M%S") + "-" + uuid.uuid4().hex[:4]
    clean, imgs = [], []
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            parts = []
            for p in content:
                if isinstance(p, dict) and p.get("type") == "image_url":
                    url = p["image_url"]["url"]
                    head, _, b64 = url.partition(",")
                    ext = "png" if "png" in head else "jpg"
                    ipath = root / f"img_{rid}_{len(imgs)}.{ext}"
                    ipath.write_bytes(base64.b64decode(b64))
                    imgs.append(ipath)
                    parts.append({"type": "image_file", "path": str(ipath)})
                else:
                    parts.append(p)
            clean.append({**m, "content": parts})
        else:
            clean.append(m)
    req = root / f"req_{rid}.json"
    req.write_text(json.dumps({"model": model, "max_tokens": max_tokens,
                               "json_mode": json_mode, "messages": clean},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        os.chmod(req, 0o600)          # 桥路文件含案情，仅本用户可读
    except OSError:
        pass
    resp = root / f"resp_{rid}.txt"
    limit = float(settings_store.load().get("manual_timeout", 600))
    deadline = time.time() + limit
    while time.time() < deadline:
        if resp.exists():
            out = resp.read_text(encoding="utf-8-sig").strip()   # utf-8-sig 顺带吃掉 BOM
            for p in imgs:
                p.unlink(missing_ok=True)      # 隐私：图片看完即删，不落盘
            req.unlink(missing_ok=True)        # 桥路用完即清，不留陈旧请求
            resp.unlink(missing_ok=True)
            return out
        time.sleep(0.5)
    raise LLMError(f"会话内人工应答超时（等 resp_{rid}.txt 超过 {limit:.0f} 秒）")


def chat(messages: list[dict], *, model: str | None = None, max_tokens: int = 1600,
         temperature: float | None = None, json_mode: bool = False,
         retried_empty: bool = False) -> str:
    cfg = settings_store.load()
    use_model = model or cfg["text_model"]
    if cfg.get("mode") == "manual":
        return _manual_exchange(messages, model=use_model, max_tokens=max_tokens, json_mode=json_mode)
    body = {
        "model": use_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": cfg["temperature"] if temperature is None else temperature,
        "thinking": {"type": "disabled"},
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    base_url = (cfg.get("base_url") or "").strip()
    if not base_url:
        raise LLMError("尚未配置模型服务地址：请在页面右上角「设置」里填写 base_url"
                       "（OpenAI 兼容的 /v1 地址），或改用 mode=manual 演示。")
    url = base_url.rstrip("/") + "/chat/completions"
    r = None
    last = None
    for attempt in range(4):
        try:
            with httpx.Client(timeout=cfg.get("timeout", 120)) as c:
                r = c.post(url, headers={"Authorization": f"Bearer {cfg['api_key']}",
                                         "Content-Type": "application/json"}, json=body)
            if r.status_code in (429, 500, 502, 503):
                last = r
                time.sleep(1.5 * (attempt + 1))
                continue
            break
        except httpx.HTTPError as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    if r is None:
        raise LLMError(f"网络请求失败（{type(last).__name__}）：{str(last)[:160]}")
    if r.status_code in (429, 500, 502, 503):
        raise LLMError(_err(r))
    if r.status_code != 200:
        raise LLMError(_err(r))
    data = r.json()
    try:
        msg = data["choices"][0]["message"]
    except (KeyError, IndexError) as e:
        raise LLMError(f"返回格式异常：{str(data)[:200]}") from e
    content = (msg.get("content") or "").strip()
    if not content and not retried_empty:
        # 偶发的空正文（截断/上游抖动）自动再要一次，用户无感
        return chat(messages, model=model, max_tokens=max_tokens, temperature=temperature,
                    json_mode=json_mode, _retried_empty=True)
    if not content:
        rc = (msg.get("reasoning_content") or "").strip()
        if rc:
            raise LLMError("模型只输出了思考过程、没有正文（可换更快的模型或调大 max_tokens）")
        raise LLMError(f"返回空内容：{str(data)[:200]}")
    return content


def _err(r) -> str:
    try:
        d = r.json()
        e = d.get("error")
        if isinstance(e, dict):
            return f"HTTP {r.status_code}：{e.get('message') or e.get('code')}"
        if e:
            return f"HTTP {r.status_code}：{e}"
        return f"HTTP {r.status_code}：{str(d)[:200]}"
    except Exception:
        return f"HTTP {r.status_code}：{r.text[:200]}"


def chat_json(messages: list[dict], *, max_tokens: int = 1600, temperature: float = 0.1) -> dict:
    raw = chat(messages, max_tokens=max_tokens, temperature=temperature, json_mode=True)
    try:
        return json.loads(_strip_json(raw))
    except json.JSONDecodeError:
        repaired = chat([
            {"role": "system", "content": "你是 JSON 修复器。把用户给的内容整理成严格 JSON，只输出 JSON 本身，不要解释、不要 Markdown。"},
            {"role": "user", "content": raw[:6000]},
        ], max_tokens=max_tokens, temperature=0, json_mode=True)
        try:
            return json.loads(_strip_json(repaired))
        except json.JSONDecodeError as e:
            raise LLMError(f"模型未返回合法 JSON：{raw[:200]}") from e


def chat_image(prompt: str, image_b64: str, mime: str, *, max_tokens: int = 1400) -> str:
    cfg = settings_store.load()
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
    ]
    return chat([{"role": "user", "content": content}],
                model=cfg["vision_model"] or cfg["text_model"], max_tokens=max_tokens)


def probe(base_url: str, api_key: str, model: str) -> dict:
    """测试连接：列模型 + 发一条最小请求。"""
    base = base_url.rstrip("/")
    out = {"base_url": base, "model": model}
    try:
        with httpx.Client(timeout=30) as c:
            r = c.get(base + "/models", headers={"Authorization": f"Bearer {api_key}"})
        out["models_status"] = r.status_code
        if r.status_code == 200:
            ids = [m.get("id") for m in (r.json().get("data") or [])]
            out["models"] = ids
    except httpx.HTTPError as e:
        out["models_error"] = str(e)
    try:
        with httpx.Client(timeout=60) as c:
            r = c.post(base + "/chat/completions",
                       headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                       json={"model": model, "messages": [{"role": "user", "content": "只回复两个字：可用"}],
                             "max_tokens": 16, "thinking": {"type": "disabled"}})
        out["chat_status"] = r.status_code
        if r.status_code == 200:
            out["reply"] = (r.json()["choices"][0]["message"].get("content") or "").strip()[:40]
        else:
            out["chat_error"] = _err(r)
    except httpx.HTTPError as e:
        out["chat_error"] = str(e)
    out["ok"] = out.get("chat_status") == 200 and bool(out.get("reply"))
    return out
