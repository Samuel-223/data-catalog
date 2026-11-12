import os
import pathlib

# 必须在导入 app 之前设置，让 app.db 读到测试库地址
os.environ["DATABASE_URL"] = "sqlite:///./test_db.sqlite3"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.main import app

TEST_DB = "test_db.sqlite3"

engine = create_engine(
    f"sqlite:///./{TEST_DB}",
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

@pytest.fixture(scope="session", autouse=True)
def _cleanup_db_file():
    yield
    pathlib.Path(TEST_DB).unlink(missing_ok=True)

@pytest.fixture
def client():
    """每个用例前重建表结构，用例之间互不污染"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

@pytest.fixture
def make_data(client):
    """一次造出 数据源 → 表 → 字段，返回三个 id"""

    def _make(name="ods_mysql", table="user_profile", column="phone"):
        r = client.post(
            "/datasources",
            json={"name": name, "type": "mysql", "host": "127.0.0.1", "owner": "tester"},
        )
        assert r.status_code in (200, 201), r.text
        ds_id = r.json()["id"]

        r = client.post(
            "/tables",
            json={"datasource_id": ds_id, "table_name": table, "layer": "ODS"},
        )
        assert r.status_code in (200, 201), r.text
        table_id = r.json()["id"]

        r = client.post(
            f"/tables/{table_id}/columns",
            json={"column_name": column, "data_type": "varchar(20)", "is_sensitive": True},
        )
        assert r.status_code in (200, 201), r.text
        col_id = r.json()["id"]

        return ds_id, table_id, col_id

    return _make
