import json

from fastapi import FastAPI, HTTPException

from app.analyze import AnalysisError, Runner, analyze_snippet
from app.db import connect, init_db, insert_occurrence, upsert_entry

MAX_SELECTION = 500


def create_app(db_path: str, runner: Runner | None = None) -> FastAPI:
    app = FastAPI(title="Reading Assistant")
    init_db(db_path).close()

    def open_db():
        return connect(db_path)

    @app.get("/api/lookup")
    def lookup(article_id: int, text: str):
        needle = text.strip()[:MAX_SELECTION]
        conn = open_db()
        try:
            row = conn.execute(
                "SELECT payload_json FROM analysis WHERE article_id = ? AND status = 'ready'",
                (article_id,),
            ).fetchone()
            if row and needle and row["payload_json"]:
                for item in json.loads(row["payload_json"]):
                    if str(item.get("term", "")).lower() == needle.lower():
                        return {"hit": True, "item": item}
            return {"hit": False, "item": None}
        finally:
            conn.close()

    @app.post("/api/lookup/miss")
    def lookup_miss(body: dict):
        article_id = int(body["article_id"])
        needle = str(body.get("text", "")).strip()[:MAX_SELECTION]
        if not needle:
            raise HTTPException(status_code=400, detail="选区为空")
        conn = open_db()
        try:
            item = analyze_snippet(conn, article_id, needle, runner=runner)
            return {"hit": False, "item": item}
        except AnalysisError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        finally:
            conn.close()

    @app.post("/api/occurrences")
    def record_occurrence(body: dict):
        article_id = int(body["article_id"])
        text = str(body.get("text", "")).strip()[:MAX_SELECTION]
        item = body.get("item") or {}
        lemma = str(item.get("term") or text).lower()
        if not lemma:
            raise HTTPException(status_code=400, detail="词条为空")
        conn = open_db()
        try:
            entry_id = upsert_entry(conn, str(item.get("type", "word")), lemma)
            recorded = insert_occurrence(
                conn, entry_id, article_id,
                str(body.get("sentence", "")), text,
                str(item.get("gloss_zh", "")),
                str(item.get("grammar_role", "")),
                str(item.get("why", "")),
            )
            return {"recorded": recorded, "entry_id": entry_id}
        finally:
            conn.close()

    return app


app = create_app("data/library.db")
