"""接口安全检查：注入、畸形输入、信息泄露、鉴权缺失四类。零第三方依赖，用 urllib。"""
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = 8
LEAK_MARKERS = ("Traceback", "psycopg", "sqlalchemy", "SELECT ", "/home/", "app/models", "PostgreSQL")

results = []


def call(method, path, body=None, headers=None, raw_body=None):
    url = BASE + path
    data = None
    hdrs = {"User-Agent": "sec-check"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode()
        hdrs["Content-Type"] = "application/json"
    if raw_body is not None:
        data = raw_body.encode()
        hdrs["Content-Type"] = "application/json"
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8", "ignore"), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "ignore"), dict(exc.headers)
    except Exception as exc:  # noqa: BLE001
        return 0, f"<{type(exc).__name__}: {exc}>", {}


def record(cid, category, case, verdict, note):
    results.append({"id": cid, "category": category, "case": case,
                    "verdict": verdict, "note": note})


def leaked(text):
    hits = [m for m in LEAK_MARKERS if m in text]
    return hits


# ---------- ① 注入类 ----------
def t01():
    status, body, _ = call("GET", "/datasources/1%20OR%201=1")
    if status >= 500:
        record("S01", "注入", "路径参数注入 id=1 OR 1=1", "FAIL", f"返回 {status}，服务端异常")
    else:
        record("S01", "注入", "路径参数注入 id=1 OR 1=1", "PASS", f"返回 {status}，未被拼接执行")


def t02():
    status, body, _ = call("GET", "/datasources/9999999999999999999999")
    if status >= 500:
        record("S02", "注入", "超范围整数 id 溢出", "FAIL", f"返回 {status}")
    else:
        record("S02", "注入", "超范围整数 id 溢出", "PASS", f"返回 {status}")


def t03():
    status, body, _ = call("GET", "/datasources?skip=0%27%20OR%201=1")
    if status >= 500:
        record("S03", "注入", "查询参数注入 skip=0' OR 1=1", "FAIL", f"返回 {status}")
    else:
        record("S03", "注入", "查询参数注入 skip=0' OR 1=1", "PASS", f"返回 {status}")


def t04():
    payload = "'; DROP TABLE datasource; --"
    name = f"sec_{uuid.uuid4().hex[:6]}"
    status, body, _ = call("POST", "/datasources",
                           {"name": name, "type": "mysql", "host": payload,
                            "owner": payload, "description": payload})
    if status >= 500:
        record("S04", "注入", "字段写入 SQL 片段", "FAIL", f"返回 {status}")
        return
    ds_id = json.loads(body).get("id") if body.strip().startswith("{") else None

    after_status, after_body, _ = call("GET", "/datasources")
    stored_literal, table_ok = False, False
    if after_status == 200:
        try:
            items = json.loads(after_body)
            table_ok = isinstance(items, list)
            stored_literal = any(i.get("name") == name and i.get("host") == payload for i in items)
        except Exception:  # noqa: BLE001
            table_ok = False

    if ds_id:
        call("DELETE", f"/datasources/{ds_id}")

    if not table_ok:
        record("S04", "注入", "字段写入 SQL 片段后校验表完整性", "FAIL", "写入后列表接口异常")
    elif stored_literal:
        record("S04", "注入", "字段写入 SQL 片段后校验表完整性", "PASS",
               "载荷按字面值存储，未被执行")
    else:
        record("S04", "注入", "字段写入 SQL 片段后校验表完整性", "INFO",
               "写入成功但回读值被改写，需人工确认")


# ---------- ② 畸形输入 ----------
def t05():
    status, body, _ = call("POST", "/datasources", body=None, raw_body='{"name": ')
    record("S05", "畸形输入", "非法 JSON", "PASS" if status == 422 else "FAIL",
           f"返回 {status}")


def t06():
    status, body, _ = call("POST", "/datasources", {"name": 12345, "type": {"a": 1}})
    record("S06", "畸形输入", "字段类型错误", "PASS" if status == 422 else "FAIL",
           f"返回 {status}")


def t07():
    status, body, _ = call("POST", "/datasources", {})
    record("S07", "畸形输入", "空 body", "PASS" if status == 422 else "FAIL",
           f"返回 {status}")


def t08():
    long_name = "A" * 100000
    status, body, _ = call("POST", "/datasources",
                           {"name": long_name[:200] + long_name[200:300],
                            "type": "mysql", "description": long_name})
    if status >= 500:
        record("S08", "畸形输入", "10 万字符超长字段", "FAIL", f"返回 {status}")
    elif status == 422:
        record("S08", "畸形输入", "10 万字符超长字段", "PASS", "被长度校验拦截")
    else:
        record("S08", "畸形输入", "10 万字符超长字段", "INFO", f"返回 {status}，未做长度限制")


def t09():
    status, body, _ = call("POST", "/datasources",
                           {"name": "x", "type": "mysql", "host": "h",
                            "owner": "o", "unknown_field": "v"})
    if status >= 500:
        record("S09", "畸形输入", "多余未知字段", "FAIL", f"返回 {status}")
    elif status in (400, 422):
        record("S09", "畸形输入", "多余未知字段", "PASS", f"返回 {status}，多余字段被拒绝")
    else:
        record("S09", "畸形输入", "多余未知字段", "INFO", f"返回 {status}，多余字段被静默忽略")

def t10():
    status, body, _ = call("GET", "/datasources/999999")
    hits = leaked(body)
    record("S10", "信息泄露", "404 响应体是否泄露实现细节",
           "PASS" if not hits else "FAIL",
           "无敏感片段" if not hits else f"泄露：{hits}")


def t11():
    status, body, _ = call("POST", "/datasources", {})
    hits = leaked(body)
    record("S11", "信息泄露", "422 响应体是否泄露实现细节",
           "PASS" if not hits else "FAIL",
           "无敏感片段" if not hits else f"泄露：{hits}")


def t12():
    status, body, headers = call("GET", "/admin")
    record("S12", "信息泄露", "未定义路由返回", "PASS" if status == 404 else "FAIL",
           f"返回 {status}")


def t13():
    _, _, headers = call("GET", "/datasources")
    lower = {k.lower(): v for k, v in headers.items()}
    missing = [h for h in ("x-content-type-options", "x-frame-options", "strict-transport-security")
               if h not in lower]
    record("S13", "信息泄露", "安全响应头", "INFO" if missing else "PASS",
           f"缺少：{', '.join(missing)}" if missing else "响应头齐全")


# ---------- ④ 鉴权 ----------
def t14():
    status, _, _ = call("GET", "/datasources")
    record("S14", "鉴权", "无凭证读取接口", "INFO" if status == 200 else "FAIL",
           f"返回 {status}，接口无认证即可读取")


def t15():
    status, body, _ = call("POST", "/datasources",
                           {"name": f"sec_noauth_{uuid.uuid4().hex[:6]}", "type": "mysql"})
    if status in (200, 201):
        ds_id = json.loads(body).get("id")
        call("DELETE", f"/datasources/{ds_id}")
        record("S15", "鉴权", "无凭证写入接口", "INFO", "接口无认证即可写入")
    else:
        record("S15", "鉴权", "无凭证写入接口", "PASS", f"返回 {status}，写入被拦截")


def t16():
    status, _, _ = call("TRACE", "/datasources")
    record("S16", "鉴权", "TRACE 方法探测", "PASS" if status in (405, 404, 400) else "INFO",
           f"返回 {status}")


for fn in (t01, t02, t03, t04, t05, t06, t07, t08, t09,
           t10, t11, t12, t13, t14, t15, t16):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        record("ERR", "执行异常", fn.__name__, "FAIL", str(exc))

# ---------- 输出 ----------
print(f"{'编号':<5}{'类别':<8}{'用例':<34}{'结果':<7}说明")
print("-" * 92)
for r in results:
    print(f"{r['id']:<5}{r['category']:<8}{r['case']:<34}{r['verdict']:<7}{r['note']}")

counts = {}
for r in results:
    counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
print("-" * 92)
print("汇总：", "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))

with open("security_result.json", "w", encoding="utf-8") as f:
    json.dump({"base": BASE, "results": results, "counts": counts}, f,
              ensure_ascii=False, indent=2)
print("明细已写入 security_result.json")
