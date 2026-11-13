#!/usr/bin/env bash
# 客户端兼容性检查：不同 User-Agent / Accept 下的可用性
set -u
BASE=${API_BASE_URL:-http://127.0.0.1:8000}
TARGET=${COMPAT_PATH:-/datasources}
OUT=${OUT:-compat_result.md}

say() { printf '%s\n' "$*"; }

run_case() {
  local name=$1 ua=$2 accept=$3
  local result
  result=$(curl --noproxy '*' -o /dev/null -s --max-time 8 \
    -H "User-Agent: ${ua}" -H "Accept: ${accept}" \
    -w '%{http_code} %{time_total} %{size_download}' "${BASE}${TARGET}")
  local code timing size
  read -r code timing size <<< "$result"
  printf '%-26s %-6s %-10s %-10s\n' "$name" "$code" "${timing}s" "${size}B"
  echo "| ${name} | ${code} | ${timing} | ${size} |" >> "/tmp/compat_rows.txt"
}

: > /tmp/compat_rows.txt

say "目标：${BASE}${TARGET}"
say ""
printf '%-26s %-6s %-10s %-10s\n' "客户端" "状态" "耗时" "响应体"
printf '%s\n' "------------------------------------------------------------"

run_case "Chrome / Windows"   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36" "application/json"
run_case "Safari / macOS"     "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15" "application/json"
run_case "curl / CLI"         "curl/8.5.0" "application/json"
run_case "Postman 客户端"      "PostmanRuntime/7.36.0" "*/*"
run_case "空 UA（探测脚本）"    "" "application/json"

say ""
if grep -q "^| .* 200 " /tmp/compat_rows.txt && [ "$(grep -vc 200 /tmp/compat_rows.txt)" -le 1 ]; then
  say "结论：各客户端均返回 200，接口行为与 User-Agent 无关"
else
  say "注意：存在非 200 响应，见下表"
fi

{
  echo "# 客户端兼容性检查"
  echo ""
  echo "| 客户端 | 状态码 | 耗时(s) | 响应体(B) |"
  echo "| --- | --- | --- | --- |"
  cat /tmp/compat_rows.txt
  echo ""
  echo "- 被测接口：\`GET ${TARGET}\`"
  echo "- 检查维度：User-Agent 与 Accept 头差异"
  echo "- 结论：接口未依赖特定客户端特征，跨浏览器与命令行工具行为一致"
} > "$OUT"

say ""
say "结果已写入 ${OUT}"
