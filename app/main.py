import json
import shutil
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.analyze import AnalysisError, Runner, analyze_snippet
from app.collect import ingest_pdf, ingest_text, ingest_url, start_startup_job
from app.db import connect, init_db, insert_occurrence, upsert_entry
from app.export import entry_rows, export_csv, export_markdown
from app.library import library_rows
from app.review import due_queue, ensure_review, grade
from app.sources import pick_today

MAX_SELECTION = 500
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app(db_path: str, runner: Runner | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        start_startup_job(db_path, runner)
        yield

    app = FastAPI(title="Reading Assistant", lifespan=lifespan)
    init_db(db_path).close()

    def open_db():
        return connect(db_path)

    @app.get("/api/health")
    def health():
        conn = open_db()
        try:
            conn.execute("SELECT 1").fetchone()
            db_status = "ok"
        except Exception:
            db_status = "error"
        finally:
            conn.close()
        return {"claude_available": shutil.which("claude") is not None, "db": db_status}

    @app.post("/api/articles/ingest")
    def ingest(body: dict):
        conn = open_db()
        try:
            if str(body.get("text") or "").strip():
                article_id = ingest_text(conn, str(body.get("title") or "Untitled"),
                                         str(body["text"]), str(body.get("topic") or "manual"))
            elif str(body.get("url") or "").strip():
                article_id = ingest_url(conn, str(body["url"]).strip(),
                                        str(body.get("topic") or "manual"))
            elif str(body.get("pdf_path") or "").strip():
                article_id = ingest_pdf(conn, str(body["pdf_path"]).strip(),
                                        str(body.get("topic") or "manual"))
            else:
                raise HTTPException(status_code=400, detail="需要 text、url 或 pdf_path")
            if article_id is None:
                raise HTTPException(status_code=422, detail="正文过短或为空，未入库")
            return {"article_id": article_id}
        finally:
            conn.close()

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
            if recorded:
                ensure_review(conn, entry_id, date.today().isoformat())
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

    @app.get("/api/articles/library")
    def article_library():
        conn = open_db()
        try:
            return library_rows(conn)
        finally:
            conn.close()

    @app.get("/api/articles/{article_id}")
    def article_detail(article_id: int):
        conn = open_db()
        try:
            row = conn.execute(
                "SELECT id, title, title_zh, source, topic, word_count, status, text "
                "FROM articles WHERE id = ?", (article_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="文章不存在")
            return dict(row)
        finally:
            conn.close()

    @app.post("/api/articles/{article_id}/read")
    def mark_read(article_id: int):
        conn = open_db()
        try:
            cur = conn.execute("UPDATE articles SET status='read' WHERE id=?", (article_id,))
            conn.commit()
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="文章不存在")
            return {"ok": True}
        finally:
            conn.close()

    @app.get("/api/entries")
    def entries():
        conn = open_db()
        try:
            return [dict(row) for row in entry_rows(conn)]
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

    @app.get("/api/review/queue")
    def review_queue():
        conn = open_db()
        try:
            return [dict(r) for r in due_queue(conn, date.today().isoformat())]
        finally:
            conn.close()

    @app.post("/api/review/{entry_id}")
    def review_grade(entry_id: int, body: dict):
        conn = open_db()
        try:
            if conn.execute("SELECT 1 FROM entries WHERE id = ?", (entry_id,)).fetchone() is None:
                raise HTTPException(status_code=404, detail="词条不存在")
            grade(conn, entry_id, bool(body.get("known")), date.today().isoformat())
            return {"ok": True}
        finally:
            conn.close()

    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

        @app.get("/")
        def index():
            return FileResponse(WEB_DIR / "index.html")

        @app.get("/review")
        def review_page():
            return FileResponse(WEB_DIR / "review.html")

    return app


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "library.db"
app = create_app(str(DB_PATH))
