"""把 pytest 的 junitxml 结果转成自包含 HTML 报告，不依赖 pytest-html。"""
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from html import escape

SRC = sys.argv[1] if len(sys.argv) > 1 else "report.xml"
DST = sys.argv[2] if len(sys.argv) > 2 else "report.html"

tree = ET.parse(SRC)
cases = tree.getroot().findall(".//testcase")

rows, passed, failed = [], 0, 0
for c in cases:
    cls, name = c.get("classname", ""), c.get("name", "")
    time_s = float(c.get("time", 0) or 0)
    fail_node = c.find("failure")
    err_node = c.find("error")

    if fail_node is not None or err_node is not None:
        status, detail = "FAIL", (fail_node if fail_node is not None else err_node)
        failed += 1
    elif c.find("skipped") is not None:
        status, detail = "SKIP", None
    else:
        status, detail = "PASS", None
        passed += 1

    msg = ""
    if detail is not None:
        msg = escape((detail.get("message") or (detail.text or ""))[:800])

    rows.append((status, cls, name, f"{time_s:.3f}s", msg))

total = len(cases)
rate = f"{passed / total * 100:.1f}%" if total else "0%"
color = {"PASS": "#1a7f37", "FAIL": "#b42318", "SKIP": "#8a6d3b"}

html = [
    '<html style="margin:0;padding:0;">',
    '<div style="font-family:\'PingFang SC\',\'Microsoft YaHei\',Arial,sans-serif;padding:16px;box-sizing:border-box;">',
    '<div style="font-size:18px;font-weight:600;color:#1A1B1C;">接口自动化测试报告</div>',
    f'<div style="font-size:12px;color:#6B7280;margin-top:4px;">生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}'
    f'　|　总数 {total}　通过 {passed}　失败 {failed}　通过率 {rate}</div>',
    '<div style="display:flex;gap:10px;flex-wrap:wrap;margin:14px 0;">',
]
for label, val, c in [("用例总数", total, "#9EACEA"), ("通过", passed, "#A2DDAA"), ("失败", failed, "#EAA7B2")]:
    html.append(
        f'<div style="flex:1 1 120px;min-width:0;padding:10px 12px;border-radius:12px;'
        f'background:linear-gradient(135deg,{c}22,{c}44);box-sizing:border-box;">'
        f'<div style="font-size:12px;color:#6B7280;">{label}</div>'
        f'<div style="font-size:20px;font-weight:600;color:#1A1B1C;">{val}</div></div>'
    )
html.append('</div>')
html.append(
    '<table style="width:100%;border-collapse:collapse;font-size:13px;">'
    '<thead><tr style="background:#F4F3EE;text-align:left;">'
    '<th style="padding:8px;border-bottom:1px solid #E4E3DD;">结果</th>'
    '<th style="padding:8px;border-bottom:1px solid #E4E3DD;">模块</th>'
    '<th style="padding:8px;border-bottom:1px solid #E4E3DD;">用例</th>'
    '<th style="padding:8px;border-bottom:1px solid #E4E3DD;">耗时</th>'
    '</tr></thead><tbody>'
)
for status, cls, name, dur, msg in rows:
    html.append(
        f'<tr><td style="padding:6px 8px;border-bottom:1px solid #F0EFEA;color:{color[status]};font-weight:600;">{status}</td>'
        f'<td style="padding:6px 8px;border-bottom:1px solid #F0EFEA;color:#6B7280;">{escape(cls)}</td>'
        f'<td style="padding:6px 8px;border-bottom:1px solid #F0EFEA;">{escape(name)}'
        + (f'<div style="font-size:12px;color:#b42318;white-space:pre-wrap;margin-top:4px;">{msg}</div>' if msg else '')
        + '</td>'
        f'<td style="padding:6px 8px;border-bottom:1px solid #F0EFEA;color:#6B7280;">{dur}</td></tr>'
    )
html.append('</tbody></table></div></html>')

with open(DST, "w", encoding="utf-8") as f:
    f.write("\n".join(html))
print(f"报告已生成：{DST}（{total} 条，通过率 {rate}）")
