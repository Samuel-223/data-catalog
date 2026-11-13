import pytest

from conftest import unique


def test_create_table(api, datasource):
    name = unique("tbl")
    r = api.post("/tables", {
        "table_name": name, "layer": "DWD", "description": "建表校验",
        "owner": "auto", "datasource_id": datasource["id"],
    })
    assert r.status_code in (200, 201), r.text

    body = r.json()
    assert body["table_name"] == name
    assert body["datasource_id"] == datasource["id"]
    assert body["layer"] == "DWD"

    api.delete(f"/tables/{body['id']}")


@pytest.mark.parametrize("payload,desc", [
    ({"layer": "ODS", "datasource_id": 1}, "缺少 table_name"),
    ({"table_name": "x"}, "缺少 datasource_id"),
])
def test_create_table_missing_field(api, payload, desc):
    r = api.post("/tables", payload)
    assert r.status_code == 422, f"{desc} 应返回 422，实际 {r.status_code}"


def test_get_table(api, table):
    r = api.get(f"/tables/{table['id']}")
    assert r.status_code == 200
    assert r.json()["table_name"] == table["table_name"]


def test_get_table_not_found(api):
    assert api.get("/tables/888888").status_code == 404


def test_update_table_layer(api, table):
    r = api.put(f"/tables/{table['id']}", {
        "table_name": table["table_name"], "layer": "DWS",
        "description": "层变更", "owner": "auto",
    })
    assert r.status_code == 200, r.text
    assert r.json()["layer"] == "DWS"


def test_create_column(api, table):
    name = unique("col")
    r = api.post(f"/tables/{table['id']}/columns", {
        "column_name": name, "data_type": "varchar",
        "is_sensitive": True, "description": "字段校验",
    })
    assert r.status_code in (200, 201), r.text

    body = r.json()
    assert body["column_name"] == name
    assert body["table_id"] == table["id"]
    assert body["is_sensitive"] is True


def test_create_column_missing_name(api, table):
    r = api.post(f"/tables/{table['id']}/columns", {"data_type": "int"})
    assert r.status_code == 422


def test_list_columns_contains_new(api, table, make_column):
    col = make_column()
    r = api.get(f"/tables/{table['id']}/columns")
    assert r.status_code == 200
    assert col["id"] in [c["id"] for c in r.json()]


def test_list_tables_contains_new(api, table):
    r = api.get("/tables")
    assert r.status_code == 200
    assert table["id"] in [t["id"] for t in r.json()]
