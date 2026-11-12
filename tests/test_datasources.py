def test_create_datasource(client):
    r = client.post(
        "/datasources",
        json={"name": "ods_mysql", "type": "mysql", "host": "127.0.0.1", "owner": "tester"},
    )
    assert r.status_code in (200, 201)
    body = r.json()
    assert body["name"] == "ods_mysql"
    assert body["type"] == "mysql"
    assert isinstance(body["id"], int)

def test_get_datasource_by_id(client):
    r = client.post("/datasources", json={"name": "dw_pg", "type": "postgres", "host": "127.0.0.1"})
    ds_id = r.json()["id"]

    r = client.get(f"/datasources/{ds_id}")
    assert r.status_code == 200
    assert r.json()["name"] == "dw_pg"

def test_list_datasources(client):
    for n in ["ods_a", "ods_b", "ods_c"]:
        client.post("/datasources", json={"name": n, "type": "mysql"})

    r = client.get("/datasources?skip=0&limit=100")
    assert r.status_code == 200
    assert len(r.json()) == 3

def test_update_datasource(client):
    r = client.post("/datasources", json={"name": "ods_x", "type": "mysql", "owner": "old"})
    ds_id = r.json()["id"]

    r = client.put(f"/datasources/{ds_id}", json={"owner": "new"})
    assert r.status_code == 200
    body = r.json()
    assert body["owner"] == "new"
    assert body["name"] == "ods_x"

def test_delete_datasource(client):
    r = client.post("/datasources", json={"name": "ods_tmp", "type": "mysql"})
    ds_id = r.json()["id"]

    r = client.delete(f"/datasources/{ds_id}")
    assert r.status_code in (200, 204)

    r = client.get(f"/datasources/{ds_id}")
    assert r.status_code == 404

def test_get_missing_datasource(client):
    r = client.get("/datasources/9999")
    assert r.status_code == 404
