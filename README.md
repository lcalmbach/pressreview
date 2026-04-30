# Basler Presseschau (PoC)

Local press review app for Basel built with Python, Streamlit, and SQLite.

## Features

- RSS harvesting with two-tier keyword filtering (see below)
- SQLite database with articles, keywords, subscribers, sources, and harvest log
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

3. Configure SMTP:

```bash
cp config.ini.example config.ini
```

Then adjust the values in `config.ini`.

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

- The database is created automatically at `./data/presseschau.db`.
- `config.ini` is intentionally included in `.gitignore`.
- BaZ now uses partner feeds. The default source is `https://partner-feeds.publishing.tamedia.ch/rss/bazonline/basel`.

## Release Metadata

Before each deployment, update both files:

- `VERSION` (application version, for example `0.0.2`)
- `VERSION_DATE` (release date in `YYYY-MM-DD` format)

The app displays both values in the sidebar and in the Impressum page.