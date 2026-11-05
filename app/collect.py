import logging
import re
import sqlite3
import threading
from datetime import date
from pathlib import Path

from app.analyze import Runner, analyze_article
from app.db import connect
from app.sources import fetch_bytes, fetch_items, ingest_article, seed_sources

logger = logging.getLogger(__name__)

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


def ingest_text(conn: sqlite3.Connection, title: str, text: str,
                topic: str = "manual") -> int:
    body = text.strip()
    if not body:
        raise ValueError("正文为空")
    row = conn.execute(
        "INSERT INTO articles(url, title, source, topic, published_at, text, "
        "word_count, status) VALUES(NULL, ?, 'manual', ?, ?, ?, ?, 'pending') RETURNING id",
        (title.strip() or "Untitled", topic, date.today().isoformat(),
         body, len(body.split())),
    ).fetchone()
    conn.commit()
    return row["id"]


def ingest_url(conn: sqlite3.Connection, url: str, topic: str = "manual") -> int | None:
    html = fetch_bytes(url).decode("utf-8", errors="replace")
    match = TITLE_RE.search(html)
    title = re.sub(r"\s+", " ", match.group(1)).strip() if match else url
    return ingest_article(conn, url, title, "manual", topic, html,
                          date.today().isoformat())


def ingest_pdf(conn: sqlite3.Connection, path: str, topic: str = "manual") -> int | None:
    from pypdf import PdfReader

    reader = PdfReader(path)
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    if not text.strip():
        return None
    return ingest_text(conn, Path(path).stem, text, topic)


def collect_new(conn: sqlite3.Connection) -> int:
    seed_sources(conn)
    added = 0
    known = {row["url"] for row in conn.execute("SELECT url FROM articles WHERE url IS NOT NULL")}
    sources = conn.execute(
        "SELECT name, feed_url, topic, link_pattern FROM sources WHERE enabled = 1"
    ).fetchall()
    for src in sources:
        try:
            feed = fetch_bytes(src["feed_url"])
        except Exception:
            logger.warning("抓取订阅源失败: %s", src["feed_url"], exc_info=True)
            continue
        for item in fetch_items(feed):
            if src["link_pattern"] and src["link_pattern"] not in item["link"]:
                continue
            if item["link"] in known:
                continue
            try:
                html = fetch_bytes(item["link"]).decode("utf-8", errors="replace")
                article_id = ingest_article(conn, item["link"], item["title"],
                                            src["name"], src["topic"], html,
                                            item["published"])
            except Exception:
                logger.warning("抓取文章失败: %s", item["link"], exc_info=True)
                continue
            known.add(item["link"])
            if article_id:
                added += 1
    return added


def analyze_pending(conn: sqlite3.Connection, runner: Runner | None = None) -> int:
    rows = conn.execute(
        "SELECT a.id FROM articles a LEFT JOIN analysis an ON an.article_id = a.id "
        "WHERE an.article_id IS NULL OR an.status IN ('failed', 'running') ORDER BY a.id"
    ).fetchall()
    done = 0
    for row in rows:
        try:
            analyze_article(conn, row["id"], runner=runner)
            done += 1
        except Exception:
            logger.warning("预分析失败: article %s", row["id"], exc_info=True)
    return done


def startup_job(db_path: str, runner: Runner | None = None) -> None:
    conn = connect(db_path)
    try:
        added = collect_new(conn)
        analysed = analyze_pending(conn, runner)
        logger.info("启动任务完成: 新增 %s 篇, 预分析 %s 篇", added, analysed)
    except Exception:
        logger.warning("启动任务失败", exc_info=True)
    finally:
        conn.close()


def start_startup_job(db_path: str, runner: Runner | None = None) -> threading.Thread:
    thread = threading.Thread(target=startup_job, args=(db_path, runner), daemon=True)
    thread.start()
    return thread
