"""Controlled grammar vocabulary shared by the analyser and the database."""
import sqlite3

FALLBACK_CATEGORY = "其他"

GRAMMAR_CATEGORIES = (
    "一般现在时", "一般过去时", "一般将来时", "现在进行时", "过去进行时",
    "现在完成时", "过去完成时", "将来完成时", "现在完成进行时",
    "被动语态", "情态动词", "虚拟语气",
    "定语从句", "状语从句", "宾语从句", "主语从句", "表语从句", "同位语从句",
    "不定式", "动名词", "现在分词", "过去分词", "独立主格",
    "倒装句", "强调句", "省略句", "疑问句", "祈使句", "There be 句型",
    "比较结构", "平行结构", "插入语", "同位语", "名词短语", "介词短语",
    "形容词短语", "副词短语", "短语动词", "固定搭配", "冠词用法", "连词用法",
    "关系代词", "关系副词", "非限定动词", FALLBACK_CATEGORY,
)


def normalize_grammar_category(raw: str) -> str:
    """Return the canonical category, falling back to 其他 for anything else."""
    label = str(raw or "").strip()
    return label if label in GRAMMAR_CATEGORIES else FALLBACK_CATEGORY


def seed_grammar_categories(conn: sqlite3.Connection) -> None:
    """Insert every canonical category once, leaving existing rows untouched."""
    conn.executemany(
        "INSERT OR IGNORE INTO grammar_terms(label, status) VALUES(?, 'active')",
        [(label,) for label in GRAMMAR_CATEGORIES],
    )
    conn.commit()
