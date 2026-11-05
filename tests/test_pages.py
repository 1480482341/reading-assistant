from fastapi.testclient import TestClient

from app.db import init_db
from app.main import create_app


def test_reading_page_serves(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    r = TestClient(create_app(db)).get("/")
    assert r.status_code == 200
    assert "article-body" in r.text


def test_today_endpoint_on_empty_library(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    r = TestClient(create_app(db)).get("/api/articles/today")
    assert r.status_code == 200 and r.json() == []


def test_static_assets_served(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db).close()
    r = TestClient(create_app(db)).get("/static/style.css")
    assert r.status_code == 200
    assert "--accent" in r.text
