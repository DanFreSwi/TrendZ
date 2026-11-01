// TrendZ – zeigt die gesammelten Trends aus data/latest.json an.

function vorWieLange(iso) {
  if (!iso) return "";
  const minuten = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (minuten < 1) return "gerade eben";
  if (minuten < 60) return `vor ${minuten} Min.`;
  const stunden = Math.round(minuten / 60);
  if (stunden < 24) return `vor ${stunden} Std.`;
  const tage = Math.round(stunden / 24);
  return tage === 1 ? "vor 1 Tag" : `vor ${tage} Tagen`;
}

function element(tag, klasse, text) {
  const el = document.createElement(tag);
  if (klasse) el.className = klasse;
  if (text) el.textContent = text;
  return el;
}

function eintragBauen(e, platz, symbol) {
  const li = document.createElement("li");
  const a = element("a", "eintrag");
  a.href = e.link;
  a.target = "_blank";
  a.rel = "noopener noreferrer";

  const platzBox = element("span", "platz", String(platz));
  const TRENDS = {
    neu: ["NEU", "Neu seit gestern"],
    hoch: ["▲", "Gestiegen seit gestern"],
    runter: ["▼", "Gefallen seit gestern"],
    gleich: ["=", "Gleich wie gestern"],
  };
  if (TRENDS[e.trend]) {
    const [zeichen, erklaerung] = TRENDS[e.trend];
    const marke = element("span", `trend trend-${e.trend}`, zeichen);
    marke.title = erklaerung;
    platzBox.append(marke);
  }
  a.append(platzBox);

  if (e.emoji) {
    a.append(element("span", "bild leer", e.emoji));
  } else if (e.bild) {
    const img = element("img", "bild");
    img.src = e.bild;
    img.alt = "";
    img.loading = "lazy";
    img.referrerPolicy = "no-referrer";
    img.onerror = () => img.replaceWith(element("span", "bild leer", symbol));
    a.append(img);
  } else {
    a.append(element("span", "bild leer", symbol));
  }

  const text = element("span", "text");
  text.append(element("span", "titel", e.titel));
  if (e.untertitel) text.append(element("span", "untertitel", e.untertitel));
  const meta = [e.quelle, e.info].filter(Boolean).join(" · ");
  if (meta) text.append(element("span", "meta", meta));
  a.append(text);

  li.append(a);
  return li;
}

function datumSchoen(tag) {
  const [j, m, t] = tag.split("-").map(Number);
  return new Date(j, m - 1, t).toLocaleDateString("de-CH", {
    weekday: "short", day: "numeric", month: "long", year: "numeric",
  });
}

async function archivListeLaden() {
  try {
    const antwort = await fetch("data/archiv/index.json", { cache: "no-store" });
    if (!antwort.ok) return;
    const { tage } = await antwort.json();
    if (!tage.length) return;
    const auswahl = document.getElementById("archiv-tag");
    for (const tag of tage) {
      const option = document.createElement("option");
      option.value = tag;
      option.textContent = `Tagesabschluss ${datumSchoen(tag)}`;
      auswahl.append(option);
    }
    auswahl.value = tage.includes(location.hash.slice(1)) ? location.hash.slice(1) : "";
    document.getElementById("archiv-wahl").hidden = false;
  } catch (fehler) {
    console.error(fehler);
  }
}

async function laden() {
  const bereich = document.getElementById("kacheln");
  const stand = document.getElementById("stand");
  const tag = location.hash.slice(1);
  const istArchiv = /^\d{4}-\d{2}-\d{2}$/.test(tag);
  const datei = istArchiv ? `data/archiv/${tag}.json` : "data/latest.json";
  try {
    const antwort = await fetch(datei, { cache: "no-store" });
    if (!antwort.ok) throw new Error(antwort.status);
    const daten = await antwort.json();

    stand.classList.toggle("archiv", istArchiv);
    if (istArchiv) {
      stand.textContent = `Archiv: So sah es am ${datumSchoen(tag)} beim Tagesabschluss (ca. 22:17 Uhr) aus`;
    } else {
      stand.textContent = daten.aktualisiert
        ? `Aktualisiert ${vorWieLange(daten.aktualisiert)}`
        : "Die ersten Trends werden gerade gesammelt …";
    }
    const vorlage = document.getElementById("kachel-vorlage");
    bereich.replaceChildren();

    for (const k of daten.kategorien) {
      const kachel = vorlage.content.cloneNode(true);
      kachel.querySelector(".symbol").textContent = k.symbol;
      kachel.querySelector(".name").textContent = k.name;
      const liste = kachel.querySelector(".liste");
      if (k.eintraege.length) {
        k.eintraege.forEach((e, i) => liste.append(eintragBauen(e, i + 1, k.symbol)));
        if (!istArchiv) kachel.querySelector(".kachel-stand").textContent = `Stand: ${vorWieLange(k.stand)}`;
      } else {
        liste.replaceWith(element("p", "bald", istArchiv ? "Keine Einträge an diesem Tag." : "Kommt bald …"));
      }
      bereich.append(kachel);
    }
  } catch (fehler) {
    stand.textContent = "Die Trends konnten gerade nicht geladen werden. Bitte später nochmals versuchen.";
    console.error(fehler);
  }
}

document.getElementById("archiv-tag").addEventListener("change", (ereignis) => {
  location.hash = ereignis.target.value;
  if (!ereignis.target.value) history.replaceState(null, "", location.pathname);
  laden();
});
window.addEventListener("hashchange", laden);

archivListeLaden();
laden();
