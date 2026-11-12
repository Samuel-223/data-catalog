def test_link_and_trace_upstream(client, make_data):
    ds_id, table_id, col_up = make_data(name="ods_src", table="src_table", column="phone")

    r = client.post(
        "/tables",
        json={"datasource_id": ds_id, "table_name": "dwd_table", "layer": "DWD"},
    )
    dwd_table_id = r.json()["id"]
    r = client.post(
        f"/tables/{dwd_table_id}/columns",
        json={"column_name": "mobile_masked", "data_type": "varchar(20)"},
    )
    col_down = r.json()["id"]

    r = client.post(
        "/lineage",
        json={"column_id": col_down, "upstream_column_id": col_up},
    )
    assert r.status_code in (200, 201)
    assert r.json()["upstream_column_id"] == col_up

    r = client.get(f"/lineage/{col_down}/upstream")
    assert r.status_code == 200
    up = r.json()["upstream"]
    assert len(up) == 1
    assert up[0]["column_id"] == col_up
    assert up[0]["column_name"] == "phone"

def test_trace_downstream(client, make_data):
    ds_id, table_id, col_up = make_data(name="ods_src2", table="src_table2", column="phone")

    r = client.post("/tables", json={"datasource_id": ds_id, "table_name": "dwd2", "layer": "DWD"})
    dwd_table_id = r.json()["id"]
    r = client.post(
        f"/tables/{dwd_table_id}/columns",
        json={"column_name": "mobile_masked", "data_type": "varchar(20)"},
    )
    col_down = r.json()["id"]

    client.post("/lineage", json={"column_id": col_down, "upstream_column_id": col_up})

    r = client.get(f"/lineage/{col_up}/downstream")
    assert r.status_code == 200
    down = r.json()["downstream"]
    assert len(down) == 1
    assert down[0]["column_id"] == col_down

def test_lineage_self_reference_rejected(client, make_data):
    _, _, col_id = make_data()
    r = client.post("/lineage", json={"column_id": col_id, "upstream_column_id": col_id})
    assert r.status_code == 400

def test_lineage_missing_column(client, make_data):
    _, _, col_id = make_data()
    r = client.post("/lineage", json={"column_id": col_id, "upstream_column_id": 9999})
    assert r.status_code == 404
