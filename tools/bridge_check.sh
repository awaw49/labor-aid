#!/usr/bin/env bash
# 桥路探针：发一个最小 req，等应答方写 resp（30s 超时）——验证 manual 模式应答链路。
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)/data/manual_llm"
RID="probe-$(date +%s)"
REQ="$DIR/req_$RID.json"
RESP="$DIR/resp_$RID.txt"
rm -f "$RESP"
cat > "$REQ" <<'EOF'
{"model":"probe","max_tokens":8,"json_mode":false,"messages":[{"role":"user","content":"回复OK两个字"}]}
EOF
echo "已投放 $REQ，等待应答…"
for i in $(seq 1 30); do
  if [ -f "$RESP" ]; then
    echo "✓ 应答方在线（${i} 秒内应答）：$(cat "$RESP" | head -c 40)"
    rm -f "$REQ" "$RESP"
    exit 0
  fi
  sleep 1
done
echo "✗ 30 秒无应答——manual 模式应答方不在线"
rm -f "$REQ"
exit 1
