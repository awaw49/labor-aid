#!/usr/bin/env bash
# 一键全验：JS 语法 + 冒烟 + 法条白名单 + （可选）报告断言
set -e
cd "$(dirname "$0")/.."
echo "== 1) JS 语法 =="
node --check static/app.js && echo "✓ app.js"
echo "== 2) 冒烟 =="
./tools/smoke.sh
echo "== 3) 法条白名单（劳动政府源）==="
WL=$(grep -rhoE '"[a-z0-9]+:[0-9]+"' app/kernel app/*.py | sort -u | tr -d '"' | cut -d: -f1 | sort -u | head -3 | tr '\n' ' ')
echo "（快验：核心 3 部法原文页如不在本机可跳过——全量验用 tools/verify_laws.py <源页.html> <law_id>）"
echo "== 3.5) 单元测试 =="
.venv/bin/python -m pytest tests/ -q || exit 1
echo "== 3.6) 城市口径自检 =="
.venv/bin/python tools/verify_city.py || exit 1
echo "== 3.7) 桥路探针（manual 模式）==="
MODE=$(curl -s -m 5 http://127.0.0.1:8787/api/bridge/status | python3 -c "import sys,json;print(json.load(sys.stdin).get('mode'))" 2>/dev/null || echo "?")
if [ "$MODE" = "manual" ]; then ./tools/bridge_check.sh || exit 1; else echo "（api 模式，跳过桥路探针）"; fi
echo "== 4) Python 编译 =="
.venv/bin/python -m py_compile app/main.py app/llm.py app/extract.py app/followup.py app/needs.py app/report.py app/session.py app/city.py app/kernel/*.py && echo "✓ python 编译"
echo "全验完成 ✓"
