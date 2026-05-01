import re
from datetime import date
from io import StringIO
from pathlib import Path

import feedparser
import pandas as pd
import streamlit as st

from db import DEFAULT_DB_PATH, db_connection, get_stats, init_db, list_harvest_log
from harvester import run_harvest
from mailer import send_digest

st.set_page_config(page_title="Basler Medienspiegel", layout="wide")


APP_VERSION = "0.2.2"
APP_VERSION_DATE = "2026-05-01"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
IMPRESSUM_FILE = Path("IMPRESSUM.md")


def _query_df(sql: str, params=()):
    with db_connection(DEFAULT_DB_PATH) as conn:
        return pd.read_sql_query(sql, conn.raw, params=params)


def _app_version() -> str:
    return APP_VERSION


def _app_version_date() -> str:
    return APP_VERSION_DATE


def page_dashboard():
    st.title("Basler Medienspiegel")
    st.write(
        "Lokales Monitoring regionaler Medienquellen mit Keyword-Filter und Versand als Tagesdigest."
    )

    stats = get_stats(DEFAULT_DB_PATH)
    ma, mb = st.columns(2)
    ma.metric("Artikel gesamt", stats["total_articles"])
    mb.metric("Artikel heute", stats["articles_today"])
    mc, md = st.columns(2)
    mc.metric("Aktive Quellen", stats["active_sources"])
    md.metric("Aktive Keywords", stats["active_keywords"])
    me, mf = st.columns(2)
    me.metric("Aktive Abonnenten", stats["subscribers"])
    mf.empty()

    col_left, col_right = st.columns(2)
    with col_left:
        st.caption(f"Letzter Harvest: {stats['last_harvest'] or '-'}")
        if st.button("Run Harvester Now", type="primary", width="stretch"):
            with st.spinner("RSS-Feeds werden verarbeitet..."):
                result = run_harvest(DEFAULT_DB_PATH)
            st.success("Harvest abgeschlossen")
            st.json(result)

    with col_right:
        st.caption(f"Noch nicht versendete Artikel: {stats['unsent_articles']}")
        if st.button("Send Digest Now", width="stretch"):
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
    st.dataframe(show, width="stretch", height=800)

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
        is_required = st.checkbox("Pflicht-Keyword (muss in jedem Artikel vorkommen)")
        submitted = st.form_submit_button("Hinzufügen")
        if submitted and new_kw.strip():
            keyword = new_kw.strip()
            with db_connection(DEFAULT_DB_PATH) as conn:
                existing = conn.execute(
                    "SELECT id FROM keywords WHERE LOWER(TRIM(keyword)) = LOWER(%s)",
                    (keyword,),
                ).fetchone()
                if existing:
                    st.warning("Keyword existiert bereits")
                else:
                    conn.execute(
                        "INSERT INTO keywords (keyword, active, required) VALUES (%s, TRUE, %s)",
                        (keyword, is_required),
                    )
                    st.success("Keyword hinzugefügt")

    df = _query_df(
        "SELECT id, keyword, active, required, created_at FROM keywords ORDER BY required DESC, LOWER(keyword)"
    )
    if df.empty:
        st.info("Keine Keywords vorhanden.")
        return

    for row in df.itertuples(index=False):
        c1, c2, c3, c4, c5 = st.columns([4, 2, 2, 3, 2])
        label = f"**{row.keyword}** 🔒" if row.required else row.keyword
        c1.markdown(label)
        is_active = c2.checkbox("Aktiv", value=bool(row.active), key=f"kw_active_{row.id}")
        is_required = c3.checkbox("Pflicht", value=bool(row.required), key=f"kw_req_{row.id}")
        c4.write(str(row.created_at))
        if c5.button("Löschen", key=f"kw_del_{row.id}"):
            with db_connection(DEFAULT_DB_PATH) as conn:
                conn.execute("DELETE FROM keywords WHERE id = %s", (row.id,))
            st.rerun()

        if bool(row.active) != bool(is_active) or bool(row.required) != bool(is_required):
            with db_connection(DEFAULT_DB_PATH) as conn:
                conn.execute(
                    "UPDATE keywords SET active = %s, required = %s WHERE id = %s",
                    (is_active, is_required, row.id),
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
                        "INSERT INTO subscribers (email, active) VALUES (%s, TRUE) ON CONFLICT (email) DO NOTHING",
                        (new_email.strip(),),
                    )
                st.success("Abonnent hinzugefügt")

    df = _query_df(
        "SELECT id, email, active, added_at FROM subscribers ORDER BY added_at DESC"
    )
    if df.empty:
        st.info("Keine Abonnenten vorhanden.")
        return

    for row in df.itertuples(index=False):
        c1, c2, c3, c4, c5 = st.columns([4, 2, 3, 2, 2])
        c1.write(row.email)
        is_active = c2.checkbox("Aktiv", value=bool(row.active), key=f"sub_active_{row.id}")
        c3.write(str(row.added_at))
        if c4.button("Digest senden", key=f"sub_digest_{row.id}"):
            try:
                with st.spinner(f"Digest wird an {row.email} gesendet..."):
                    send_digest(DEFAULT_DB_PATH, recipients=[row.email])
                st.success(f"Digest gesendet an {row.email}")
            except Exception as exc:
                st.error(f"Fehler: {exc}")
        if c5.button("🗑️", key=f"sub_del_{row.id}", help="Abonnent entfernen"):
            with db_connection(DEFAULT_DB_PATH) as conn:
                conn.execute("DELETE FROM subscribers WHERE id = %s", (row.id,))
            st.rerun()

        if bool(row.active) != bool(is_active):
            with db_connection(DEFAULT_DB_PATH) as conn:
                conn.execute(
                    "UPDATE subscribers SET active = %s WHERE id = %s",
                    (is_active, row.id),
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
                    "INSERT INTO sources (name, url, rss_url, active) VALUES (%s, %s, %s, TRUE) ON CONFLICT (rss_url) DO NOTHING",
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
            s.local,
            MAX(a.harvested_at) AS last_harvested
        FROM sources s
        LEFT JOIN articles a ON a.source_id = s.id
        GROUP BY s.id, s.name, s.url, s.rss_url, s.active, s.local
        ORDER BY s.name
        """
    )

    for row in df.itertuples(index=False):
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([4, 2, 2, 1])
            c1.markdown(f"**{row.name}**  ")
            c1.caption(f"Website: {row.url or '-'}")
            c1.caption(f"RSS: {row.rss_url}")
            c2.write(f"Last Harvested: {row.last_harvested or '-'}")
            active = c2.checkbox("Aktiv", value=bool(row.active), key=f"src_active_{row.id}")
            local = c2.checkbox("Lokal", value=bool(row.local), key=f"src_local_{row.id}",
                                help="Pflicht-Keywords werden für diese Quelle nicht geprüft")

            if bool(row.active) != bool(active) or bool(row.local) != bool(local):
                with db_connection(DEFAULT_DB_PATH) as conn:
                    conn.execute(
                        "UPDATE sources SET active = %s, local = %s WHERE id = %s",
                        (active, local, row.id),
                    )

            if c3.button("Test feed", key=f"src_test_{row.id}"):
                parsed = feedparser.parse(row.rss_url)
                entries = parsed.entries[:3]
                if not entries:
                    st.warning("Keine Eintrage im Feed gefunden")
                else:
                    for ent in entries:
                        st.write(f"- {ent.get('title', '(ohne Titel)')}")

            confirm_key = f"src_delete_confirm_{row.id}"
            if st.session_state.get(confirm_key):
                c4.warning("Sicher?")
                if c4.button("Ja, löschen", key=f"src_delete_yes_{row.id}", type="primary"):
                    with db_connection(DEFAULT_DB_PATH) as conn:
                        conn.execute("DELETE FROM sources WHERE id = %s", (row.id,))
                    st.session_state.pop(confirm_key, None)
                    st.rerun()
                if c4.button("Abbrechen", key=f"src_delete_cancel_{row.id}"):
                    st.session_state.pop(confirm_key, None)
                    st.rerun()
            else:
                if c4.button("🗑️", key=f"src_delete_{row.id}", help="Quelle löschen"):
                    st.session_state[confirm_key] = True
                    st.rerun()


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
