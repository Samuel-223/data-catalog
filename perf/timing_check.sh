#!/usr/bin/env bash
# 时序对比：压测前 vs 压测中，同一请求的 TTFB（对应浏览器「响应」段）
set -u

BASE=${API_BASE_URL:-http://127.0.0.1:8000}
TARGET=${TIMING_PATH:-/openapi.json}
CONC=${CONC:-50}
TOTAL=${TOTAL:-20000}
SAMPLES=${SAMPLES:-5}
OUT=${OUT:-timing_result.md}
AB_LOG=/tmp/ab_timing.log

say() { printf '%s\n' "$*"; }

ttfb_line() {
  curl --noproxy '*' -o /dev/null -s --max-time 15 \
    -w '%{http_code} %{time_starttransfer} %{time_total}\n' "${BASE}${TARGET}"
}

sample() {
  local n=$1 tag=$2
  : > "/tmp/timing_${tag}.txt"
  local i=0
  while [ "$i" -lt "$n" ]; do
    ttfb_line >> "/tmp/timing_${tag}.txt"
    i=$((i + 1))
    sleep 0.2
  done
}

stat() {
  local f=$1
  awk 'NF>=3 {s+=$2; if(NR==1||$2<min)min=$2; if($2>max)max=$2; if($1!=200)bad++}
       END {if(NR>0) printf "%d %.1f %.1f %.1f %d\n", NR, s/NR*1000, min*1000, max*1000, bad+0}' "$f"
}

say "目标：${BASE}${TARGET}"
say "压测：ab -k -s 10 -n ${TOTAL} -c ${CONC} ${BASE}/datasources"
say ""

if ! command -v ab >/dev/null 2>&1; then
  say "未找到 ab，请先安装：sudo apt-get install -y apache2-utils"
  exit 1
fi

code=$(ttfb_line | awk '{print $1}')
say "服务探活：HTTP ${code}"
if [ "$code" != "200" ]; then
  say "服务未就绪，先 docker compose up -d 再跑"
  exit 1
fi

say "① 采集基线（${SAMPLES} 次）"
sample "$SAMPLES" before
read -r n1 avg1 min1 max1 bad1 <<EOF
$(stat /tmp/timing_before.txt)
EOF
say "   基线 TTFB 均值 ${avg1}ms（min ${min1} / max ${max1}）"

say "② 启动压测并在压测中采集（${SAMPLES} 次）"
ab -k -s 10 -n "$TOTAL" -c "$CONC" "${BASE}/datasources" > "$AB_LOG" 2>&1 &
AB_PID=$!

sleep 3
sample "$SAMPLES" during
read -r n2 avg2 min2 max2 bad2 <<EOF
$(stat /tmp/timing_during.txt)
EOF
say "   压测中 TTFB 均值 ${avg2}ms（min ${min2} / max ${max2}）"

wait "$AB_PID" 2>/dev/null

AB_RPS=$(grep -o 'Requests per second:.*' "$AB_LOG" | head -1 | sed 's/[^0-9.]//g')
AB_FAIL=$(grep -o 'Failed requests:.*' "$AB_LOG" | head -1 | sed 's/[^0-9]//g')
say ""
say "③ 压测结果：TPS ${AB_RPS:-未取到}  失败 ${AB_FAIL:-未取到}"

RATIO=$(awk -v a="$avg1" -v b="$avg2" 'BEGIN{if(a>0)printf "%.1f", b/a; else print "0"}')

cat > "$OUT" <<EOF
# 时序对比：压测前 vs 压测中

| 场景 | 采样次数 | TTFB 均值 | 最小值 | 最大值 | 非 200 次数 |
|---|---|---|---|---|---|
| 压测前 | ${n1} | ${avg1} ms | ${min1} ms | ${max1} ms | ${bad1} |
| 压测中（${CONC} 并发） | ${n2} | ${avg2} ms | ${min2} ms | ${max2} ms | ${bad2} |

- 被测请求：\`GET ${TARGET}\`
- 压测命令：\`ab -k -s 10 -n ${TOTAL} -c ${CONC} ${BASE}/datasources\`
- 压测吞吐：${AB_RPS:-—} req/s，失败请求 ${AB_FAIL:-—}
- TTFB 抬升倍数：**${RATIO}x**

## 结论

同一请求在压测前后的 TTFB 由 ${avg1}ms 升至 ${avg2}ms，抬升 ${RATIO} 倍。
本机回环访问下 DNS、TCP、TLS 三段接近 0，耗时几乎全部落在「响应」段，
说明延迟来自服务端处理排队，而非链路质量。
EOF

say ""
say "对比表已写入 ${OUT}"
say "| 场景 | 采样次数 | TTFB 均值 | 最小 | 最大 | 非 200 |"
say "|---|---|---|---|---|---|"
say "| 压测前 | ${n1} | ${avg1}ms | ${min1}ms | ${max1}ms | ${bad1} |"
say "| 压测中(${CONC} 并发) | ${n2} | ${avg2}ms | ${min2}ms | ${max2}ms | ${bad2} |"
say ""
say "TTFB 抬升：${RATIO}x（压测中 / 压测前）"
if [ "${bad2}" != "0" ]; then say "注意：压测中出现了 ${bad2} 次非 200 响应，说明已接近或超过容量边界"; fi
