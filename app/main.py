import logging
import shutil
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.analyze import AnalysisError, Runner, analyze_snippet
from app.annotations import (
    add_annotation,
    delete_annotation,
    list_annotations,
    update_annotation_color,
)
from app.bookmarks import add_bookmark, delete_bookmark, list_bookmarks
from app.collect import ingest_pdf, ingest_text, ingest_url, start_startup_job
from app.db import connect, init_db, insert_occurrence, upsert_entry
from app.export import entry_rows, export_csv, export_markdown
from app.grammar import GRAMMAR_CATEGORIES
from app.library import library_rows
from app.lookup import cached_item, find_analysis_item, normalize_term, store_item
from app.metadata import INTEREST_TAGS
from app.review import due_queue, ensure_review, grade
from app.shelf import (
    add_to_shelf,
    history_rows,
    in_shelf,
    record_open,
    remove_from_shelf,
    shelf_rows,
)
from app.sources import pick_today

MAX_SELECTION = 500
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
APP_LOGGER_NAME = "app"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class IngestBody(BaseModel):
    text: str | None = None
    url: str | None = None
    pdf_path: str | None = None
    title: str | None = None
    topic: str | None = None


class LookupBody(BaseModel):
    article_id: int
    text: str = ""


class OccurrenceBody(BaseModel):
    article_id: int
    text: str = ""
    sentence: str = ""
    item: dict = Field(default_factory=dict)


class ReviewBody(BaseModel):
    known: bool = False


class AnnotationBody(BaseModel):
    para_index: int
    start_offset: int
    end_offset: int
    quote: str = ""
    color: str


class AnnotationColorBody(BaseModel):
    color: str


class BookmarkBody(BaseModel):
    para_index: int
    offset_ratio: float = 0
    label: str = ""


def configure_logging(level: int = logging.INFO) -> None:
    logger = logging.getLogger(APP_LOGGER_NAME)
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(handler)


def create_app(db_path: str, runner: Runner | None = None) -> FastAPI:
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        start_startup_job(db_path, runner)
        yield

    app = FastAPI(title="Reading Assistant", lifespan=lifespan)

    # Frontend files are edited in place on this machine, so the browser must
    # never reuse a cached page or asset: a stale app.js silently breaks new
    # UI that depends on it.
    pages = ("/", "/library", "/review", "/shelf")

    @app.middleware("http")
    async def disable_caching(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path in pages or path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    init_db(db_path).close()

    def open_db():
        return connect(db_path)

    @app.get("/api/health")
    def health():
        conn = open_db()
        try:
            conn.execute("SELECT 1").fetchone()
            db_status = "ok"
        except Exception:  # noqa: BLE001 - any DB failure means degraded
            db_status = "error"
        finally:
            conn.close()
        return {"claude_available": shutil.which("claude") is not None, "db": db_status}

    @app.post("/api/articles/ingest")
    def ingest(body: IngestBody):
        conn = open_db()
        try:
            text = body.text
            url = body.url
            pdf_path = body.pdf_path
            article_id: int | None
            if text is not None and text.strip():
                article_id = ingest_text(conn, body.title or "Untitled",
                                         text, body.topic or "manual")
            elif url is not None and url.strip():
                article_id = ingest_url(conn, url.strip(), body.topic or "manual")
            elif pdf_path is not None and pdf_path.strip():
                article_id = ingest_pdf(conn, pdf_path.strip(),
                                        body.topic or "manual")
            else:
                raise HTTPException(status_code=400, detail="需要 text、url 或 pdf_path")
            if article_id is None:
                raise HTTPException(status_code=422, detail="正文过短或为空，未入库")
            return {"article_id": article_id}
        finally:
            conn.close()

    @app.get("/api/lookup")
    def lookup(article_id: int, text: str):
        needle = normalize_term(text)[:MAX_SELECTION]
        conn = open_db()
        try:
            row = conn.execute(
                "SELECT payload_json FROM analysis WHERE article_id = ? AND status = 'ready'",
                (article_id,),
            ).fetchone()
            item = find_analysis_item(row["payload_json"] if row else None, needle)
            if item is None:
                item = cached_item(conn, article_id, needle)
            return {"hit": item is not None, "item": item}
        finally:
            conn.close()

    @app.post("/api/lookup/miss")
    def lookup_miss(body: LookupBody):
        article_id = body.article_id
        raw = body.text.strip()[:MAX_SELECTION]
        needle = normalize_term(raw)
        if not needle:
            raise HTTPException(status_code=400, detail="选区为空")
        conn = open_db()
        try:
            if conn.execute("SELECT 1 FROM articles WHERE id = ?", (article_id,)).fetchone() is None:
                raise HTTPException(status_code=404, detail="文章不存在")
            item = cached_item(conn, article_id, needle)
            if item is None:
                try:
                    item = analyze_snippet(conn, article_id, raw, runner=runner)
                except AnalysisError as exc:
                    raise HTTPException(status_code=503, detail=str(exc))
                store_item(conn, article_id, needle, item)
            return {"hit": False, "item": item}
        finally:
            conn.close()

    @app.post("/api/occurrences")
    def record_occurrence(body: OccurrenceBody):
        article_id = body.article_id
        text = body.text.strip()[:MAX_SELECTION]
        item = body.item or {}
        lemma = str(item.get("term") or text).lower()
        if not lemma:
            raise HTTPException(status_code=400, detail="词条为空")
        conn = open_db()
        try:
            kind = str(item.get("type", "word"))
            raw_category = str(item.get("grammar_category") or "").strip()
            category = (raw_category if kind == "grammar"
                        and raw_category in GRAMMAR_CATEGORIES else "")
            entry_id = upsert_entry(conn, kind, lemma, category)
            recorded = insert_occurrence(
                conn, entry_id, article_id,
                body.sentence, text,
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

    @app.get("/api/tags")
    def tags():
        return {"tags": list(INTEREST_TAGS)}

    @app.get("/api/articles/library")
    def article_library():
        conn = open_db()
        try:
            return library_rows(conn)
        finally:
            conn.close()

    @app.get("/api/articles/{article_id:int}/annotations")
    def article_annotations(article_id: int):
        conn = open_db()
        try:
            if conn.execute("SELECT 1 FROM articles WHERE id = ?",
                            (article_id,)).fetchone() is None:
                raise HTTPException(status_code=404, detail="文章不存在")
            return list_annotations(conn, article_id)
        finally:
            conn.close()

    @app.post("/api/articles/{article_id:int}/annotations")
    def create_annotation(article_id: int, body: AnnotationBody):
        conn = open_db()
        try:
            if conn.execute("SELECT 1 FROM articles WHERE id = ?",
                            (article_id,)).fetchone() is None:
                raise HTTPException(status_code=404, detail="文章不存在")
            try:
                new_id = add_annotation(
                    conn, article_id, body.para_index, body.start_offset,
                    body.end_offset, body.quote, body.color)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            row = conn.execute(
                "SELECT id, para_index, start_offset, end_offset, quote, color "
                "FROM annotations WHERE id = ?", (new_id,),
            ).fetchone()
            return dict(row)
        finally:
            conn.close()

    @app.patch("/api/annotations/{annotation_id:int}")
    def patch_annotation(annotation_id: int, body: AnnotationColorBody):
        conn = open_db()
        try:
            try:
                updated = update_annotation_color(conn, annotation_id, body.color)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            if not updated:
                raise HTTPException(status_code=404, detail="标注不存在")
            return {"ok": True}
        finally:
            conn.close()

    @app.delete("/api/annotations/{annotation_id:int}")
    def remove_annotation(annotation_id: int):
        conn = open_db()
        try:
            if not delete_annotation(conn, annotation_id):
                raise HTTPException(status_code=404, detail="标注不存在")
            return {"ok": True}
        finally:
            conn.close()

    @app.get("/api/articles/{article_id:int}/bookmarks")
    def article_bookmarks(article_id: int):
        conn = open_db()
        try:
            if conn.execute("SELECT 1 FROM articles WHERE id = ?",
                            (article_id,)).fetchone() is None:
                raise HTTPException(status_code=404, detail="文章不存在")
            return list_bookmarks(conn, article_id)
        finally:
            conn.close()

    @app.post("/api/articles/{article_id:int}/bookmarks")
    def create_bookmark(article_id: int, body: BookmarkBody):
        conn = open_db()
        try:
            if conn.execute("SELECT 1 FROM articles WHERE id = ?",
                            (article_id,)).fetchone() is None:
                raise HTTPException(status_code=404, detail="文章不存在")
            try:
                new_id = add_bookmark(conn, article_id, body.para_index,
                                      body.offset_ratio, body.label)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            row = conn.execute(
                "SELECT id, para_index, offset_ratio, label, created_at "
                "FROM bookmarks WHERE id = ?", (new_id,),
            ).fetchone()
            return dict(row)
        finally:
            conn.close()

    @app.delete("/api/bookmarks/{bookmark_id:int}")
    def remove_bookmark(bookmark_id: int):
        conn = open_db()
        try:
            if not delete_bookmark(conn, bookmark_id):
                raise HTTPException(status_code=404, detail="书签不存在")
            return {"ok": True}
        finally:
            conn.close()

    @app.get("/api/shelf")
    def shelf_list():
        conn = open_db()
        try:
            return shelf_rows(conn)
        finally:
            conn.close()

    @app.post("/api/shelf/{article_id:int}")
    def shelf_add(article_id: int):
        conn = open_db()
        try:
            if conn.execute("SELECT 1 FROM articles WHERE id = ?",
                            (article_id,)).fetchone() is None:
                raise HTTPException(status_code=404, detail="文章不存在")
            add_to_shelf(conn, article_id,
                         datetime.now().isoformat(timespec="seconds"))
            return {"ok": True}
        finally:
            conn.close()

    @app.delete("/api/shelf/{article_id:int}")
    def shelf_remove(article_id: int):
        conn = open_db()
        try:
            if not remove_from_shelf(conn, article_id):
                raise HTTPException(status_code=404, detail="文章不在书架")
            return {"ok": True}
        finally:
            conn.close()

    @app.get("/api/history")
    def history_list():
        conn = open_db()
        try:
            return history_rows(conn)
        finally:
            conn.close()

    @app.get("/api/articles/{article_id:int}")
    def article_detail(article_id: int):
        conn = open_db()
        try:
            row = conn.execute(
                "SELECT id, title, title_zh, source, topic, word_count, status, text "
                "FROM articles WHERE id = ?", (article_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="文章不存在")
            return {**dict(row),
                    "in_shelf": in_shelf(conn, article_id),
                    "annotations": list_annotations(conn, article_id),
                    "bookmarks": list_bookmarks(conn, article_id)}
        finally:
            conn.close()

    @app.get("/api/articles/{article_id}/marks")
    def article_marks(article_id: int):
        conn = open_db()
        try:
            rows = conn.execute(
                "SELECT e.kind, e.lemma, e.category, o.gloss, o.grammar_role, o.why "
                "FROM occurrences o JOIN entries e ON e.id = o.entry_id "
                "WHERE o.article_id = ?",
                (article_id,),
            ).fetchall()
            occurrences = []
            grammar = []
            for row in rows:
                item = {
                    "term": row["lemma"],
                    "gloss_zh": row["gloss"],
                    "grammar_role": row["grammar_role"],
                    "why": row["why"],
                    "category": row["category"],
                }
                if row["kind"] == "grammar":
                    grammar.append(item)
                else:
                    occurrences.append(item)
            return {"occurrences": occurrences, "grammar": grammar}
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

    @app.post("/api/articles/{article_id}/open")
    def article_open(article_id: int):
        conn = open_db()
        try:
            if conn.execute("SELECT 1 FROM articles WHERE id = ?",
                            (article_id,)).fetchone() is None:
                raise HTTPException(status_code=404, detail="文章不存在")
            record_open(conn, article_id,
                        datetime.now().isoformat(timespec="seconds"))
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
    def review_grade(entry_id: int, body: ReviewBody):
        conn = open_db()
        try:
            if conn.execute("SELECT 1 FROM entries WHERE id = ?", (entry_id,)).fetchone() is None:
                raise HTTPException(status_code=404, detail="词条不存在")
            grade(conn, entry_id, body.known, date.today().isoformat())
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

        @app.get("/library")
        def library_page():
            return FileResponse(WEB_DIR / "library.html")

        @app.get("/shelf")
        def shelf_page():
            return FileResponse(WEB_DIR / "shelf.html")

    return app


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "library.db"
app = create_app(str(DB_PATH))
