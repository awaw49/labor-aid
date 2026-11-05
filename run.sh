#!/usr/bin/env bash
# 启动演示服务（默认 8787，手机同网段可访问）
set -e
cd "$(dirname "$0")"

PORT="${PORT:-8787}"
PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"

# macOS 与 Linux 取局域网 IP 的方式不同
if command -v ipconfig >/dev/null 2>&1; then
  IP=$(ipconfig getifaddr en0 2>/dev/null || echo 127.0.0.1)
else
  IP=$(hostname -I 2>/dev/null | awk '{print $1}')
  [ -n "$IP" ] || IP=127.0.0.1
fi

echo "本机:    http://127.0.0.1:$PORT"
echo "局域网:  http://$IP:$PORT"
echo "接口文档: http://127.0.0.1:$PORT/docs"

exec "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
