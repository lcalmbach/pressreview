# Basler Presseschau (PoC)

Local press review app for Basel built with Python, Streamlit, and PostgreSQL.

## Features

- RSS harvesting with two-tier keyword filtering (see below)
- PostgreSQL database with articles, keywords, subscribers, sources, and harvest log
- Streamlit admin interface (German UI)
- Manual digest delivery via SMTP (text + HTML + PDF), with per-subscriber test send

## Keyword Filtering

Harvesting uses a two-tier keyword system:

**Mandatory keywords** – at least one must appear in every article (OR logic between them).  
Typical examples: `Basel`, `Basler`, `Basel-Stadt`.

**Topic keywords** – at least one must additionally be present (OR logic between them).  
Examples: `Verkehr`, `Bildung`, `Kriminalität`.

An article is only saved when **both conditions are met simultaneously**:

```
(Basel OR Basler OR Basel-Stadt) AND (Verkehr OR Bildung OR ...)
```

If no mandatory keywords are defined, the old behaviour applies: any match on a topic keyword is sufficient.

Keywords are managed in the admin interface under **Keywords**. The **Pflicht** checkbox marks a keyword as mandatory.

### Local Sources

Some RSS feeds report exclusively on local topics (e.g. Bajour) and therefore do not necessarily mention "Basel" in every article. For such sources, the **Lokal** checkbox can be enabled in the **Quellen** management page.

For sources marked as local, the mandatory keyword check is skipped — a single match on any topic keyword is sufficient:

```
local = True  →  only: Verkehr OR Bildung OR ...
local = False →  (Basel OR Basler OR ...) AND (Verkehr OR Bildung OR ...)
```

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create a `.env` file in the project root (see `.env` variables below).

4. Configure SMTP — either via `.env` variables or by copying and editing `config.ini`:

```bash
cp config.ini.example config.ini
```

### Database

The app uses PostgreSQL with a dedicated `pressreview` schema. Create the schema on your database, then run:

```bash
python db.py
```

This creates all tables and seeds initial sources and keywords.

**Environment variables** (`.env` or Streamlit secrets):

| Variable | Purpose |
|---|---|
| `DB_HOST` | PostgreSQL host (default: `localhost`) |
| `DB_PORT` | PostgreSQL port (default: `5432`) |
| `DB_NAME` | Database name (default: `postgres`) |
| `DB_USER` | Database user (default: `postgres`) |
| `DB_PASSWORD` | Database password |
| `HEROKU_DATABASE_URL` | Full Heroku Postgres URL (overrides `DB_*` when `USE_PRODUCTION_DB=1`) |
| `USE_PRODUCTION_DB` | Set to `1` to connect to the cloud DB locally |

**Connection priority at runtime:**

1. `DATABASE_URL` — set automatically on Heroku dynos.
2. `HEROKU_DATABASE_URL` + `USE_PRODUCTION_DB=1` — local override for the cloud DB.
3. `DB_*` vars — local PostgreSQL (default for development).

The database schema is always set to `pressreview` regardless of the connection URL.

### Streamlit Cloud secrets

When deploying to Streamlit Cloud, add the following secrets in the app settings:

| Secret | Description |
|---|---|
| `HEROKU_DATABASE_URL` | Heroku Postgres connection URL |
| `USE_PRODUCTION_DB` | `1` |
| `EMAIL_HOST` | SMTP server (e.g. `smtp.gmail.com`) |
| `EMAIL_PORT` | SMTP port (e.g. `587`) |
| `EMAIL_HOST_USER` | SMTP username |
| `EMAIL_HOST_PASSWORD` | SMTP password |
| `DEFAULT_FROM_EMAIL` | Sender address |
| `EMAIL_USE_TLS` | `true` |

## Start

Streamlit app:

```bash
streamlit run app.py
```

Run harvester manually:

```bash
python harvester.py
```

Send digest manually:

```bash
python mailer.py
```

## Digest Delivery

The digest can be sent in two ways:

- **Dashboard → "Send Digest Now"** – sends to all active subscribers.
- **Subscribers → "Digest senden"** (per row) – sends the digest exclusively to that one address, e.g. for testing or a manual individual send.

Both methods produce identical content (HTML + plain text + PDF attachment).

## Notes

- `.env` and `config.ini` are intentionally included in `.gitignore`.
- BaZ uses partner feeds. The default source URL is `https://partner-feeds.publishing.tamedia.ch/rss/bazonline/basel`.
- The SQLite file (`data/presseschau.db`) is no longer used and can be deleted if still present.

## Release Metadata

Before each deployment, update the two constants at the top of `app.py`:

```python
APP_VERSION = "0.2.1"
APP_VERSION_DATE = "2026-05-01"
```

The app displays both values in the sidebar and in the Impressum page.