#!/usr/bin/env bash
# 本地启动：先清掉占用端口的旧进程，再按统一环境变量起服务。
# 用法：./scripts/start-local.sh            # 默认 8000
#       PORT=8001 ./scripts/start-local.sh  # 换端口
#       DOCS_ENABLED=0 ./scripts/start-local.sh
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
PROJECT_DIR="$(pwd)"
PORT="${PORT:-8000}"

# 可选：把本地配置放在项目根的 .env.local（不会被提交）
if [ -f .env.local ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env.local
  set +a
fi

export AUTH_MODE="${AUTH_MODE:-apikey}"
export API_KEYS="${API_KEYS:-admin:sk_admin_local_00000000,editor:sk_editor_local_1111111,viewer:sk_viewer_local_222222}"
export DATABASE_URL="${DATABASE_URL:-sqlite:///./dev.db}"

pids_on_port() {
  if command -v fuser >/dev/null 2>&1; then
    fuser -n tcp "$PORT" 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+$'
  else
    ss -ltnp 2>/dev/null | awk -v pat=":$PORT\$" '$4 ~ pat' \
      | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u
  fi
}

mapfile -t PIDS < <(pids_on_port | sort -u)
if [ "${#PIDS[@]}" -gt 0 ]; then
  echo "[预检] 端口 $PORT 已被占用，逐个判断来源："
  for pid in "${PIDS[@]}"; do
    cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || echo '未知')"
    cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | cut -c1-90)"
    echo "  PID=$pid cwd=$cwd"
    echo "          cmd=$cmd"
    if [ "$cwd" != "$PROJECT_DIR" ]; then
      echo "          ⚠ 这个进程不在当前目录，确认后仍会被杀掉（端口必须让出来）"
    fi
  done

  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  for _ in $(seq 1 20); do
    [ "$(pids_on_port | wc -l)" -eq 0 ] && break
    sleep 0.25
  done
  leftovers="$(pids_on_port | tr '\n' ' ')"
  if [ -n "${leftovers// /}" ]; then
    echo "[预检] 仍在占用，强制结束：$leftovers"
    for pid in $leftovers; do kill -9 "$pid" 2>/dev/null || true; done
    sleep 0.5
  fi
  echo "[预检] 端口 $PORT 已释放"
else
  echo "[预检] 端口 $PORT 空闲"
fi

# Ubuntu 只提供 python3（PEP 394），所以按 venv → python3 的顺序找解释器
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  echo "[错误] 找不到 python3，先装：sudo apt install -y python3 python3-venv" >&2
  exit 1
fi

echo "[启动] $PROJECT_DIR → 0.0.0.0:$PORT  (AUTH_MODE=$AUTH_MODE, DOCS_ENABLED=${DOCS_ENABLED:-1}, PY=$PY)"
exec "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
