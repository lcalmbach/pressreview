import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

DEFAULT_DB_PATH = os.getenv("PRESSREVIEW_DB_PATH", "./data/presseschau.db")

INITIAL_KEYWORDS = [
    "Verwaltung",
    "Präsidialdepartement",
    "Parlament",
    "Conradin Cramer",
]

INITIAL_SOURCES = [
    {
        "name": "SRF News",
        "url": "https://www.srf.ch/news",
        "rss_url": "https://www.srf.ch/news/bnf/rss/1646",
        "active": 1,
    },
    {
        "name": "SRF Schweiz",
        "url": "https://www.srf.ch/news",
        "rss_url": "https://www.srf.ch/news/bnf/rss/1890",
        "active": 0,
    },
    {
        "name": "SRF Regionaljournal Basel",
        "url": "https://www.srf.ch/audio",
        "rss_url": "https://www.srf.ch/audio/regionaljournal-basel-baselland",
        "active": 0,
    },
    {
        "name": "Basler Zeitung (BaZ)",
        "url": "https://www.bazonline.ch",
        "rss_url": "https://partner-feeds.publishing.tamedia.ch/rss/bazonline/basel",
        "active": 1,
    },
    {
        "name": "BZ Basel",
        "url": "https://www.bzbasel.ch",
        "rss_url": "https://www.bzbasel.ch/rss",
        "active": 1,
    },
    {
        "name": "BZ Basel - Region Basel",
        "url": "https://www.bzbasel.ch",
        "rss_url": "https://www.bzbasel.ch/basel/bnf/rss/",
        "active": 0,
    },
    {
        "name": "Bajour",
        "url": "https://bajour.ch",
        "rss_url": "https://bajour.ch/api/rss-feed",
        "active": 1,
    },
    {
        "name": "TeleBasel",
        "url": "https://telebasel.ch",
        "rss_url": "https://telebasel.ch/feed/",
        "active": 0,
    },
    {
        "name": "Baseljetzt",
        "url": "https://www.baseljetzt.ch",
        "rss_url": "https://www.baseljetzt.ch/feed/",
        "active": 0,
    },
    {
        "name": "OnlineReports",
        "url": "https://www.onlinereports.ch",
        "rss_url": "https://www.onlinereports.ch/rss.xml",
        "active": 0,
    },
    {
        "name": "PrimeNews",
        "url": "https://primenews.ch",
        "rss_url": "https://primenews.ch/rss",
        "active": 0,
    },
    {
        "name": "20 Minuten",
        "url": "https://www.20min.ch",
        "rss_url": "https://partner-feeds.beta.20min.ch/rss/20minuten",
        "active": 1,
    },
]


@contextmanager
def db_connection(db_path: str = DEFAULT_DB_PATH):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    with db_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT,
                rss_url TEXT UNIQUE NOT NULL,
                active BOOLEAN NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT UNIQUE NOT NULL,
                active BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS subscribers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                active BOOLEAN NOT NULL DEFAULT 1,
                added_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                summary TEXT,
                link TEXT UNIQUE NOT NULL,
                published_at DATETIME,
                harvested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                matched_keywords TEXT,
                FOREIGN KEY(source_id) REFERENCES sources(id)
            );

            CREATE TABLE IF NOT EXISTS harvest_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_at DATETIME NOT NULL,
                sources_checked INTEGER NOT NULL,
                articles_new INTEGER NOT NULL,
                articles_skipped INTEGER NOT NULL,
                errors TEXT
            );

            CREATE TABLE IF NOT EXISTS mail_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sent_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                subject TEXT NOT NULL,
                recipients INTEGER NOT NULL,
                success BOOLEAN NOT NULL,
                error TEXT
            );
            """
        )

        for kw in INITIAL_KEYWORDS:
            conn.execute(
                """
                INSERT OR IGNORE INTO keywords (keyword, active)
                VALUES (?, 1)
                """,
                (kw,),
            )

        for source in INITIAL_SOURCES:
            conn.execute(
                """
                INSERT OR IGNORE INTO sources (name, url, rss_url, active)
                VALUES (:name, :url, :rss_url, :active)
                """,
                source,
            )

        # Tamedia/BaZ migrated away from the historic bazonline.ch RSS endpoint.
        # Keep existing DBs working by rewriting the obsolete URL and safely
        # deduplicate if the target URL already exists.
        old_url = "https://www.bazonline.ch/rss-652867452909"
        new_url = "https://partner-feeds.publishing.tamedia.ch/rss/bazonline/basel"

        old_row = conn.execute(
            "SELECT id FROM sources WHERE name = 'Basler Zeitung (BaZ)' AND rss_url = ?",
            (old_url,),
        ).fetchone()
        new_row = conn.execute(
            "SELECT id FROM sources WHERE rss_url = ?",
            (new_url,),
        ).fetchone()

        if old_row and not new_row:
            conn.execute(
                "UPDATE sources SET rss_url = ? WHERE id = ?",
                (new_url, old_row["id"]),
            )
        elif old_row and new_row:
            conn.execute("DELETE FROM sources WHERE id = ?", (old_row["id"],))

        # Bajour switched from /feed to API feed endpoints.
        bajour_old = "https://bajour.ch/feed"
        bajour_new = "https://bajour.ch/api/rss-feed"

        bajour_old_row = conn.execute(
            "SELECT id FROM sources WHERE name = 'Bajour' AND rss_url = ?",
            (bajour_old,),
        ).fetchone()
        bajour_new_row = conn.execute(
            "SELECT id FROM sources WHERE rss_url = ?",
            (bajour_new,),
        ).fetchone()

        if bajour_old_row and not bajour_new_row:
            conn.execute(
                "UPDATE sources SET rss_url = ? WHERE id = ?",
                (bajour_new, bajour_old_row["id"]),
            )
        elif bajour_old_row and bajour_new_row:
            conn.execute("DELETE FROM sources WHERE id = ?", (bajour_old_row["id"],))


def get_stats(db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    with db_connection(db_path) as conn:
        total_articles = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        articles_today = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE DATE(published_at) = DATE('now', 'localtime')"
        ).fetchone()[0]
        active_keywords = conn.execute(
            "SELECT COUNT(*) FROM keywords WHERE active = 1"
        ).fetchone()[0]
        subscribers = conn.execute(
            "SELECT COUNT(*) FROM subscribers WHERE active = 1"
        ).fetchone()[0]
        last_harvest = conn.execute(
            "SELECT run_at FROM harvest_log ORDER BY run_at DESC LIMIT 1"
        ).fetchone()

    return {
        "total_articles": total_articles,
        "articles_today": articles_today,
        "active_keywords": active_keywords,
        "subscribers": subscribers,
        "last_harvest": last_harvest[0] if last_harvest else None,
    }


def list_active_keywords(db_path: str = DEFAULT_DB_PATH) -> List[str]:
    with db_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT keyword FROM keywords WHERE active = 1 ORDER BY keyword"
        ).fetchall()
    return [r["keyword"] for r in rows]


def list_active_sources(db_path: str = DEFAULT_DB_PATH) -> List[sqlite3.Row]:
    with db_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, name, url, rss_url FROM sources WHERE active = 1 ORDER BY name"
        ).fetchall()
    return rows


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
        cur = conn.execute("SELECT id FROM articles WHERE link = ?", (link,))
        if cur.fetchone():
            return False

        conn.execute(
            """
            INSERT INTO articles (source_id, title, summary, link, published_at, matched_keywords)
            VALUES (?, ?, ?, ?, ?, ?)
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
    return True


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
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                run_at.isoformat(timespec="seconds"),
                sources_checked,
                articles_new,
                articles_skipped,
                json.dumps(errors) if errors else None,
            ),
        )


def list_harvest_log(limit: int = 30, db_path: str = DEFAULT_DB_PATH) -> List[sqlite3.Row]:
    with db_connection(db_path) as conn:
        return conn.execute(
            """
            SELECT run_at, sources_checked, articles_new, articles_skipped, errors
            FROM harvest_log
            ORDER BY run_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


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
            VALUES (?, ?, ?, ?)
            """,
            (subject, recipients, int(success), error),
        )


if __name__ == "__main__":
    init_db()
    print("Datenbank initialisiert:", DEFAULT_DB_PATH)
