import csv
import io
import sqlite3

QUERY = """
SELECT e.kind, e.lemma, COUNT(o.id) AS count,
       COALESCE(latest.gloss, '') AS gloss,
       COALESCE(latest.sentence, '') AS sentence,
       COALESCE(a.url, '') AS article_url
FROM entries e
LEFT JOIN occurrences o ON o.entry_id = e.id
LEFT JOIN occurrences latest ON latest.id =
    (SELECT MAX(id) FROM occurrences WHERE entry_id = e.id)
LEFT JOIN articles a ON a.id = latest.article_id
GROUP BY e.id
ORDER BY count DESC, e.lemma ASC
"""

HEADER = ["kind", "lemma", "count", "gloss", "sentence", "article_url"]


def entry_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(QUERY).fetchall()


def export_csv(conn: sqlite3.Connection) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(HEADER)
    for row in entry_rows(conn):
        writer.writerow([row[k] for k in HEADER])
    return buf.getvalue()


def export_markdown(conn: sqlite3.Connection) -> str:
    lines = ["# Vocabulary", "", "| Kind | Lemma | Count | Gloss | Sentence | Source |",
             "|---|---|---|---|---|---|"]
    for row in entry_rows(conn):
        sentence = str(row["sentence"]).replace("|", "\\|")
        lines.append(
            f"| {row['kind']} | {row['lemma']} | {row['count']} | "
            f"{row['gloss']} | {sentence} | {row['article_url']} |"
        )
    return "\n".join(lines) + "\n"
