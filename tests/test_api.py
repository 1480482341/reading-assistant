from fastapi.testclient import TestClient

from app.db import init_db
from app.main import create_app

PAYLOAD = (
    '[{"term":"albeit","type":"word","gloss_zh":"尽管","grammar_role":"conj",'
    '"sentence":"albeit short","why":"让步"}]'
)


def _client(tmp_path, runner=None):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    conn.execute("INSERT INTO articles(url,title,text,status) VALUES('u','t','body','ready')")
    conn.execute(
        "INSERT INTO analysis(article_id,status,payload_json) VALUES(1,'ready',?)",
        (PAYLOAD,),
    )
    conn.commit()
    conn.close()
    return TestClient(create_app(db, runner=runner))


def test_lookup_hits_local_analysis(tmp_path):
    r = _client(tmp_path).get("/api/lookup", params={"article_id": 1, "text": "albeit"})
    assert r.status_code == 200
    assert r.json()["hit"] is True
    assert r.json()["item"]["gloss_zh"] == "尽管"


def test_lookup_overlong_selection_is_truncated(tmp_path):
    c = _client(tmp_path)
    r = c.get("/api/lookup", params={"article_id": 1, "text": "x" * 5000})
    assert r.status_code == 200
    assert r.json()["hit"] is False


def test_duplicate_confirmation_records_once(tmp_path):
    c = _client(tmp_path)
    body = {"article_id": 1, "text": "albeit", "sentence": "albeit short",
            "item": {"term": "albeit", "type": "word"}}
    assert c.post("/api/occurrences", json=body).json()["recorded"] is True
    assert c.post("/api/occurrences", json=body).json()["recorded"] is False


def test_miss_endpoint_returns_analysis(tmp_path):
    runner = lambda prompt: '[{"term":"scrutiny","type":"word","gloss_zh":"审查"}]'
    c = _client(tmp_path, runner=runner)
    r = c.post("/api/lookup/miss", json={"article_id": 1, "text": "scrutiny"})
    assert r.status_code == 200
    assert r.json()["item"]["gloss_zh"] == "审查"
