# Basler Presseschau (PoC)

Local press review app for Basel built with Python, Streamlit, and SQLite.

## Features

- RSS harvesting with keyword filtering
- SQLite database with articles, keywords, subscribers, sources, and harvest log
- Streamlit admin interface (German UI)
- Manual digest delivery via SMTP (text + HTML + PDF)

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

## Notes

- The database is created automatically at `./data/presseschau.db`.
- `config.ini` is intentionally included in `.gitignore`.
- BaZ now uses partner feeds. The default source is `https://partner-feeds.publishing.tamedia.ch/rss/bazonline/basel`.

## Release Metadata

Before each deployment, update both files:

- `VERSION` (application version, for example `0.0.2`)
- `VERSION_DATE` (release date in `YYYY-MM-DD` format)

The app displays both values in the sidebar and in the Impressum page.

## Troubleshooting (Linux)

If you see the `inotify watch limit reached` error when starting Streamlit:

1. A short-term fallback is already active in the project: `.streamlit/config.toml` sets the watcher to `poll`.
2. For a permanent fix, increase the inotify limits:

```bash
echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf
echo fs.inotify.max_user_instances=1024 | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```
