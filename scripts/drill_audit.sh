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

ROOT=$(cd "$(dirname "$0")/.." && pwd)

# 从项目根 .env.local 的 API_KEYS 里取某个角色的 key：role_key editor
role_key() {
  local role="$1" line
  [ -f "$ROOT/.env.local" ] || return 1
  line=$(grep -E '^API_KEYS=' "$ROOT/.env.local" | tail -1 | cut -d= -f2-)
  line=$(printf '%s' "$line" | tr -d '"' | tr -d "'")
  printf '%s' "$line" | tr ',' '\n' | grep -E "^${role}:" | head -1 | cut -d: -f2- | tr -d ' \r'
}

pk() {  # pk 角色 环境变量值 兜底默认值
  local role="$1" given="$2" fallback="$3" found=""
  if [ -n "$given" ]; then printf '%s' "$given"; return; fi
  found=$(role_key "$role" 2>/dev/null || true)
  printf '%s' "${found:-$fallback}"
}

ADMIN_KEY=$(pk admin "${DRILL_ADMIN_KEY:-}" "sk_admin_local_00000000")
EDITOR_KEY=$(pk editor "${DRILL_EDITOR_KEY:-}" "sk_editor_local_1111111")
VIEWER_KEY=$(pk viewer "${DRILL_VIEWER_KEY:-}" "sk_viewer_local_222222")
KEY_SOURCE="默认值"
[ -f "$ROOT/.env.local" ] && grep -q '^API_KEYS=' "$ROOT/.env.local" 2>/dev/null && KEY_SOURCE=".env.local"

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
echo "[0.5] 身份自检（key 来源：$KEY_SOURCE）"
BAD_KEY=0
for pair in "admin:$ADMIN_KEY" "editor:$EDITOR_KEY" "viewer:$VIEWER_KEY"; do
  role=${pair%%:*}; key=${pair#*:}
  code=$(curl -s -o /dev/null -w '%{http_code}' -H "X-API-Key: $key" "$BASE/datasources")
  head_key=$(printf '%s' "$key" | cut -c1-18)
  if [ "$code" = "200" ]; then
    printf '  %-8s %s…  %s\n' "$role" "$head_key" "$code"
  else
    printf '  %-8s %s…  %s  ✗该角色 key 无效\n' "$role" "$head_key" "$code"
    BAD_KEY=1
  fi
done
if [ "$BAD_KEY" -ne 0 ]; then
  cat <<'HINT'

  提示：脚本用的 key 与服务端 API_KEYS 不一致，后续所有场景都会 401。
  修法之一：把 .env.local 的 API_KEYS 改成脚本读取的那一套后重启服务
  修法之二：显式传入真实 key
      DRILL_ADMIN_KEY=... DRILL_EDITOR_KEY=... DRILL_VIEWER_KEY=... ./scripts/drill_audit.sh
HINT
  exit 3
fi

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

if [ ! -f "$FILE" ]; then
  echo
  echo "⚠️ 审计文件仍不存在：一个必然留痕的请求（无密钥 401）都没写进来。"
  echo "   说明服务端 AUDIT_LOG_PATH 与这里的 $FILE 不是同一个文件："
  echo "   tr '\0' '\n' < /proc/\$(pgrep -f 'uvicorn app.main:app' | head -1)/environ | grep AUDIT_LOG_PATH"
  echo "   然后用 -f 指向服务端那个路径重跑。"
  note_fail
fi

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
