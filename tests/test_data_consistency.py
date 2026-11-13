"""数据一致性校验：接口返回值与库表记录逐字段比对（零第三方依赖）。"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401  确保模型注册到 Base.metadata
from app.db import Base, get_db
from app.main import app

COMPARE_KEYS = ("id", "name", "type", "host", "owner")


@pytest.fixture()
def client_and_engine():
    """独立内存库，避免污染开发库；用例结束还原原有依赖覆盖。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client, engine
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override
        engine.dispose()


def _normalize_api(rows, keys=COMPARE_KEYS):
    out = []
    for row in rows:
        out.append(tuple(row.get(k) if row.get(k) is not None else None for k in keys))
    return sorted(out, key=lambda item: item[0])


def _normalize_db(conn, keys=COMPARE_KEYS):
    stmt = text("select " + ", ".join(keys) + " from datasource")
    rows = conn.execute(stmt).all()
    return sorted((tuple(r) for r in rows), key=lambda item: item[0])


def _assert_same(api_rows, db_rows, keys=COMPARE_KEYS):
    """逐字段比对，失败时指出第几行、哪个字段、两侧取值。"""
    assert len(api_rows) == len(db_rows), (
        f"记录数不一致：接口 {len(api_rows)} 行，库表 {len(db_rows)} 行"
    )
    for index, (api_row, db_row) in enumerate(zip(api_rows, db_rows)):
        for position, key in enumerate(keys):
            api_value, db_value = api_row[position], db_row[position]
            if api_value != db_value:
                raise AssertionError(
                    f"第 {index} 行字段 {key} 不一致：接口={api_value!r}，库表={db_value!r}"
                )


def test_list_matches_db(client_and_engine):
    client, engine = client_and_engine

    seeds = [
        {"name": "ods_mysql", "type": "mysql", "host": "127.0.0.1", "owner": "qa"},
        {"name": "dwd_order", "type": "postgres", "host": "10.0.0.8", "owner": "qa"},
        {"name": "ads_user", "type": "hive", "host": None, "owner": None},
    ]
    for item in seeds:
        resp = client.post("/datasources", json=item)
        assert resp.status_code in (200, 201), resp.text

    api_rows = _normalize_api(client.get("/datasources").json())
    with engine.connect() as conn:
        db_rows = _normalize_db(conn)

    assert len(api_rows) == len(seeds)
    _assert_same(api_rows, db_rows)


def test_detects_deviation(client_and_engine):
    """反向用例：人为篡改库表字段后，比对必须报错。"""
    client, engine = client_and_engine

    client.post("/datasources", json={"name": "ods_mysql", "type": "mysql", "owner": "qa"})
    api_rows = _normalize_api(client.get("/datasources").json())

    with engine.connect() as conn:
        conn.execute(text("update datasource set owner = 'tampered'"))
        conn.commit()
        db_rows = _normalize_db(conn)

    with pytest.raises(AssertionError) as exc:
        _assert_same(api_rows, db_rows)
    assert "owner" in str(exc.value)
