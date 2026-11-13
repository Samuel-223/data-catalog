import pytest

from conftest import extract_ids, unique


@pytest.fixture
def column_chain(make_column):
    """建一条最小血缘：root（上游）→ child（下游）。"""
    root = make_column(name=unique("root"))
    child = make_column(name=unique("child"))
    return root, child


def test_create_lineage(api, column_chain):
    root, child = column_chain
    r = api.post("/lineage", {"column_id": child["id"], "upstream_column_id": root["id"]})
    assert r.status_code in (200, 201), r.text


def test_upstream_returns_parent(api, column_chain):
    root, child = column_chain
    api.post("/lineage", {"column_id": child["id"], "upstream_column_id": root["id"]})

    r = api.get(f"/lineage/{child['id']}/upstream")
    assert r.status_code == 200
    assert root["id"] in extract_ids(r.json()), f"上游链路未包含父字段：{r.text}"


def test_downstream_returns_child(api, column_chain):
    root, child = column_chain
    api.post("/lineage", {"column_id": child["id"], "upstream_column_id": root["id"]})

    r = api.get(f"/lineage/{root['id']}/downstream")
    assert r.status_code == 200
    assert child["id"] in extract_ids(r.json()), f"下游影响面未包含子字段：{r.text}"


def test_upstream_of_root_is_empty(api, column_chain):
    root, _ = column_chain
    r = api.get(f"/lineage/{root['id']}/upstream")
    assert r.status_code == 200
    assert extract_ids(r.json()) == [], "根字段不应有上游"


@pytest.mark.parametrize("payload,desc", [
    ({"column_id": 1}, "缺少 upstream_column_id"),
    ({"upstream_column_id": 1}, "缺少 column_id"),
])
def test_create_lineage_missing_field(api, payload, desc):
    r = api.post("/lineage", payload)
    assert r.status_code == 422, f"{desc} 应返回 422，实际 {r.status_code}"


def test_lineage_nonexistent_column(api):
    r = api.get("/lineage/777777/upstream")
    assert r.status_code in (200, 404), f"不存在的字段应 404 或返回空，实际 {r.status_code}"
