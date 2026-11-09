import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.analyze import analyze_article
from app.db import init_db
from app.main import create_app
from app.sources import ingest_article

FAKE = (
    '[{"term":"albeit","type":"word","gloss_zh":"尽管","grammar_role":"conj",'
    '"sentence":"albeit short","why":"让步"}]'
)


def _fake(prompt):
    items = json.loads(FAKE)
    items += [{"term": f"w{i}", "type": "word"} for i in range(59)]
    return json.dumps(items, ensure_ascii=False)


def test_ingest_analyze_lookup_confirm(tmp_path):
    db = str(tmp_path / "t.db")
    conn = init_db(db)
    html = (Path(__file__).parent / "fixtures" / "sample_article.html").read_text(
        encoding="utf-8")
    aid = ingest_article(conn, "u9", "T", "Quanta", "tech", html, "2026-11-05")
    assert aid is not None
    analyze_article(conn, aid, runner=_fake)
    conn.close()

    c = TestClient(create_app(db))
    hit = c.get("/api/lookup", params={"article_id": aid, "text": "albeit"}).json()
    assert hit["hit"] is True

    body = {"article_id": aid, "text": "albeit", "sentence": "albeit short",
            "item": {"term": "albeit", "type": "word"}}
    assert c.post("/api/occurrences", json=body).json()["recorded"] is True

    today = c.get("/api/articles/today").json()
    assert len(today) == 1
