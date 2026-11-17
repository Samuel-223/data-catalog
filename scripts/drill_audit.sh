#!/usr/bin/env bash
# 审计演练：一次跑完"留痕 / 不留痕"的典型场景，输出对照表。
#
# 用法：
#   ./scripts/drill_audit.sh                          # 默认 http://127.0.0.1:8000 + ./audit.jsonl
#   ./scripts/drill_audit.sh -b http://127.0.0.1:8000 -f ./audit_drill.jsonl
#   DRILL_ADMIN_KEY=... DRILL_EDITOR_KEY=... DRILL_VIEWER_KEY=... ./scripts/drill_audit.sh
#
# 前提：服务已启动，AUTH_MODE=apikey（或 both），且三把不同角色的 key 可用。
set -uo pipefail

BASE="http://127.0.0.1:8000"
FILE="${AUDIT_LOG_PATH:-./audit.jsonl}"

while getopts "b:f:h" opt; do
  case "$opt" in
    b) BASE="$OPTARG" ;;
    f) FILE="$OPTARG" ;;
    h) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "未知参数 -$OPTARG（-h 看用法）" >&2; exit 2 ;;
  esac
done

ADMIN_KEY="${DRILL_ADMIN_KEY:-sk_admin_local_00000000}"
EDITOR_KEY="${DRILL_EDITOR_KEY:-sk_editor_local_1111111}"
VIEWER_KEY="${DRILL_VIEWER_KEY:-sk_viewer_local_222222}"

PASS=0
FAIL=0

note_fail() { FAIL=$((FAIL + 1)); }

lines() {
  if [ -f "$FILE" ]; then wc -l < "$FILE"; else echo 0; fi
}

# probe 标签 期望状态码 curl 参数...
probe() {
  local label="$1" expect="$2"
  shift 2
  local before after code mark delta
  before=$(lines)
  code=$(curl -s -o /dev/null -w '%{http_code}' "$@")
  sleep 0.2
  after=$(lines)
  delta=$((after - before))
  if [ "$delta" -gt 0 ]; then mark="留痕(+$delta)"; else mark="不留痕"; fi
  if [ "$code" = "$expect" ]; then PASS=$((PASS + 1)); else note_fail; mark="$mark  ✗期望$expect"; fi
  printf '  %-44s %s  %s\n' "$label" "$code" "$mark"
}

echo "======================================================"
echo " 审计演练"
echo "  服务：$BASE"
echo "  审计：$FILE"
echo "======================================================"

if [ ! -f "$FILE" ]; then
  echo "提示：$FILE 还不存在，说明此前没有需要留痕的请求（文件在首次留痕时自动创建）"
fi

echo
echo "[0] 连通性"
probe "GET /health（匿名，探针）" 200 "$BASE/health"
probe "GET /ready（匿名，探针）" 200 "$BASE/ready"

echo
echo "[1] 只读成功 —— 不该留痕（避免审计被查询刷满）"
probe "GET /datasources（viewer）" 200 -H "X-API-Key: $VIEWER_KEY" "$BASE/datasources"
probe "GET /datasources（editor）" 200 -H "X-API-Key: $EDITOR_KEY" "$BASE/datasources"
probe "GET /audit（admin）" 200 -H "X-API-Key: $ADMIN_KEY" "$BASE/audit?limit=1"

echo
echo "[2] 鉴权失败 —— 读也要留痕（这是攻击面）"
probe "GET /datasources（无密钥）" 401 "$BASE/datasources"
probe "GET /datasources（假密钥）" 401 -H "X-API-Key: sk_fake_000000000000" "$BASE/datasources"
probe "GET /datasources（密钥不存在）" 401 \
  -H "X-API-Key: dc_viewer_deadbeef_000000000000000000000000000000000000000000000000" \
  "$BASE/datasources"

echo
echo "[3] 越权写入 —— 必须留痕"
probe "POST /datasources（viewer 越权）" 403 -X POST -H "X-API-Key: $VIEWER_KEY" \
  -H 'Content-Type: application/json' -d '{"name":"drill_denied","type":"mysql"}' "$BASE/datasources"
probe "DELETE /datasources/999999（editor 越权）" 403 -X DELETE \
  -H "X-API-Key: $EDITOR_KEY" "$BASE/datasources/999999"

echo
echo "[4] 合法写操作 —— 必须留痕"
CREATED=$(curl -s -X POST -H "X-API-Key: $EDITOR_KEY" -H 'Content-Type: application/json' \
  -d '{"name":"drill_ok","type":"mysql","host":"127.0.0.1"}' "$BASE/datasources")
NEW_ID=$(printf '%s' "$CREATED" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("id",""))' 2>/dev/null)
probe "POST /datasources 后复查（editor 只读，不留痕）" 200 \
  -H "X-API-Key: $EDITOR_KEY" "$BASE/datasources"

if [ -n "$NEW_ID" ]; then
  probe "DELETE /datasources/$NEW_ID（admin）" 204 -X DELETE -H "X-API-Key: $ADMIN_KEY" \
    "$BASE/datasources/$NEW_ID"
else
  echo "  （跳过删除：创建数据源失败，检查服务日志）"
  note_fail
fi

echo
echo "======================================================"
echo " 结果：$PASS 项符合预期，$FAIL 项不符"
echo "======================================================"

if [ -f "$FILE" ]; then
  echo
  echo "审计文件现状：$(lines) 行"
  echo "按状态码统计："
  grep -o '"status": [0-9]*' "$FILE" 2>/dev/null | sort | uniq -c | sed 's/^/  /'
  echo
  echo "最近 5 条："
  tail -5 "$FILE" 2>/dev/null | python3 -c "
import sys, json
for line in sys.stdin:
    d = json.loads(line)
    print('  {}  {:<24} {:<6} {:<20} {}'.format(d['ts'], d['actor'], d['method'], d['path'], d['status']))
"
  echo
  echo "汇总报表：./scripts/audit_report.sh -f $FILE"
fi

[ "$FAIL" -eq 0 ] || exit 1
