import os
import uuid

import pytest
import httpx

BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = float(os.getenv("API_TIMEOUT", "10"))


def unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def extract_ids(payload):
    """兼容 list / {items:[...]} / {upstream:[...]} 等返回结构，统一取出 id。"""
    if isinstance(payload, dict):
        for key in ("items", "upstream", "downstream", "relations", "data"):
            if key in payload and isinstance(payload[key], list):
                payload = payload[key]
                break
        else:
            payload = []
    ids = []
    for item in payload:
        if isinstance(item, dict):
            ids.append(item.get("id", item.get("column_id")))
        else:
            ids.append(item)
    return ids


class Api:
    def __init__(self, session, base_url):
        self.s = session
        self.base = base_url

    def get(self, path, **kwargs):
        return self.s.get(self.base + path, timeout=TIMEOUT, **kwargs)

    def post(self, path, json=None):
        return self.s.post(self.base + path, json=json, timeout=TIMEOUT)

    def put(self, path, json=None):
        return self.s.put(self.base + path, json=json, timeout=TIMEOUT)

    def delete(self, path):
        return self.s.delete(self.base + path, timeout=TIMEOUT)


@pytest.fixture(scope="session")
def api():
    session = httpx.Client()
    session.headers.update({"Content-Type": "application/json"})
    try:
        r = session.get(BASE_URL + "/", timeout=TIMEOUT)
    except httpx.RequestException as exc:
        pytest.exit(f"无法连接被测服务 {BASE_URL}：{exc}", returncode=1)
    assert r.status_code == 200, f"被测服务异常，GET / 返回 {r.status_code}"
    yield Api(session, BASE_URL)
    session.close()


@pytest.fixture
def datasource(api):
    payload = {
        "name": unique("ds"),
        "type": "mysql",
        "host": "127.0.0.1",
        "owner": "auto",
        "description": "接口自动化生成，用例结束自动删除",
    }
    r = api.post("/datasources", payload)
    assert r.status_code in (200, 201), f"创建数据源失败：{r.status_code} {r.text}"
    ds = r.json()
    yield ds
    api.delete(f"/datasources/{ds['id']}")


@pytest.fixture
def table(api, datasource):
    payload = {
        "table_name": unique("tbl"),
        "layer": "ODS",
        "description": "自动化用例表",
        "owner": "auto",
        "datasource_id": datasource["id"],
    }
    r = api.post("/tables", payload)
    assert r.status_code in (200, 201), f"创建表失败：{r.status_code} {r.text}"
    tb = r.json()
    yield tb
    api.delete(f"/tables/{tb['id']}")


@pytest.fixture
def make_column(api, table):
    def _make(name=None, **kwargs):
        payload = {
            "column_name": name or unique("col"),
            "data_type": "varchar",
            "is_sensitive": False,
            "description": "自动化用例字段",
            **kwargs,
        }
        r = api.post(f"/tables/{table['id']}/columns", payload)
        assert r.status_code in (200, 201), f"创建字段失败：{r.status_code} {r.text}"
        return r.json()

    return _make


@pytest.fixture
def rule_factory(api):
    created = []

    def _make(table_id, rule_type, column_id=None, threshold=None, enabled=True):
        payload = {"table_id": table_id, "rule_type": rule_type, "enabled": enabled}
        if column_id is not None:
            payload["column_id"] = column_id
        if threshold is not None:
            payload["threshold"] = threshold
        r = api.post("/rules", payload)
        assert r.status_code in (200, 201), f"创建规则失败：{r.status_code} {r.text}"
        rule = r.json()
        created.append(rule)
        return rule

    yield _make
    for rule in created:
        api.delete(f"/rules/{rule['id']}")
