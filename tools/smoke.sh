#!/usr/bin/env bash
# 一键冒烟：健康检查 / 会话创建 / 法条库 / 城市口径 / 静态资源 / 搜索
set -e
BASE="${1:-http://127.0.0.1:8787}"
pass=0; fail=0
check() { # 名称 期望片段 实际
  if echo "$3" | grep -q "$2"; then echo "✓ $1"; pass=$((pass+1));
  else echo "✗ $1（缺「$2」）"; fail=$((fail+1)); fi
}

H=$(curl -s -m 5 "$BASE/api/health")
check "健康检查" '"ok":true' "$H"

S=$(curl -s -m 5 -X POST "$BASE/api/session")
check "会话创建" 'session_id' "$S"
SID=$(echo "$S" | python3 -c "import sys,json;print(json.load(sys.stdin)['session_id'])" 2>/dev/null || true)

L=$(curl -s -m 5 "$BASE/api/laws")
check "法条库索引" 'laodonghetongfa' "$L"

C=$(curl -s -m 5 "$BASE/api/city")
check "城市口径" 'covered_cities' "$C"

for f in / /index.html /styles.css /app.js /manifest.webmanifest; do
  code=$(curl -s -o /dev/null -w "%{http_code}" -m 5 "$BASE$f")
  check "静态 $f" '200' "$code"
done

if [ -n "$SID" ]; then
  SL=$(curl -s -m 5 "$BASE/api/slots")
  check "槽位元数据" 'employer_city' "$SL"
fi

B=$(curl -s -m 5 "$BASE/api/bridge/status")
check "桥路状态端点" 'pending' "$B"

echo "----"
echo "冒烟结果: $pass 通过 / $fail 失败"
[ "$fail" -eq 0 ]
