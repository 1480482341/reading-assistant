from app.db import init_db
from app.export import export_markdown, export_csv


def _seed(conn):
    conn.execute("INSERT INTO articles(url,title,text,status) VALUES('http://x','T','body','read')")
    conn.execute("INSERT INTO entries(kind,lemma) VALUES('word','albeit')")
    conn.execute(
        "INSERT INTO occurrences(entry_id,article_id,sentence,surface,gloss,grammar_role,why) "
        "VALUES(1,1,'albeit short','albeit','尽管','conj','让步')"
    )
    conn.commit()


def test_markdown_contains_word_and_frequency(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    _seed(conn)
    md = export_markdown(conn)
    assert "albeit" in md and "1" in md


def test_csv_has_header_and_row(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    _seed(conn)
    lines = export_csv(conn).strip().splitlines()
    assert lines[0] == "kind,lemma,count,gloss,sentence,article_url"
    assert "albeit" in lines[1]
