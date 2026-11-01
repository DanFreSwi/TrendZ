"""
TrendZ – der Sammler.

Dieses Programm holt die aktuellen Trends aus offiziellen, frei nutzbaren
Quellen (RSS-Feeds und APIs), wählt pro Kategorie die Top 3 aus und speichert
das Ergebnis als Datei:

    docs/data/latest.json          -> wird von der Website angezeigt
    docs/data/archiv/JJJJ-MM-TT.json -> Archiv: was war an diesem Tag Trend?

Es läuft automatisch alle paar Stunden über GitHub Actions
(siehe .github/workflows/sammeln.yml). Du musst es nicht selbst starten.

Faire Regeln, an die sich der Sammler hält:
  * nur offizielle Feeds und Schnittstellen, kein Abgrasen fremder Webseiten
  * robots.txt wird respektiert
  * nur Titel, kurzer Text, Bild-Link und Link zum Original werden gespeichert
  * eine Quelle, die nicht antwortet, wird einfach übersprungen
"""

from __future__ import annotations

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib import robotparser
from urllib.parse import quote_plus, urlparse

import feedparser
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# Einstellungen
# ---------------------------------------------------------------------------

LAND = "ch"  # Schweiz
TOP_N = 3
TIMEOUT = 20  # Sekunden, bevor wir eine Quelle aufgeben

# So stellt sich der Sammler bei den Quellen vor (höflich und ehrlich).
USER_AGENT = "TrendZ-Sammler/1.0 (nicht-kommerzielles Hobbyprojekt; https://github.com/DanFreSwi/TrendZ)"

# Schlüssel für Quellen, die eine (kostenlose) Anmeldung brauchen.
# Sie werden als "Secrets" in GitHub hinterlegt, nie direkt hier im Code.
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "").strip()
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()

# News-Quellen. Du kannst hier jederzeit Quellen ergänzen oder entfernen.
NEWS_SCHWEIZ = [
    ("SRF", "https://www.srf.ch/news/bnf/rss/1646"),
    ("Blick", "https://www.blick.ch/news/rss.xml"),
    ("20 Minuten", "https://partner-feeds.20min.ch/rss/20minuten"),
    ("watson", "https://www.watson.ch/api/1.0/rss/index.xml"),
]

NEWS_WELT = [
    ("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("The Guardian", "https://www.theguardian.com/world/rss"),
    ("tagesschau", "https://www.tagesschau.de/infoservices/alle-meldungen-100~rss2.xml"),
]

PROJEKT_ORDNER = Path(__file__).resolve().parent.parent
DATEN_ORDNER = PROJEKT_ORDNER / "docs" / "data"

session = requests.Session()
session.headers["User-Agent"] = USER_AGENT
# Antwortet eine Quelle einmal nicht, versuchen wir es kurz darauf nochmals.
_nochmal = Retry(total=2, backoff_factor=3, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
session.mount("https://", HTTPAdapter(max_retries=_nochmal))


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def log(text: str) -> None:
    print(text, flush=True)


_robots_cache: dict[str, robotparser.RobotFileParser | None] = {}


def erlaubt(url: str) -> bool:
    """Prüft in der robots.txt der Website, ob wir diese Adresse abrufen dürfen."""
    teile = urlparse(url)
    basis = f"{teile.scheme}://{teile.netloc}"
    if basis not in _robots_cache:
        parser = robotparser.RobotFileParser()
        try:
            antwort = session.get(basis + "/robots.txt", timeout=TIMEOUT)
            if antwort.status_code in (401, 403):
                parser.disallow_all = True
            elif antwort.ok:
                parser.parse(antwort.text.splitlines())
            else:
                parser.allow_all = True  # keine robots.txt = keine Einschränkung
            _robots_cache[basis] = parser
        except requests.RequestException:
            _robots_cache[basis] = None  # nicht erreichbar, Quelle wird ohnehin scheitern
    parser = _robots_cache[basis]
    return parser is None or parser.can_fetch(USER_AGENT, url)


def text_kuerzen(text: str, laenge: int = 180) -> str:
    """Entfernt HTML und kürzt einen Text auf eine Teaser-Länge."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > laenge:
        text = text[: laenge - 1].rsplit(" ", 1)[0] + " …"
    return text


def eintrag(titel, link, quelle, untertitel="", bild="", info=""):
    """Ein einheitlicher Eintrag, egal aus welcher Quelle er kommt."""
    return {
        "titel": (titel or "").strip(),
        "untertitel": (untertitel or "").strip(),
        "link": link or "",
        "bild": bild or "",
        "quelle": quelle,
        "info": info,
    }


def bild_aus_feed(item) -> str:
    for feld in ("media_thumbnail", "media_content"):
        werte = item.get(feld) or []
        for wert in werte:
            if wert.get("url"):
                return wert["url"]
    for anhang in item.get("enclosures", []) or []:
        if str(anhang.get("type", "")).startswith("image") and anhang.get("href"):
            return anhang["href"]
    treffer = re.search(r'<img[^>]+src="([^"]+)"', item.get("summary", "") or "")
    return treffer.group(1) if treffer else ""


# ---------------------------------------------------------------------------
# News: welche Geschichten sind gerade am wichtigsten?
# ---------------------------------------------------------------------------
# Idee: Eine Geschichte, über die mehrere Redaktionen gleichzeitig berichten,
# ist wichtiger als eine, die nur eine Zeitung bringt. Wir vergleichen dafür
# die Wörter in den Schlagzeilen.

STOPPWOERTER = set(
    """
    aber alle allen als also auch auf aus bei beim bis dass dem den der des die
    dies diese dieser doch durch eine einem einen einer eines fuer für gegen
    hat hatte haben hier ihre ihr ist jetzt kann kein keine mehr mit nach neue
    neuen nicht noch nun nur oder ohne schon sein seine sich sie sind soll über
    ueber und uns unter vom von vor war was weil wenn werden wie wieder will wir
    wird zum zur zwei drei news live ticker video bilder schweiz
    about after again against also amid been before being from have into more
    over says said than that their them then there they this what when where
    which while will with would your world first last year years
    """.split()
)


def stichwoerter(text: str) -> set[str]:
    woerter = re.findall(r"[a-zA-ZäöüÄÖÜàéèçÀÉÈ]{4,}", text.lower())
    return {w for w in woerter if w not in STOPPWOERTER}


def news_top(quellen: list[tuple[str, str]], pro_quelle: int = 15) -> list[dict]:
    artikel = []
    for name, url in quellen:
        if not erlaubt(url):
            log(f"  - {name}: robots.txt erlaubt den Abruf nicht, übersprungen")
            continue
        try:
            antwort = session.get(url, timeout=TIMEOUT)
            antwort.raise_for_status()
        except requests.RequestException as fehler:
            log(f"  - {name}: nicht erreichbar ({fehler}), übersprungen")
            continue
        feed = feedparser.parse(antwort.content)
        anzahl = 0
        for position, item in enumerate(feed.entries[:pro_quelle]):
            titel = item.get("title", "")
            link = item.get("link", "")
            if not titel or not link or link.endswith("/undefined"):
                continue
            artikel.append(
                {
                    "eintrag": eintrag(
                        titel,
                        link,
                        name,
                        untertitel=text_kuerzen(item.get("summary", "")),
                        bild=bild_aus_feed(item),
                    ),
                    "woerter": stichwoerter(titel + " " + text_kuerzen(item.get("summary", ""), 150)),
                    "position": position,
                }
            )
            anzahl += 1
        log(f"  - {name}: {anzahl} Artikel")

    # Für jeden Artikel zählen: wie viele ANDERE Quellen berichten Ähnliches?
    for a in artikel:
        andere_quellen = {
            b["eintrag"]["quelle"]
            for b in artikel
            if b["eintrag"]["quelle"] != a["eintrag"]["quelle"] and len(a["woerter"] & b["woerter"]) >= 2
        }
        a["quellen"] = 1 + len(andere_quellen)

    # Sortieren: zuerst nach Anzahl Quellen, dann nach Position im Feed (neu = oben).
    artikel.sort(key=lambda a: (-a["quellen"], a["position"]))

    auswahl = []
    for a in artikel:
        # Dieselbe Geschichte nicht zweimal zeigen.
        if any(len(a["woerter"] & b["woerter"]) >= 2 for b in auswahl):
            continue
        a["eintrag"]["info"] = (
            f"{a['quellen']} Quellen berichten" if a["quellen"] > 1 else "Neu"
        )
        auswahl.append(a)
        if len(auswahl) == TOP_N:
            break
    return [a["eintrag"] for a in auswahl]


# ---------------------------------------------------------------------------
# Restaurants & Bars in den News
# ---------------------------------------------------------------------------
# Google und Apple geben keine Klickzahlen von Maps heraus. Stattdessen suchen
# wir in den Schweizer News nach Artikeln über Restaurants, Bars und Gastro.

GASTRO_MUSTER = re.compile(
    r"\b(restaurants?|beiz|beizen|gastro\w*|gastronom\w*|bars?|cocktail\w*|café|cafés|kaffee|"
    r"brunch|köch(?:e|in|innen)?|spitzenkoch|michelin|gault|millau|sterneküche|"
    r"burger|pizzeria|pizza|bistro|food|foodtruck|wein\w*|bier\w*|brauerei|"
    r"neueröffnung\w*|sterne?koch\w*)\b",
    re.IGNORECASE,
)


def gastro_news() -> list[dict]:
    treffer = []
    for name, url in NEWS_SCHWEIZ:
        if not erlaubt(url):
            continue
        try:
            antwort = session.get(url, timeout=TIMEOUT)
            antwort.raise_for_status()
        except requests.RequestException as fehler:
            log(f"  - {name}: nicht erreichbar ({fehler}), übersprungen")
            continue
        for position, item in enumerate(feedparser.parse(antwort.content).entries):
            titel = item.get("title", "")
            link = item.get("link", "")
            teaser = text_kuerzen(item.get("summary", ""))
            if not titel or not link or link.endswith("/undefined"):
                continue
            # Ein Treffer im Titel zählt doppelt so viel wie einer im Teaser.
            punkte = 2 * len(GASTRO_MUSTER.findall(titel)) + len(GASTRO_MUSTER.findall(teaser))
            if punkte >= 2:
                treffer.append(
                    {
                        "eintrag": eintrag(titel, link, name, untertitel=teaser, bild=bild_aus_feed(item)),
                        "woerter": stichwoerter(titel),
                        "punkte": punkte,
                        "position": position,
                    }
                )
    log(f"  - {len(treffer)} Gastro-Artikel gefunden")
    treffer.sort(key=lambda t: (-t["punkte"], t["position"]))
    auswahl = []
    for t in treffer:
        if any(len(t["woerter"] & a["woerter"]) >= 2 for a in auswahl):
            continue
        auswahl.append(t)
        if len(auswahl) == TOP_N:
            break
    return [t["eintrag"] for t in auswahl]


# ---------------------------------------------------------------------------
# Die übrigen Kategorien
# ---------------------------------------------------------------------------

def google_suchtrends() -> list[dict]:
    """Was in der Schweiz gerade bei Google gesucht wird."""
    url = f"https://trends.google.com/trending/rss?geo={LAND.upper()}"
    if not erlaubt(url):
        return []
    antwort = session.get(url, timeout=TIMEOUT)
    antwort.raise_for_status()
    ns = {"ht": "https://trends.google.com/trending/rss"}
    wurzel = ET.fromstring(antwort.content)
    ergebnis = []
    for item in wurzel.iter("item"):
        suchbegriff = item.findtext("title", "")
        menge = item.findtext("ht:approx_traffic", "", ns)
        news = item.find("ht:news_item", ns)
        untertitel, link, quelle = "", "", "Google Trends"
        if news is not None:
            untertitel = news.findtext("ht:news_item_title", "", ns)
            link = news.findtext("ht:news_item_url", "", ns)
            quelle = f"Google Trends · {news.findtext('ht:news_item_source', '', ns)}".rstrip(" ·")
        if not link:
            link = "https://www.google.ch/search?q=" + quote_plus(suchbegriff)
        ergebnis.append(
            eintrag(
                suchbegriff,
                link,
                quelle,
                untertitel=text_kuerzen(untertitel),
                bild=item.findtext("ht:picture", "", ns),
                info=f"{menge} Suchanfragen" if menge else "",
            )
        )
    return ergebnis[:TOP_N]


def apple_charts(art: str) -> list[dict]:
    """Offizielle Apple-Charts für die Schweiz (Musik oder Podcasts)."""
    if art == "musik":
        url = f"https://rss.marketingtools.apple.com/api/v2/{LAND}/music/most-played/10/songs.json"
        quelle = "Apple Music Charts CH"
    else:
        url = f"https://rss.marketingtools.apple.com/api/v2/{LAND}/podcasts/top/10/podcasts.json"
        quelle = "Apple Podcasts Charts CH"
    antwort = session.get(url, timeout=TIMEOUT)
    antwort.raise_for_status()
    ergebnis = []
    for platz, r in enumerate(antwort.json()["feed"]["results"][:TOP_N], start=1):
        bild = (r.get("artworkUrl100") or "").replace("100x100", "300x300")
        genres = ", ".join(g["name"] for g in r.get("genres", []) if g.get("name") not in ("Musik", "Music", "Podcasts"))
        ergebnis.append(
            eintrag(r.get("name"), r.get("url"), quelle, untertitel=r.get("artistName", ""), bild=bild, info=genres)
        )
    return ergebnis


def filme() -> list[dict]:
    """Die beliebtesten Filme, die gerade in Schweizer Kinos laufen (TMDB)."""
    if not TMDB_API_KEY:
        log("  - kein TMDB_API_KEY hinterlegt, Filme übersprungen")
        return []
    antwort = session.get(
        "https://api.themoviedb.org/3/movie/now_playing",
        params={"api_key": TMDB_API_KEY, "region": LAND.upper(), "language": "de-CH"},
        timeout=TIMEOUT,
    )
    antwort.raise_for_status()
    resultate = sorted(antwort.json().get("results", []), key=lambda f: -f.get("popularity", 0))
    ergebnis = []
    for f in resultate[:TOP_N]:
        bild = f"https://image.tmdb.org/t/p/w300{f['poster_path']}" if f.get("poster_path") else ""
        bewertung = f.get("vote_average") or 0
        ergebnis.append(
            eintrag(
                f.get("title"),
                f"https://www.themoviedb.org/movie/{f['id']}",
                "TMDB · im Kino in der Schweiz",
                untertitel=text_kuerzen(f.get("overview", ""), 140),
                bild=bild,
                info=f"★ {bewertung:.1f}" if bewertung else "",
            )
        )
    return ergebnis


def videos() -> list[dict]:
    """Die beliebtesten YouTube-Videos in der Schweiz."""
    if not YOUTUBE_API_KEY:
        log("  - kein YOUTUBE_API_KEY hinterlegt, Videos übersprungen")
        return []
    antwort = session.get(
        "https://www.googleapis.com/youtube/v3/videos",
        params={
            "part": "snippet,statistics",
            "chart": "mostPopular",
            "regionCode": LAND.upper(),
            "maxResults": TOP_N,
            "key": YOUTUBE_API_KEY,
        },
        timeout=TIMEOUT,
    )
    antwort.raise_for_status()
    ergebnis = []
    for v in antwort.json().get("items", []):
        s = v["snippet"]
        aufrufe = int(v.get("statistics", {}).get("viewCount", 0))
        bilder = s.get("thumbnails", {})
        bild = (bilder.get("high") or bilder.get("medium") or bilder.get("default") or {}).get("url", "")
        ergebnis.append(
            eintrag(
                s.get("title"),
                f"https://www.youtube.com/watch?v={v['id']}",
                "YouTube · beliebt in der Schweiz",
                untertitel=s.get("channelTitle", ""),
                bild=bild,
                info=f"{aufrufe:,} Aufrufe".replace(",", "'") if aufrufe else "",
            )
        )
    return ergebnis


# ---------------------------------------------------------------------------
# Alles zusammen
# ---------------------------------------------------------------------------

KATEGORIEN = [
    # (Schlüssel, Name auf der Website, Symbol, Funktion)
    ("news_ch", "News Schweiz", "🇨🇭", lambda: news_top(NEWS_SCHWEIZ)),
    ("news_welt", "News Welt", "🌍", lambda: news_top(NEWS_WELT)),
    ("suche", "Gesucht in der Schweiz", "🔎", google_suchtrends),
    ("musik", "Musik", "🎵", lambda: apple_charts("musik")),
    ("podcasts", "Podcasts", "🎙️", lambda: apple_charts("podcasts")),
    ("gastro", "Restaurants & Bars", "🍽️", gastro_news),
    # Vorerst ausgeschaltet. Zum Einschalten die "#" entfernen und die
    # Schlüssel TMDB_API_KEY bzw. YOUTUBE_API_KEY in GitHub hinterlegen.
    # ("filme", "Filme im Kino", "🎬", filme),
    # ("videos", "Videos", "▶️", videos),
]


def vorherige_daten() -> dict:
    datei = DATEN_ORDNER / "latest.json"
    if datei.exists():
        try:
            return {k["id"]: k for k in json.loads(datei.read_text("utf-8")).get("kategorien", [])}
        except (json.JSONDecodeError, KeyError):
            pass
    return {}


def main() -> int:
    jetzt = datetime.now(timezone.utc)
    alt = vorherige_daten()
    kategorien = []
    erfolgreich = 0

    for schluessel, name, symbol, funktion in KATEGORIEN:
        log(f"{symbol} {name} …")
        try:
            eintraege = funktion()
        except Exception as fehler:  # eine kaputte Quelle soll nie alles stoppen
            log(f"  ! Fehler: {fehler}")
            eintraege = []

        if eintraege:
            erfolgreich += 1
            stand = jetzt.isoformat(timespec="seconds")
        elif schluessel in alt and alt[schluessel].get("eintraege"):
            # Lieber die letzten bekannten Trends zeigen als eine leere Kachel.
            log("  -> nichts Neues erhalten, letzte bekannte Daten bleiben stehen")
            eintraege = alt[schluessel]["eintraege"]
            stand = alt[schluessel].get("stand")
        else:
            stand = None

        kategorien.append(
            {"id": schluessel, "name": name, "symbol": symbol, "stand": stand, "eintraege": eintraege}
        )

    daten = {"aktualisiert": jetzt.isoformat(timespec="seconds"), "land": LAND, "kategorien": kategorien}

    DATEN_ORDNER.mkdir(parents=True, exist_ok=True)
    (DATEN_ORDNER / "archiv").mkdir(exist_ok=True)
    inhalt = json.dumps(daten, ensure_ascii=False, indent=2)
    (DATEN_ORDNER / "latest.json").write_text(inhalt + "\n", "utf-8")
    (DATEN_ORDNER / "archiv" / f"{jetzt:%Y-%m-%d}.json").write_text(inhalt + "\n", "utf-8")

    log(f"Fertig: {erfolgreich} von {len(KATEGORIEN)} Kategorien frisch aktualisiert.")
    return 0 if erfolgreich else 1


if __name__ == "__main__":
    sys.exit(main())
