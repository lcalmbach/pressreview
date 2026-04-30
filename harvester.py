import argparse
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional
import unicodedata

import feedparser
import requests

from db import (
    DEFAULT_DB_PATH,
    init_db,
    insert_article,
    insert_harvest_log,
    list_active_keywords_by_type,
    list_active_sources,
)

REQUEST_TIMEOUT = 10
USER_AGENT = "BaslerPresseschau/0.1"
MAX_AGE_DAYS = 2


def parse_entry_datetime(entry) -> Optional[datetime]:
    for key in ("published", "updated"):
        value = entry.get(key)
        if not value:
            continue
        try:
            dt = parsedate_to_datetime(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            # Many feeds provide ISO-8601 timestamps that parsedate_to_datetime
            # does not handle reliably, e.g. 2026-04-27T04:09:07.000Z.
            try:
                iso_value = value.replace("Z", "+00:00")
                dt = datetime.fromisoformat(iso_value)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                continue
    return None


_IMG_TAG_RE = re.compile(r"<img\b[^>]*/?>", re.IGNORECASE)


def extract_summary(entry) -> str:
    content_list = entry.get("content") or []
    content_encoded = content_list[0].get("value", "") if content_list else ""
    raw = entry.get("summary") or entry.get("description") or content_encoded
    return _IMG_TAG_RE.sub("", raw).strip()


def keyword_matches(text: str, keywords: List[str]) -> List[str]:
    def normalize(value: str) -> str:
        lower = value.lower()
        # Common German transliterations found in feeds.
        lower = (
            lower.replace("ä", "ae")
            .replace("ö", "oe")
            .replace("ü", "ue")
            .replace("ß", "ss")
        )
        return "".join(
            c for c in unicodedata.normalize("NFKD", lower) if not unicodedata.combining(c)
        )

    normalized_text = normalize(text)
    return [
        kw for kw in keywords
        if re.search(r"\b" + re.escape(normalize(kw)) + r"\b", normalized_text)
    ]


def run_harvest(db_path: str = DEFAULT_DB_PATH) -> Dict[str, object]:
    init_db(db_path)
    required_kws, regular_kws = list_active_keywords_by_type(db_path)
    sources = list_active_sources(db_path)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=MAX_AGE_DAYS)

    errors: List[str] = []
    new_count = 0
    skipped_count = 0

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    for source in sources:
        try:
            response = session.get(source["rss_url"], timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
        except Exception as exc:
            errors.append(f"{source['name']}: {exc}")
            continue

        for entry in feed.entries:
            title = entry.get("title", "").strip()
            summary = extract_summary(entry)
            link = entry.get("link", "").strip()
            if not link:
                skipped_count += 1
                continue

            published_dt = parse_entry_datetime(entry)
            if published_dt and published_dt < cutoff:
                continue

            tags_text = " ".join(t.get("term", "") for t in (entry.get("tags") or []))
            text_blob = f"{title} {summary} {tags_text}".strip()
            is_local = bool(source["local"])
            required_matches = keyword_matches(text_blob, required_kws) if (required_kws and not is_local) else None
            regular_matches = keyword_matches(text_blob, regular_kws)
            if required_kws and not is_local and not required_matches:
                continue
            if not regular_matches:
                continue
            matches = (required_matches or []) + regular_matches

            published_iso = (
                published_dt.astimezone(timezone.utc).isoformat(timespec="seconds")
                if published_dt
                else None
            )
            inserted = insert_article(
                source_id=source["id"],
                title=title or "(ohne Titel)",
                summary=summary,
                link=link,
                published_at=published_iso,
                matched_keywords=matches,
                db_path=db_path,
            )
            if inserted:
                new_count += 1
            else:
                skipped_count += 1

    run_at = datetime.now()
    insert_harvest_log(
        run_at=run_at,
        sources_checked=len(sources),
        articles_new=new_count,
        articles_skipped=skipped_count,
        errors=errors,
        db_path=db_path,
    )

    return {
        "run_at": run_at.isoformat(timespec="seconds"),
        "sources_checked": len(sources),
        "articles_new": new_count,
        "articles_skipped": skipped_count,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RSS harvester for Basler Presseschau")
    parser.add_argument("--db", dest="db_path", default=DEFAULT_DB_PATH)
    args = parser.parse_args()

    started = time.time()
    result = run_harvest(db_path=args.db_path)
    duration = time.time() - started

    print("Harvest abgeschlossen")
    print(f"Quellen geprüft: {result['sources_checked']}")
    print(f"Neu gespeichert: {result['articles_new']}")
    print(f"Übersprungen: {result['articles_skipped']}")
    print(f"Fehler: {len(result['errors'])}")
    if result["errors"]:
        for err in result["errors"]:
            print(" -", err)
    print(f"Dauer: {duration:.2f}s")


if __name__ == "__main__":
    main()
