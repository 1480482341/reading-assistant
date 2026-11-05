import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.analyze import AnalysisError, Runner, analyze_snippet
from app.db import connect, init_db, insert_occurrence, upsert_entry
from app.export import export_csv, export_markdown
from app.sources import pick_today

MAX_SELECTION = 500
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


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

    @app.get("/api/articles/today")
    def articles_today():
        conn = open_db()
        try:
            return pick_today(conn)
        finally:
            conn.close()

    @app.get("/api/articles/{article_id}")
    def article_detail(article_id: int):
        conn = open_db()
        try:
            row = conn.execute(
                "SELECT id, title, source, topic, word_count, status, text "
                "FROM articles WHERE id = ?", (article_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="文章不存在")
            return dict(row)
        finally:
            conn.close()

    @app.get("/api/export")
    def export(format: str = "md"):
        conn = open_db()
        try:
            if format == "csv":
                return PlainTextResponse(export_csv(conn),
                                         media_type="text/csv; charset=utf-8")
            return PlainTextResponse(export_markdown(conn),
                                     media_type="text/markdown; charset=utf-8")
        finally:
            conn.close()

    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

        @app.get("/")
        def index():
            return FileResponse(WEB_DIR / "index.html")

    return app


app = create_app("data/library.db")
