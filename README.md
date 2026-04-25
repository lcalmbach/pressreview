# Basler Presseschau (PoC)

Lokale Presseschau-App fur Basel mit Python, Streamlit und SQLite.

## Features

- RSS-Harvesting mit Keyword-Filter
- SQLite-Datenbank mit Artikeln, Keywords, Abonnenten, Quellen und Harvest-Log
- Streamlit-Adminoberflache (Deutsch)
- Manueller Digest-Versand per SMTP (Text + HTML + PDF)

## Setup

1. Virtuelle Umgebung erstellen und aktivieren.
2. Abhangigkeiten installieren:

```bash
pip install -r requirements.txt
```

3. SMTP konfigurieren:

```bash
cp config.ini.example config.ini
```

Dann Werte in `config.ini` anpassen.

## Start

Streamlit App:

```bash
streamlit run app.py
```

Harvester manuell:

```bash
python harvester.py
```

Digest manuell senden:

```bash
python mailer.py
```

## Hinweise

- Die Datenbank wird automatisch unter `./data/presseschau.db` erstellt.
- `config.ini` ist absichtlich in `.gitignore` enthalten.
- BaZ nutzt inzwischen Partner-Feeds. Standardquelle ist deshalb `https://partner-feeds.publishing.tamedia.ch/rss/bazonline/basel`.

## Troubleshooting (Linux)

Wenn beim Start von Streamlit der Fehler `inotify watch limit reached` erscheint:

1. Kurzfristig ist im Projekt bereits ein Fallback aktiv: `.streamlit/config.toml` setzt den Watcher auf `poll`.
2. Dauerhaft kann das inotify-Limit erhoht werden:

```bash
echo fs.inotify.max_user_watches=524288 | sudo tee -a /etc/sysctl.conf
echo fs.inotify.max_user_instances=1024 | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```
