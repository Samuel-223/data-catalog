import pytest

from conftest import unique


@pytest.mark.smoke
def test_service_alive(api):
    """服务根路径可访问，openapi 路径数量与预期一致。"""
    assert api.get("/").status_code == 200

    r = api.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    ops = sum(len(v) for v in paths.values())
    assert len(paths) >= 12, f"路径数量异常：{len(paths)}"
    assert ops >= 20, f"接口操作数量异常：{ops}"


def test_create_datasource(api):
    name = unique("ds")
    r = api.post("/datasources", {
        "name": name, "type": "mysql", "host": "10.0.0.1",
        "owner": "auto", "description": "创建校验",
    })
    assert r.status_code in (200, 201), r.text

    body = r.json()
    assert body["name"] == name
    assert body["type"] == "mysql"
    assert isinstance(body["id"], int) and body["id"] > 0
    assert body["created_at"], "created_at 不应为空"

    api.delete(f"/datasources/{body['id']}")


@pytest.mark.parametrize("payload,desc", [
    ({"name": "only_name"}, "缺少 type"),
    ({"type": "mysql"}, "缺少 name"),
    ({}, "全部缺失"),
])
def test_create_datasource_missing_field(api, payload, desc):
    r = api.post("/datasources", payload)
    assert r.status_code == 422, f"{desc} 应返回 422，实际 {r.status_code}"
    assert r.json()["detail"], "422 响应应包含 detail"


def test_get_datasource(api, datasource):
    r = api.get(f"/datasources/{datasource['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == datasource["id"]
    assert body["name"] == datasource["name"]


def test_get_datasource_not_found(api):
    r = api.get("/datasources/999999")
    assert r.status_code == 404, f"不存在的 ID 应返回 404，实际 {r.status_code}"


def test_update_datasource(api, datasource):
    new_owner = unique("owner")
    r = api.put(f"/datasources/{datasource['id']}", {
        "name": datasource["name"], "type": "postgresql",
        "host": "10.0.0.2", "owner": new_owner, "description": "更新校验",
    })
    assert r.status_code == 200, r.text
    assert r.json()["owner"] == new_owner

    again = api.get(f"/datasources/{datasource['id']}").json()
    assert again["owner"] == new_owner, "更新后回查数据未生效"
    assert again["type"] == "postgresql"


def test_list_datasources_contains_new(api, datasource):
    r = api.get("/datasources")
    assert r.status_code == 200
    names = [item["name"] for item in r.json()]
    assert datasource["name"] in names, "新建数据源未出现在列表中"


def test_delete_datasource(api, datasource):
    r = api.delete(f"/datasources/{datasource['id']}")
    assert r.status_code in (200, 204), f"删除应返回 200/204，实际 {r.status_code}"

    again = api.get(f"/datasources/{datasource['id']}")
    assert again.status_code == 404, "删除后再查应返回 404"
