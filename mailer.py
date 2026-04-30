import argparse
import configparser
import os
import re
import smtplib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from email.message import EmailMessage
from pathlib import Path
from typing import Dict, List, Sequence

from dotenv import find_dotenv, load_dotenv
from jinja2 import Environment, FileSystemLoader, select_autoescape

from db import DEFAULT_DB_PATH, db_connection, init_db, insert_mail_log

MONTH_NAMES_DE = {
    1: "Januar",
    2: "Februar",
    3: "März",
    4: "April",
    5: "Mai",
    6: "Juni",
    7: "Juli",
    8: "August",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Dezember",
}


_ZURICH = ZoneInfo("Europe/Zurich")


def format_zurich_time(published_at: str) -> str:
    if not published_at:
        return "-"
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_ZURICH).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return published_at


def load_smtp_settings(config_path: str = "config.ini") -> Dict[str, str]:
    # Ensure .env is loaded even when Streamlit runs from a different CWD.
    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path=dotenv_path)
    else:
        load_dotenv(Path(__file__).resolve().parent / ".env")

    cfg = configparser.ConfigParser()
    cfg.read(config_path)

    smtp_section = cfg["smtp"] if "smtp" in cfg else {}

    def env_first(*keys: str, default: str = "") -> str:
        for key in keys:
            value = os.getenv(key)
            if value not in (None, ""):
                return value
        return default

    return {
        "host": env_first("SMTP_HOST", "EMAIL_HOST", "MAIL_HOST", default=smtp_section.get("host", "")),
        "port": int(
            env_first("SMTP_PORT", "EMAIL_PORT", "MAIL_PORT", default=smtp_section.get("port", "587"))
        ),
        "user": env_first(
            "SMTP_USER",
            "EMAIL_HOST_USER",
            "MAIL_USER",
            default=smtp_section.get("user", ""),
        ),
        "password": env_first(
            "SMTP_PASSWORD",
            "EMAIL_HOST_PASSWORD",
            "MAIL_PASSWORD",
            default=smtp_section.get("password", ""),
        ),
        "use_tls": str(
            env_first("SMTP_USE_TLS", "EMAIL_USE_TLS", "MAIL_USE_TLS", default=smtp_section.get("use_tls", "true"))
        ).lower()
        in ("1", "true", "yes", "on"),
        "from_name": env_first(
            "SMTP_FROM_NAME",
            "EMAIL_FROM_NAME",
            "DEFAULT_FROM_NAME",
            default=smtp_section.get("from_name", "Basler Medienspiegel"),
        ),
        "from_email": env_first(
            "SMTP_FROM_EMAIL",
            "DEFAULT_FROM_EMAIL",
            "EMAIL_FROM",
            default=smtp_section.get("from_email", smtp_section.get("user", "")),
        ),
    }


def list_subscribers(db_path: str = DEFAULT_DB_PATH, mailing_path: str = "mailing.txt") -> List[str]:
    emails: List[str] = []

    with db_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT email FROM subscribers WHERE active = 1 ORDER BY email"
        ).fetchall()
        emails.extend([r["email"] for r in rows])

    if emails:
        return sorted(set(emails))

    file_path = Path(mailing_path)
    if file_path.exists():
        for line in file_path.read_text(encoding="utf-8").splitlines():
            item = line.strip()
            if not item or item.startswith("#"):
                continue
            emails.append(item)

    return sorted(set(emails))


def list_today_articles(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, str]]:
    with db_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                s.name AS source,
                a.published_at,
                a.title,
                a.summary,
                a.link,
                a.matched_keywords
            FROM articles a
            JOIN sources s ON s.id = a.source_id
            WHERE DATE(a.published_at) = DATE('now', 'localtime')
            ORDER BY s.name ASC, a.published_at DESC
            """
        ).fetchall()

    return [dict(r) for r in rows]


def highlight_keywords(summary: str, keyword_csv: str) -> str:
    text = summary or ""
    keywords = [k.strip() for k in (keyword_csv or "").split(",") if k.strip()]
    for kw in sorted(keywords, key=len, reverse=True):
        pattern = re.compile(re.escape(kw), re.IGNORECASE)
        text = pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", text)
    return text


def to_plain_text(articles: Sequence[Dict[str, str]], digest_date: str) -> str:
    lines = [f"Basler Presseschau - {digest_date}", ""]
    for art in articles:
        lines.append(f"[{art['source']}] {art['title']}")
        lines.append(f"Zeit: {format_zurich_time(art.get('published_at') or '')}")
        lines.append(f"Keywords: {art.get('matched_keywords') or '-'}")
        lines.append(f"Link: {art['link']}")
        if art.get("summary"):
            lines.append(f"Summary: {art['summary']}")
        lines.append("")
    return "\n".join(lines)


def render_digest(articles: List[Dict[str, str]], digest_date: str):
    template_env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )

    display_articles = []
    for art in articles:
        copy_art = dict(art)
        copy_art["summary_highlighted"] = highlight_keywords(
            copy_art.get("summary") or "", copy_art.get("matched_keywords") or ""
        )
        copy_art["published_at_fmt"] = format_zurich_time(copy_art.get("published_at") or "")
        display_articles.append(copy_art)

    html_template = template_env.get_template("digest.html")
    pdf_template = template_env.get_template("digest_pdf.html")

    html = html_template.render(date_label=digest_date, articles=display_articles)
    pdf_html = pdf_template.render(date_label=digest_date, articles=display_articles)
    return html, pdf_html


def render_pdf(pdf_html: str) -> bytes | None:
    # Import lazily so environments without native weasyprint dependencies
    # can still run the app and send the HTML/text digest.
    try:
        from weasyprint import HTML  # type: ignore
    except Exception:
        return None

    try:
        return HTML(string=pdf_html).write_pdf()
    except Exception:
        return None


def build_subject(today: datetime) -> str:
    return f"Basler Presseschau - {today.day}. {MONTH_NAMES_DE[today.month]} {today.year}"


def send_digest(
    db_path: str = DEFAULT_DB_PATH,
    config_path: str = "config.ini",
    mailing_path: str = "mailing.txt",
    recipients: List[str] | None = None,
) -> Dict[str, object]:
    init_db(db_path)

    subscribers = recipients if recipients is not None else list_subscribers(db_path=db_path, mailing_path=mailing_path)
    if not subscribers:
        raise RuntimeError("Keine aktiven Empfänger gefunden")

    articles = list_today_articles(db_path=db_path)
    today = datetime.now()
    date_label = today.strftime("%d.%m.%Y")
    subject = build_subject(today)

    html_body, pdf_html = render_digest(articles, date_label)
    text_body = to_plain_text(articles, date_label)
    pdf_bytes = render_pdf(pdf_html)

    smtp = load_smtp_settings(config_path=config_path)
    missing = [key for key in ("host", "from_email") if not smtp.get(key)]
    if missing:
        hint_map = {
            "host": "SMTP_HOST oder EMAIL_HOST",
            "from_email": "SMTP_FROM_EMAIL oder DEFAULT_FROM_EMAIL",
        }
        hints = [hint_map[key] for key in missing if key in hint_map]
        raise RuntimeError(
            f"Fehlende SMTP-Konfiguration: {', '.join(missing)}"
            + (f". Bitte setzen: {', '.join(hints)}" if hints else "")
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{smtp['from_name']} <{smtp['from_email']}>"
    msg["To"] = smtp["from_email"]
    msg["Bcc"] = ", ".join(subscribers)

    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    if pdf_bytes is not None:
        msg.add_attachment(
            pdf_bytes,
            maintype="application",
            subtype="pdf",
            filename=f"presseschau_{today.strftime('%Y%m%d')}.pdf",
        )

    try:
        with smtplib.SMTP(smtp["host"], smtp["port"], timeout=20) as server:
            if smtp["use_tls"]:
                server.starttls()
            if smtp.get("user"):
                server.login(smtp["user"], smtp.get("password", ""))
            server.send_message(msg)
        insert_mail_log(subject, len(subscribers), True, None, db_path=db_path)
    except Exception as exc:
        insert_mail_log(subject, len(subscribers), False, str(exc), db_path=db_path)
        raise

    return {
        "subject": subject,
        "recipients": len(subscribers),
        "articles": len(articles),
        "date": date_label,
        "pdf_attached": pdf_bytes is not None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Send Basler Presseschau digest")
    parser.add_argument("--db", dest="db_path", default=DEFAULT_DB_PATH)
    parser.add_argument("--config", dest="config_path", default="config.ini")
    parser.add_argument("--mailing", dest="mailing_path", default="mailing.txt")
    args = parser.parse_args()

    result = send_digest(
        db_path=args.db_path,
        config_path=args.config_path,
        mailing_path=args.mailing_path,
    )
    print("Digest gesendet")
    print(f"Betreff: {result['subject']}")
    print(f"Empfänger: {result['recipients']}")
    print(f"Artikel: {result['articles']}")


if __name__ == "__main__":
    main()
