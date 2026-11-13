#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
BASE=${API_BASE_URL:-http://127.0.0.1:8000}

code=$(curl --noproxy '*' -s --max-time 5 -o /dev/null -w "%{http_code}" "$BASE/" || true)
if [ "$code" != "200" ]; then
  echo "[x] 服务未就绪：$BASE/ 返回 $code"
  echo "    cd ~/projects/data-catalog && sudo docker compose up -d"
  exit 1
fi

echo "[+] 服务就绪：$BASE"

if python -c "import pytest_html" 2>/dev/null; then
  python -m pytest -v --html=report.html --self-contained-html
else
  echo "[i] 未装 pytest-html，改用 junitxml + 本地转换"
  python -m pytest -v --junitxml=report.xml || true
  python make_report.py report.xml report.html
fi

echo "[+] 报告：$(pwd)/report.html"
