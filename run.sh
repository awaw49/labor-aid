#!/usr/bin/env bash
# 启动演示服务（默认 8787，手机同网段可访问）
set -e
cd "$(dirname "$0")"
IP=$(ipconfig getifaddr en0 2>/dev/null || echo 127.0.0.1)
echo "本机:  http://127.0.0.1:8787"
echo "手机:  http://$IP:8787"
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8787
