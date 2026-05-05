import json
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

import psycopg2
import psycopg2.extras
from dotenv import find_dotenv, load_dotenv

_dotenv = find_dotenv(usecwd=True)
load_dotenv(_dotenv if _dotenv else None)

# Kept for call-site compatibility; value is ignored — connection comes from env vars.
DEFAULT_DB_PATH = "postgresql"

RELEVANCE_THRESHOLD = 7

INITIAL_KEYWORDS = [
    "Verwaltung",
    "Präsidialdepartement",
    "Parlament",
    "Conradin Cramer",
]
INITIAL_SOURCES = [
    {"name": "SRF News",                "url": "https://www.srf.ch/news",   "rss_url": "https://www.srf.ch/news/bnf/rss/1646",                                          "active": False, "local": False},
    {"name": "SRF Schweiz",             "url": "https://www.srf.ch/news",   "rss_url": "https://www.srf.ch/news/bnf/rss/1890",                                          "active": False, "local": False},
    {"name": "SRF Regionaljournal Basel","url": "https://www.srf.ch/audio", "rss_url": "https://www.srf.ch/audio/regionaljournal-basel-baselland",                      "active": False, "local": True},
    {"name": "Basler Zeitung (BaZ)",    "url": "https://www.bazonline.ch",  "rss_url": "https://partner-feeds.publishing.tamedia.ch/rss/bazonline/basel",               "active": True,  "local": False},
    {"name": "BZ Basel",                "url": "https://www.bzbasel.ch",    "rss_url": "https://www.bzbasel.ch/rss",                                                    "active": True,  "local": False},
    {"name": "BZ Basel - Region Basel", "url": "https://www.bzbasel.ch",    "rss_url": "https://www.bzbasel.ch/basel.rss",                                              "active": False, "local": True},
    {"name": "Bajour",                  "url": "https://bajour.ch",         "rss_url": "https://bajour.ch/api/rss-feed",                                                "active": True,  "local": True},
    {"name": "Blick",                   "url": "https://blick.ch",          "rss_url": "https://www.blick.ch/schweiz/rss.xml",                                          "active": False, "local": False},
    {"name": "20 Minuten",              "url": "https://www.20min.ch/",     "rss_url": "https://partner-feeds.beta.20min.ch/rss/20minuten",                             "active": True,  "local": False},
]


def _get_dsn() -> str:
    """Return the PostgreSQL DSN to use.

    Priority:
    1. DATABASE_URL   — set automatically by Heroku on the dyno (production).
    2. HEROKU_DATABASE_URL + USE_PRODUCTION_DB=1 — explicit local override to
       test against the cloud DB.
    3. DB_* env vars  — local PostgreSQL (default for development).
    """
    # Heroku dyno: platform sets DATABASE_URL automatically
    heroku_auto = os.getenv("DATABASE_URL")
    if heroku_auto:
        return heroku_auto.replace("postgres://", "postgresql://", 1)

    # Local override: developer explicitly opts into the cloud DB
    if os.getenv("USE_PRODUCTION_DB") == "1":
        url = os.getenv("HEROKU_DATABASE_URL", "")
        if url:
            return url.replace("postgres://", "postgresql://", 1)

    # Local development database
    host     = os.getenv("PRESSREVIEW_DB_HOST")     or os.getenv("DB_HOST", "localhost")
    port     = os.getenv("PRESSREVIEW_DB_PORT")     or os.getenv("DB_PORT", "5432")
    name     = os.getenv("PRESSREVIEW_DB_NAME")     or os.getenv("DB_NAME", "postgres")
    user     = os.getenv("PRESSREVIEW_DB_USER")     or os.getenv("DB_USER", "postgres")
    password = os.getenv("PRESSREVIEW_DB_PASSWORD") or os.getenv("DB_PASSWORD", "")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


def _get_schema() -> str:
    return os.getenv("PRESSREVIEW_DB_SCHEMA", "pressreview")


class _Conn:
    """Thin wrapper around a psycopg2 connection with a sqlite3-compatible execute() API."""

    def __init__(self, raw: psycopg2.extensions.connection) -> None:
        self._raw = raw
        self._cur = raw.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    @property
    def raw(self) -> psycopg2.extensions.connection:
        """Underlying psycopg2 connection — used by pd.read_sql_query."""
        return self._raw

    def execute(self, sql: str, params=None):
        self._cur.execute(sql, params)
        return self._cur

    def executemany(self, sql: str, params_list):
        self._cur.executemany(sql, params_list)
        return self._cur


@contextmanager
def db_connection(db_path: str = DEFAULT_DB_PATH):  # db_path unused, kept for API compat
    schema = _get_schema()
    raw = psycopg2.connect(_get_dsn(), options=f"-c search_path={schema}")
    conn = _Conn(raw)
    try:
        yield conn
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    schema = _get_schema()
    with db_connection(db_path) as conn:
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                id          SERIAL PRIMARY KEY,
                name        TEXT NOT NULL,
                url         TEXT,
                rss_url     TEXT UNIQUE NOT NULL,
                active      BOOLEAN NOT NULL DEFAULT TRUE,
                local       BOOLEAN NOT NULL DEFAULT FALSE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS keywords (
                id          SERIAL PRIMARY KEY,
                keyword     TEXT UNIQUE NOT NULL,
                active      BOOLEAN NOT NULL DEFAULT TRUE,
                required    BOOLEAN NOT NULL DEFAULT FALSE,
                created_at  TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
                id          SERIAL PRIMARY KEY,
                email       TEXT UNIQUE NOT NULL,
                active      BOOLEAN NOT NULL DEFAULT TRUE,
                added_at    TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id                  SERIAL PRIMARY KEY,
                source_id           INTEGER NOT NULL REFERENCES sources(id),
                title               TEXT NOT NULL,
                summary             TEXT,
                link                TEXT UNIQUE NOT NULL,
                published_at        TIMESTAMP,
                harvested_at        TIMESTAMP NOT NULL DEFAULT NOW(),
                matched_keywords    TEXT,
                daily_digest_sent   BOOLEAN NOT NULL DEFAULT FALSE,
                weekly_digest_sent  BOOLEAN NOT NULL DEFAULT FALSE,
                relevance_score     SMALLINT,
                relevance_reason    TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS harvest_log (
                id                  SERIAL PRIMARY KEY,
                run_at              TIMESTAMP NOT NULL,
                sources_checked     INTEGER NOT NULL,
                articles_new        INTEGER NOT NULL,
                articles_skipped    INTEGER NOT NULL,
                errors              TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS mail_log (
                id          SERIAL PRIMARY KEY,
                sent_at     TIMESTAMP NOT NULL DEFAULT NOW(),
                subject     TEXT NOT NULL,
                recipients  INTEGER NOT NULL,
                success     BOOLEAN NOT NULL,
                error       TEXT
            )
        """)

        # Migrations for columns added after initial release
        for stmt in [
            "ALTER TABLE keywords  ADD COLUMN IF NOT EXISTS required           BOOLEAN  NOT NULL DEFAULT FALSE",
            "ALTER TABLE sources   ADD COLUMN IF NOT EXISTS local              BOOLEAN  NOT NULL DEFAULT FALSE",
            "ALTER TABLE articles  ADD COLUMN IF NOT EXISTS daily_digest_sent  BOOLEAN  NOT NULL DEFAULT FALSE",
            "ALTER TABLE articles  ADD COLUMN IF NOT EXISTS weekly_digest_sent BOOLEAN  NOT NULL DEFAULT FALSE",
            "ALTER TABLE articles  ADD COLUMN IF NOT EXISTS relevance_score    SMALLINT",
            "ALTER TABLE articles  ADD COLUMN IF NOT EXISTS relevance_reason   TEXT",
        ]:
            conn.execute(stmt)

        for kw in INITIAL_KEYWORDS:
            conn.execute(
                "INSERT INTO keywords (keyword, active) VALUES (%s, TRUE) ON CONFLICT (keyword) DO NOTHING",
                (kw,),
            )

        for source in INITIAL_SOURCES:
            conn.execute(
                """
                INSERT INTO sources (name, url, rss_url, active, local)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (rss_url) DO NOTHING
                """,
                (source["name"], source["url"], source["rss_url"], source["active"], source["local"]),
            )


def get_stats(db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    with db_connection(db_path) as conn:
        total_articles  = conn.execute("SELECT COUNT(*) AS cnt FROM articles").fetchone()["cnt"]
        articles_today  = conn.execute(
            "SELECT COUNT(*) AS cnt FROM articles WHERE published_at::date = CURRENT_DATE"
        ).fetchone()["cnt"]
        active_keywords = conn.execute("SELECT COUNT(*) AS cnt FROM keywords  WHERE active = TRUE").fetchone()["cnt"]
        subscribers     = conn.execute("SELECT COUNT(*) AS cnt FROM subscribers WHERE active = TRUE").fetchone()["cnt"]
        active_sources  = conn.execute("SELECT COUNT(*) AS cnt FROM sources   WHERE active = TRUE").fetchone()["cnt"]
        unsent_articles = conn.execute("SELECT COUNT(*) AS cnt FROM articles  WHERE daily_digest_sent = FALSE").fetchone()["cnt"]
        unrated_articles = conn.execute("SELECT COUNT(*) AS cnt FROM articles WHERE relevance_score IS NULL").fetchone()["cnt"]
        last_harvest    = conn.execute(
            "SELECT run_at FROM harvest_log ORDER BY run_at DESC LIMIT 1"
        ).fetchone()

    return {
        "total_articles":  total_articles,
        "articles_today":  articles_today,
        "active_keywords": active_keywords,
        "subscribers":     subscribers,
        "active_sources":  active_sources,
        "unsent_articles":  unsent_articles,
        "unrated_articles": unrated_articles,
        "last_harvest":    str(last_harvest["run_at"]) if last_harvest else None,
    }


def list_active_keywords(db_path: str = DEFAULT_DB_PATH) -> List[str]:
    with db_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT keyword FROM keywords WHERE active = TRUE ORDER BY keyword"
        ).fetchall()
    return [r["keyword"] for r in rows]


def list_active_keywords_by_type(db_path: str = DEFAULT_DB_PATH):
    """Return (required_keywords, regular_keywords) — both lists of active keyword strings."""
    with db_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT keyword, required FROM keywords WHERE active = TRUE ORDER BY keyword"
        ).fetchall()
    required = [r["keyword"] for r in rows if r["required"]]
    regular  = [r["keyword"] for r in rows if not r["required"]]
    return required, regular


def list_unsent_articles(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    with db_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                a.id,
                s.name AS source,
                a.published_at,
                a.title,
                a.summary,
                a.link,
                a.matched_keywords
            FROM articles a
            JOIN sources s ON s.id = a.source_id
            WHERE a.daily_digest_sent = FALSE
              AND a.relevance_score >= %(threshold)s
            ORDER BY a.published_at ASC
            """
        , {"threshold": RELEVANCE_THRESHOLD}).fetchall()
    return [dict(r) for r in rows]


def list_unrated_articles(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    with db_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT a.id, a.title, a.summary, a.matched_keywords
            FROM articles a
            WHERE a.relevance_score IS NULL
            ORDER BY a.published_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def update_article_relevance(
    article_id: int,
    score: int,
    reason: str,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    with db_connection(db_path) as conn:
        conn.execute(
            "UPDATE articles SET relevance_score = %s, relevance_reason = %s WHERE id = %s",
            (score, reason, article_id),
        )


def mark_articles_daily_sent(article_ids: List[int], db_path: str = DEFAULT_DB_PATH) -> None:
    if not article_ids:
        return
    placeholders = ",".join(["%s"] * len(article_ids))
    with db_connection(db_path) as conn:
        conn.execute(
            f"UPDATE articles SET daily_digest_sent = TRUE WHERE id IN ({placeholders})",
            article_ids,
        )


def list_active_sources(db_path: str = DEFAULT_DB_PATH) -> List[Dict]:
    with db_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, name, url, rss_url, local FROM sources WHERE active = TRUE ORDER BY name"
        ).fetchall()
    return [dict(r) for r in rows]


def insert_article(
    source_id: int,
    title: str,
    summary: str,
    link: str,
    published_at: Optional[str],
    matched_keywords: Iterable[str],
    db_path: str = DEFAULT_DB_PATH,
) -> bool:
    with db_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO articles (source_id, title, summary, link, published_at, matched_keywords)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (link) DO NOTHING
            """,
            (
                source_id,
                title,
                summary,
                link,
                published_at,
                ", ".join(sorted(set(matched_keywords))),
            ),
        )
        return cur.rowcount > 0


def insert_harvest_log(
    run_at: datetime,
    sources_checked: int,
    articles_new: int,
    articles_skipped: int,
    errors: List[str],
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    with db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO harvest_log (run_at, sources_checked, articles_new, articles_skipped, errors)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                run_at.isoformat(timespec="seconds"),
                sources_checked,
                articles_new,
                articles_skipped,
                json.dumps(errors) if errors else None,
            ),
        )


def list_harvest_log(limit: int = 30, db_path: str = DEFAULT_DB_PATH) -> List[Dict]:
    with db_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT run_at, sources_checked, articles_new, articles_skipped, errors
            FROM harvest_log
            ORDER BY run_at DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def insert_mail_log(
    subject: str,
    recipients: int,
    success: bool,
    error: Optional[str],
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    with db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO mail_log (subject, recipients, success, error)
            VALUES (%s, %s, %s, %s)
            """,
            (subject, recipients, success, error),
        )


if __name__ == "__main__":
    init_db()
    print(f"Database initialised (schema: {_get_schema()})")
