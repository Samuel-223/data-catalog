#!/usr/bin/env bash
# 本地停止：按端口找进程，打印来源目录再结束。用法：PORT=8001 ./scripts/stop-local.sh
set -uo pipefail
PORT="${PORT:-8000}"

pids_on_port() {
  if command -v fuser >/dev/null 2>&1; then
    fuser -n tcp "$PORT" 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+$'
  else
    ss -ltnp 2>/dev/null | awk -v pat=":$PORT\$" '$4 ~ pat' \
      | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u
  fi
}

PIDS="$(pids_on_port | sort -u | tr '\n' ' ')"
if [ -z "${PIDS// /}" ]; then
  echo "端口 $PORT 没有进程"
  exit 0
fi

for pid in $PIDS; do
  echo "停止 PID=$pid cwd=$(readlink "/proc/$pid/cwd" 2>/dev/null || echo '未知')"
  kill "$pid" 2>/dev/null || true
done

for _ in $(seq 1 20); do
  [ "$(pids_on_port | wc -l)" -eq 0 ] && break
  sleep 0.25
done
leftovers="$(pids_on_port | tr '\n' ' ')"
[ -n "${leftovers// /}" ] && for pid in $leftovers; do kill -9 "$pid" 2>/dev/null || true; done
echo "端口 $PORT 已释放"
