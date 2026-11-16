#!/usr/bin/env bash
# 审计日志报表：只用 grep / awk / sort / tail，不依赖 python 或数据库。
#
# 用法：
#   ./scripts/audit_report.sh                      # 读 AUDIT_LOG_PATH 或默认路径
#   ./scripts/audit_report.sh -f audit.jsonl       # 指定文件
#   ./scripts/audit_report.sh -n 20                # 最近 20 条
#   ./scripts/audit_report.sh --since 2026-11-16   # 只看某天之后
set -uo pipefail

FILE="${AUDIT_LOG_PATH:-/var/log/data-catalog/audit.jsonl}"
LINES=10
SINCE=""

while [ $# -gt 0 ]; do
  case "$1" in
    -f) FILE="$2"; shift 2 ;;
    -n) LINES="$2"; shift 2 ;;
    --since) SINCE="$2"; shift 2 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

if [ ! -r "$FILE" ]; then
  echo "读不到审计文件：$FILE" >&2
  echo "提示：确认属主与权限（建议 appuser:adm 640），或用 sudo 运行" >&2
  exit 1
fi

lines() {
  if [ -n "$SINCE" ]; then
    grep -- "$SINCE" "$FILE"
  else
    cat "$FILE"
  fi
}

echo "==================== 审计概览 ===================="
echo "文件：$FILE"
echo "大小：$(du -h "$FILE" | cut -f1)    行数：$(wc -l < "$FILE")"
echo "时间范围：$(head -1 "$FILE" | grep -o '"ts": "[^"]*"' | cut -d'"' -f4) → $(tail -1 "$FILE" | grep -o '"ts": "[^"]*"' | cut -d'"' -f4)"
echo

echo "----------- 按操作人统计 -------------------------------"
lines | grep -o '"actor": "[^"]*"' | cut -d'"' -f4 | sort | uniq -c | sort -rn |
  awk '{printf "  %-30s %4d 次\n", $2, $1}'
echo

echo "----------- 按状态码统计 -------------------------------"
lines | grep -o '"status": [0-9]*' | awk -F': ' '{print $2}' | sort | uniq -c | sort -rn |
  awk '{printf "  HTTP %-4s %4d 次\n", $2, $1}'
echo

echo "----------- 被拒最多的路径（401/403） ------------------"
lines | grep -E '"status": (401|403)' | grep -o '"path": "[^"]*"' | cut -d'"' -f4 |
  sort | uniq -c | sort -rn | head -5 | awk '{printf "  %-34s %4d 次\n", $2, $1}'
echo

echo "----------- 写操作热度（路径维度） ---------------------"
lines | grep -E '"method": "(POST|PUT|PATCH|DELETE)"' | grep -o '"path": "[^"]*"' | cut -d'"' -f4 |
  sort | uniq -c | sort -rn | head -5 | awk '{printf "  %-34s %4d 次\n", $2, $1}'
echo

echo "----------- 最近 $LINES 条原始记录 ---------------------"
tail -n "$LINES" "$FILE"
echo

echo "============== 可疑信号（需人工复核） ================="
denied=$(lines | grep -c '"status": 403' || true)
unauth=$(lines | grep -c '"actor": "unknown"' || true)
server_err=$(lines | grep -cE '"status": 5' || true)
[ "${denied:-0}" -gt 0 ] && echo "  · 403 共 ${denied} 次：存在越权尝试，核对 actor 是否为内部账号"
[ "${unauth:-0}" -gt 0 ] && echo "  · 未认证调用 ${unauth} 次（actor=unknown），核对来源 IP 与密钥下发"
[ "${server_err:-0}" -gt 0 ] && echo "  · 5xx 共 ${server_err} 次，排查服务端异常"
if [ "${denied:-0}" -eq 0 ] && [ "${unauth:-0}" -eq 0 ] && [ "${server_err:-0}" -eq 0 ]; then
  echo "  （无异常信号）"
fi
