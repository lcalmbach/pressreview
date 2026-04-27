import re
from datetime import date, datetime, timedelta
from io import StringIO
from pathlib import Path

import feedparser
import pandas as pd
import streamlit as st

from db import DEFAULT_DB_PATH, db_connection, get_stats, init_db, list_harvest_log
from harvester import run_harvest
from mailer import send_digest

st.set_page_config(page_title="Basler Medienspiegel", layout="wide")


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
VERSION_FILE = Path("VERSION")
VERSION_DATE_FILE = Path("VERSION_DATE")
IMPRESSUM_FILE = Path("IMPRESSUM.md")


def _query_df(sql: str, params=()):
    with db_connection(DEFAULT_DB_PATH) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def _app_version() -> str:
    if VERSION_FILE.exists():
        version = VERSION_FILE.read_text(encoding="utf-8").strip()
        if version:
            return version
    return "0.0.1"


def _app_version_date() -> str:
    if VERSION_DATE_FILE.exists():
        version_date = VERSION_DATE_FILE.read_text(encoding="utf-8").strip()
        if version_date:
            return version_date
    return "1970-01-01"


def page_dashboard():
    st.title("Basler Medienspiegel")
    st.write(
        "Lokales Monitoring regionaler Medienquellen mit Keyword-Filter und Versand als Tagesdigest."
    )

    stats = get_stats(DEFAULT_DB_PATH)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Artikel gesamt", stats["total_articles"])
    c2.metric("Artikel heute", stats["articles_today"])
    c3.metric("Aktive Keywords", stats["active_keywords"])
    c4.metric("Aktive Abonnenten", stats["subscribers"])

    st.caption(f"Letzter Harvest: {stats['last_harvest'] or '-'}")

    left, right = st.columns(2)
    with left:
        if st.button("Run Harvester Now", type="primary"):
            with st.spinner("RSS-Feeds werden verarbeitet..."):
                result = run_harvest(DEFAULT_DB_PATH)
            st.success("Harvest abgeschlossen")
            st.json(result)

    with right:
        if st.button("Send Digest Now"):
            try:
                with st.spinner("Digest wird versendet..."):
                    result = send_digest(DEFAULT_DB_PATH)
                st.success("Digest erfolgreich gesendet")
                if not result.get("pdf_attached", True):
                    st.warning(
                        "Digest wurde ohne PDF-Anhang versendet, da die PDF-Generierung "
                        "in dieser Umgebung nicht verfugbar ist."
                    )
                st.json(result)
            except Exception as exc:
                st.error(f"Versand fehlgeschlagen: {exc}")


def page_articles():
    st.title("Artikel")

    df = _query_df(
        """
        SELECT
            a.id,
            a.published_at,
            s.name AS source,
            a.title,
            a.summary,
            a.link,
            a.matched_keywords
        FROM articles a
        JOIN sources s ON s.id = a.source_id
        ORDER BY a.published_at DESC
        """
    )

    if df.empty:
        st.info("Noch keine Artikel vorhanden.")
        return

    df["published_dt"] = pd.to_datetime(df["published_at"], errors="coerce", utc=True)
    valid_published = df["published_dt"].dropna()
    if valid_published.empty:
        min_date = date.today()
        max_date = date.today()
    else:
        min_date = valid_published.min().date()
        max_date = valid_published.max().date()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        start_date = st.date_input("Von", value=min_date)
    with col2:
        end_date = st.date_input("Bis", value=max_date)
    with col3:
        source_opts = sorted(df["source"].dropna().unique().tolist())
        selected_sources = st.multiselect("Quellen", source_opts, default=source_opts)
    with col4:
        keyword_filter = st.text_input("Keyword-Filter")

    free_text = st.text_input("Freitext (Titel + Summary)")

    filt = df.copy()
    start_ts = pd.Timestamp(start_date, tz="UTC")
    end_ts = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(days=1)
    filt = filt[(filt["published_dt"] >= start_ts) & (filt["published_dt"] < end_ts)]
    if selected_sources:
        filt = filt[filt["source"].isin(selected_sources)]
    if keyword_filter.strip():
        filt = filt[
            filt["matched_keywords"].fillna("").str.contains(
                keyword_filter.strip(), case=False, regex=False
            )
        ]
    if free_text.strip():
        pattern = free_text.strip()
        filt = filt[
            filt["title"].fillna("").str.contains(pattern, case=False, regex=False)
            | filt["summary"].fillna("").str.contains(pattern, case=False, regex=False)
        ]

    show = filt[["published_at", "source", "title", "summary", "matched_keywords", "link"]]
    st.dataframe(show, width="stretch")

    csv_buf = StringIO()
    show.to_csv(csv_buf, index=False)
    st.download_button(
        "Download as CSV",
        data=csv_buf.getvalue(),
        file_name=f"presseschau_articles_{date.today().isoformat()}.csv",
        mime="text/csv",
    )


def page_keywords():
    st.title("Keywords")

    with st.form("add_keyword"):
        new_kw = st.text_input("Neues Keyword")
        submitted = st.form_submit_button("Hinzufügen")
        if submitted and new_kw.strip():
            keyword = new_kw.strip()
            with db_connection(DEFAULT_DB_PATH) as conn:
                existing = conn.execute(
                    "SELECT id FROM keywords WHERE LOWER(TRIM(keyword)) = LOWER(?)",
                    (keyword,),
                ).fetchone()
                if existing:
                    st.warning("Keyword existiert bereits")
                else:
                    conn.execute(
                        "INSERT INTO keywords (keyword, active) VALUES (?, 1)",
                        (keyword,),
                    )
                    st.success("Keyword hinzugefügt")

    df = _query_df(
        "SELECT id, keyword, active, created_at FROM keywords ORDER BY keyword COLLATE NOCASE"
    )
    if df.empty:
        st.info("Keine Keywords vorhanden.")
        return

    for row in df.itertuples(index=False):
        c1, c2, c3, c4 = st.columns([4, 2, 3, 2])
        c1.write(row.keyword)
        is_active = c2.checkbox("Aktiv", value=bool(row.active), key=f"kw_active_{row.id}")
        c3.write(str(row.created_at))
        if c4.button("Löschen", key=f"kw_del_{row.id}"):
            with db_connection(DEFAULT_DB_PATH) as conn:
                conn.execute("DELETE FROM keywords WHERE id = ?", (row.id,))
            st.rerun()

        if bool(row.active) != bool(is_active):
            with db_connection(DEFAULT_DB_PATH) as conn:
                conn.execute(
                    "UPDATE keywords SET active = ? WHERE id = ?",
                    (int(is_active), row.id),
                )


def page_subscribers():
    st.title("Abonnenten")

    with st.form("add_subscriber"):
        new_email = st.text_input("Neue E-Mail")
        submitted = st.form_submit_button("Hinzufügen")
        if submitted:
            if not EMAIL_RE.match(new_email.strip()):
                st.error("Bitte eine gültige E-Mail eingeben")
            else:
                with db_connection(DEFAULT_DB_PATH) as conn:
                    conn.execute(
                        "INSERT OR IGNORE INTO subscribers (email, active) VALUES (?, 1)",
                        (new_email.strip(),),
                    )
                st.success("Abonnent hinzugefügt")

    if st.button("Import from mailing.txt"):
        file_path = Path("mailing.txt")
        if not file_path.exists():
            st.error("mailing.txt wurde nicht gefunden")
        else:
            added = 0
            with db_connection(DEFAULT_DB_PATH) as conn:
                for line in file_path.read_text(encoding="utf-8").splitlines():
                    item = line.strip()
                    if not item or item.startswith("#"):
                        continue
                    if not EMAIL_RE.match(item):
                        continue
                    conn.execute(
                        "INSERT OR IGNORE INTO subscribers (email, active) VALUES (?, 1)",
                        (item,),
                    )
                    added += 1
            st.success(f"Import abgeschlossen, verarbeitet: {added}")

    df = _query_df(
        "SELECT id, email, active, added_at FROM subscribers ORDER BY added_at DESC"
    )
    if df.empty:
        st.info("Keine Abonnenten vorhanden.")
        return

    for row in df.itertuples(index=False):
        c1, c2, c3, c4 = st.columns([4, 2, 3, 2])
        c1.write(row.email)
        is_active = c2.checkbox("Aktiv", value=bool(row.active), key=f"sub_active_{row.id}")
        c3.write(str(row.added_at))
        if c4.button("Entfernen", key=f"sub_del_{row.id}"):
            with db_connection(DEFAULT_DB_PATH) as conn:
                conn.execute("DELETE FROM subscribers WHERE id = ?", (row.id,))
            st.rerun()

        if bool(row.active) != bool(is_active):
            with db_connection(DEFAULT_DB_PATH) as conn:
                conn.execute(
                    "UPDATE subscribers SET active = ? WHERE id = ?",
                    (int(is_active), row.id),
                )


def page_sources():
    st.title("Quellen")

    with st.form("add_source"):
        name = st.text_input("Name")
        website = st.text_input("Website URL")
        rss = st.text_input("RSS URL")
        submitted = st.form_submit_button("Quelle hinzufugen")
        if submitted and name.strip() and rss.strip():
            with db_connection(DEFAULT_DB_PATH) as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO sources (name, url, rss_url, active)
                    VALUES (?, ?, ?, 1)
                    """,
                    (name.strip(), website.strip(), rss.strip()),
                )
            st.success("Quelle gespeichert")

    df = _query_df(
        """
        SELECT
            s.id,
            s.name,
            s.url,
            s.rss_url,
            s.active,
            MAX(a.harvested_at) AS last_harvested
        FROM sources s
        LEFT JOIN articles a ON a.source_id = s.id
        GROUP BY s.id, s.name, s.url, s.rss_url, s.active
        ORDER BY s.name
        """
    )

    for row in df.itertuples(index=False):
        with st.container(border=True):
            c1, c2, c3 = st.columns([4, 2, 2])
            c1.markdown(f"**{row.name}**  ")
            c1.caption(f"Website: {row.url or '-'}")
            c1.caption(f"RSS: {row.rss_url}")
            c2.write(f"Last Harvested: {row.last_harvested or '-'}")
            active = c2.checkbox("Aktiv", value=bool(row.active), key=f"src_active_{row.id}")

            if bool(row.active) != bool(active):
                with db_connection(DEFAULT_DB_PATH) as conn:
                    conn.execute(
                        "UPDATE sources SET active = ? WHERE id = ?",
                        (int(active), row.id),
                    )

            if c3.button("Test feed", key=f"src_test_{row.id}"):
                parsed = feedparser.parse(row.rss_url)
                entries = parsed.entries[:3]
                if not entries:
                    st.warning("Keine Eintrage im Feed gefunden")
                else:
                    for ent in entries:
                        st.write(f"- {ent.get('title', '(ohne Titel)')}")


def page_harvest_log():
    st.title("Harvest Log")

    rows = list_harvest_log(50, DEFAULT_DB_PATH)
    if not rows:
        st.info("Noch kein Harvest-Log vorhanden.")
        return

    for idx, row in enumerate(rows):
        header = (
            f"{row['run_at']} | Quellen: {row['sources_checked']} | "
            f"Neu: {row['articles_new']} | Skip: {row['articles_skipped']}"
        )
        with st.expander(header, expanded=(idx == 0)):
            if row["errors"]:
                st.code(row["errors"], language="json")
            else:
                st.write("Keine Fehler")


def page_impressum():
    st.title("Impressum")
    with st.container(border=True):
        st.markdown(
            "\n\n".join(
                [
                    "**Basler Medienspiegel**",
                    "",
                    "**Author:** [Lukas Calmbach](mailto:lcalmbach@gmail.com)",
                    "[GitHub repository](https://github.com/lcalmbach/pressreview)",
                    f"**Version:** {_app_version()}",
                    f"**Version date:** {_app_version_date()}",
                ]
            )
        )


def main():
    init_db(DEFAULT_DB_PATH)

    pages = {
        "Dashboard": page_dashboard,
        "Artikel": page_articles,
        "Keywords": page_keywords,
        "Abonnenten": page_subscribers,
        "Quellen": page_sources,
        "Harvest Log": page_harvest_log,
        "Impressum": page_impressum,
    }

    selected = st.sidebar.radio("Navigation", list(pages.keys()))
    st.sidebar.caption(f"Version {_app_version()} ({_app_version_date()})")
    pages[selected]()


if __name__ == "__main__":
    main()
