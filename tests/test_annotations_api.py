from fastapi.testclient import TestClient

from app.db import init_db
from app.main import create_app

TEXT = "First paragraph here.\n\nSecond paragraph."


def _client(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("INSERT INTO articles(id,url,title,text,status) "
                 "VALUES(1,'u','t',?,'ready')", (TEXT,))
    conn.commit()
    conn.close()
    return TestClient(create_app(db))


def test_create_and_list_annotation(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/articles/1/annotations", json={
        "para_index": 0, "start_offset": 0, "end_offset": 5,
        "quote": "First", "color": "red"})
    assert r.status_code == 200
    rows = c.get("/api/articles/1/annotations").json()
    assert len(rows) == 1 and rows[0]["color"] == "red"


def test_create_returns_full_row(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/articles/1/annotations", json={
        "para_index": 0, "start_offset": 0, "end_offset": 5,
        "quote": "First", "color": "red"})
    body = r.json()
    assert body["id"] == 1
    assert body["para_index"] == 0
    assert body["start_offset"] == 0
    assert body["end_offset"] == 5
    assert body["quote"] == "First"
    assert body["color"] == "red"


def test_invalid_color_returns_422(tmp_path):
    r = _client(tmp_path).post("/api/articles/1/annotations", json={
        "para_index": 0, "start_offset": 0, "end_offset": 5,
        "quote": "First", "color": "purple"})
    assert r.status_code == 422


def test_unknown_article_returns_404(tmp_path):
    r = _client(tmp_path).post("/api/articles/99/annotations", json={
        "para_index": 0, "start_offset": 0, "end_offset": 5,
        "quote": "First", "color": "red"})
    assert r.status_code == 404


def test_list_unknown_article_returns_404(tmp_path):
    assert _client(tmp_path).get("/api/articles/99/annotations").status_code == 404


def test_patch_color_and_delete(tmp_path):
    c = _client(tmp_path)
    aid = c.post("/api/articles/1/annotations", json={
        "para_index": 0, "start_offset": 0, "end_offset": 5,
        "quote": "First", "color": "red"}).json()["id"]
    assert c.patch(f"/api/annotations/{aid}", json={"color": "green"}).status_code == 200
    assert c.get("/api/articles/1/annotations").json()[0]["color"] == "green"
    assert c.delete(f"/api/annotations/{aid}").status_code == 200
    assert c.get("/api/articles/1/annotations").json() == []


def test_delete_missing_annotation_returns_404(tmp_path):
    assert _client(tmp_path).delete("/api/annotations/999").status_code == 404
