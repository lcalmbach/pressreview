# Basler Presseschau (PoC)

Local press review app for Basel built with Python, Streamlit, and PostgreSQL.

## Features

- RSS harvesting with two-tier keyword filtering (see below)
- AI relevance scoring via LLM (Anthropic or DeepSeek models)
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

## AI Relevance Scoring

After harvesting, articles can be rated for relevance by an LLM. This is a separate manual step triggered from the Dashboard via the **Rate Articles** button.

Each unrated article is sent to the selected model with a prompt asking it to score the article's relevance to Basel city affairs on a scale of **1–10** and provide a one-sentence reason. The score and reason are stored in the database alongside the article.

Only articles with a relevance score of **≥ 7** (configurable via `RELEVANCE_THRESHOLD` in `db.py`) are included in the digest.

### Model selection

The model can be changed using the **Bewertungsmodell** dropdown in the sidebar (visible only on the Dashboard page). Available options:

| Display name | Provider | Model ID |
|---|---|---|
| Claude Haiku 4.5 (fast) | Anthropic | `claude-haiku-4-5-20251001` |
| Claude Sonnet 4.6 | Anthropic | `claude-sonnet-4-6` |
| DeepSeek Chat | DeepSeek | `deepseek-chat` |
| DeepSeek Reasoner | DeepSeek | `deepseek-reasoner` |

Anthropic models require `ANTHROPIC_API_KEY`. DeepSeek models require `DEEPSEEK_API_KEY`. Both can be set in `.env` (local) or as Streamlit Cloud secrets.

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
| `ANTHROPIC_API_KEY` | API key for Anthropic models (Claude Haiku, Sonnet) |
| `DEEPSEEK_API_KEY` | API key for DeepSeek models (deepseek-chat, deepseek-reasoner) |

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
| `ANTHROPIC_API_KEY` | API key for Anthropic models |
| `DEEPSEEK_API_KEY` | API key for DeepSeek models |

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