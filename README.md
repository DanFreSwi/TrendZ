# TrendZ 📈

**Die Top 3 von allem, was in der Schweiz gerade abgeht:** News (Schweiz und Welt), Suchtrends,
Musik, Podcasts, Filme und Videos, auf einer einzigen Seite.

TrendZ ist ein nicht-kommerzielles Hobbyprojekt.

## So funktioniert es

```
Quellen (RSS & APIs)  →  Sammler (Python, alle 3 Std.)  →  docs/data/latest.json  →  Website
```

| Teil | Wo | Was es macht |
|---|---|---|
| Sammler | `collector/collect.py` | Holt die Trends, wählt die Top 3 pro Kategorie, speichert sie. |
| Zeitplan | `.github/workflows/sammeln.yml` | Startet den Sammler automatisch alle 3 Stunden auf GitHub. |
| Daten | `docs/data/` | `latest.json` = aktueller Stand, `archiv/` = ein Schnappschuss pro Tag. |
| Website | `docs/` | `index.html`, `style.css`, `app.js` zeigen die Daten an. |

## Quellen

Nur offizielle RSS-Feeds und Schnittstellen. Der Sammler respektiert die `robots.txt` der Websites,
speichert nur Titel, kurze Teaser, Vorschaubilder und Links und verlinkt immer auf das Original.

| Kategorie | Quelle | Schlüssel nötig? |
|---|---|---|
| News Schweiz | SRF, Blick, 20 Minuten, watson (RSS) | nein |
| News Welt | BBC, The Guardian, tagesschau (RSS) | nein |
| Gesucht in der Schweiz | Google Trends (RSS) | nein |
| Musik | Apple Music Charts Schweiz | nein |
| Podcasts | Apple Podcasts Charts Schweiz | nein |
| Filme im Kino | TMDB | ja, kostenlos: `TMDB_API_KEY` |
| Videos | YouTube Data API | ja, kostenlos: `YOUTUBE_API_KEY` |

**Wie kommen die Top 3 News zustande?** Eine Geschichte, über die mehrere Redaktionen gleichzeitig
berichten, rutscht nach oben. Dafür vergleicht der Sammler die Stichwörter der Schlagzeilen.

## Einrichtung (einmalig)

1. **Website einschalten:** Settings → Pages → *Build and deployment*: Source = „Deploy from a branch“,
   Branch = `main`, Ordner = `/docs` → Save. Nach 1 bis 2 Minuten ist die Seite unter
   `https://danfreswi.github.io/TrendZ/` erreichbar.
2. **Ersten Durchlauf starten:** Actions → „Trends sammeln“ → *Run workflow*.
3. **Optional, für Filme und Videos:** Settings → Secrets and variables → Actions → *New repository secret*,
   und dort `TMDB_API_KEY` bzw. `YOUTUBE_API_KEY` eintragen.

## Lokal ausprobieren (für Neugierige)

```bash
pip install -r collector/requirements.txt
python collector/collect.py
cd docs && python -m http.server 8000   # dann http://localhost:8000 öffnen
```
