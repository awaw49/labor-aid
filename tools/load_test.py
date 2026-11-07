#!/usr/bin/env python3
"""轻量并发压测：20 个并发会话创建 + 健康检查，验证内存态会话管理不崩。"""
import concurrent.futures
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8787"

def one(i):
    req = urllib.request.Request(BASE + "/api/session", method="POST", data=b"{}",
                                 headers={"Content-Type": "application/json"})
    sid = json.load(urllib.request.urlopen(req, timeout=30))["session_id"]
    h = json.load(urllib.request.urlopen(BASE + "/api/health", timeout=30))
    return sid and h.get("ok")

with concurrent.futures.ThreadPoolExecutor(20) as ex:
    ok = sum(ex.map(one, range(20)))
print(f"{ok}/20 并发会话成功")
sys.exit(0 if ok == 20 else 1)
