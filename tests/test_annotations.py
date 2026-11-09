import pytest

from app.annotations import (add_annotation, delete_annotation, list_annotations,
                             split_paragraphs, update_annotation_color)
from app.db import init_db

TEXT = "First paragraph here.\n\nSecond paragraph.\n\n\nThird one."


def _conn(tmp_path):
    conn = init_db(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO articles(id,url,title,text) VALUES(1,'u','t',?)", (TEXT,))
    conn.commit()
    return conn


def test_split_paragraphs_drops_blank_lines():
    assert split_paragraphs(TEXT) == [
        "First paragraph here.", "Second paragraph.", "Third one."]


def test_split_paragraphs_ignores_surrounding_whitespace():
    assert split_paragraphs("\n\n  a  \n\n  b \n\n") == ["a", "b"]


def test_add_and_list_roundtrip(tmp_path):
    conn = _conn(tmp_path)
    aid = add_annotation(conn, 1, 1, 0, 6, "Second", "green")
    rows = list_annotations(conn, 1)
    assert len(rows) == 1
    assert rows[0]["id"] == aid
    assert rows[0]["color"] == "green"
    assert rows[0]["quote"] == "Second"


def test_overlapping_annotation_replaces_previous(tmp_path):
    conn = _conn(tmp_path)
    add_annotation(conn, 1, 0, 0, 10, "First para", "red")
    add_annotation(conn, 1, 0, 5, 15, "paragraph", "yellow")
    rows = list_annotations(conn, 1)
    assert len(rows) == 1
    assert rows[0]["color"] == "yellow"


def test_adjacent_annotations_are_both_kept(tmp_path):
    conn = _conn(tmp_path)
    add_annotation(conn, 1, 0, 0, 5, "First", "red")
    add_annotation(conn, 1, 0, 5, 10, " para", "green")
    assert len(list_annotations(conn, 1)) == 2


def test_annotations_in_different_paragraphs_do_not_collide(tmp_path):
    conn = _conn(tmp_path)
    add_annotation(conn, 1, 0, 0, 5, "First", "red")
    add_annotation(conn, 1, 1, 0, 6, "Second", "red")
    assert len(list_annotations(conn, 1)) == 2


def test_invalid_color_rejected(tmp_path):
    with pytest.raises(ValueError):
        add_annotation(_conn(tmp_path), 1, 0, 0, 5, "First", "purple")


def test_invalid_range_rejected(tmp_path):
    with pytest.raises(ValueError):
        add_annotation(_conn(tmp_path), 1, 0, 5, 5, "", "red")


def test_paragraph_index_out_of_range_rejected(tmp_path):
    with pytest.raises(ValueError):
        add_annotation(_conn(tmp_path), 1, 9, 0, 5, "x", "red")


def test_end_offset_past_paragraph_end_rejected(tmp_path):
    with pytest.raises(ValueError):
        add_annotation(_conn(tmp_path), 1, 0, 0, 999, "x", "red")


def test_end_offset_equal_to_paragraph_length_accepted(tmp_path):
    conn = _conn(tmp_path)
    para = "First paragraph here."
    add_annotation(conn, 1, 0, 0, len(para), para, "red")
    assert len(list_annotations(conn, 1)) == 1


def test_quote_mismatch_is_dropped_on_read(tmp_path):
    conn = _conn(tmp_path)
    add_annotation(conn, 1, 0, 0, 9, "NOPE", "red")
    assert list_annotations(conn, 1) == []


def test_stale_annotation_is_deleted_on_read(tmp_path):
    conn = _conn(tmp_path)
    add_annotation(conn, 1, 0, 0, 9, "NOPE", "red")
    list_annotations(conn, 1)
    remaining = conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
    assert remaining == 0


def test_update_color_and_delete(tmp_path):
    conn = _conn(tmp_path)
    aid = add_annotation(conn, 1, 0, 0, 5, "First", "red")
    assert update_annotation_color(conn, aid, "yellow") is True
    assert list_annotations(conn, 1)[0]["color"] == "yellow"
    assert delete_annotation(conn, aid) is True
    assert list_annotations(conn, 1) == []
    assert delete_annotation(conn, aid) is False
