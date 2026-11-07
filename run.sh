#!/usr/bin/env bash
# 一键启动：venv 检查 + 端口检查 + uvicorn
set -e
cd "$(dirname "$0")"
[ -d .venv ] || { echo "缺 .venv——先: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"; exit 1; }
if lsof -ti :8787 >/dev/null 2>&1; then echo "8787 端口被占用——先停掉旧进程"; exit 1; fi
echo "启动: http://127.0.0.1:8787"
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8787
