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

  a.append(element("span", "platz", String(platz)));

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

async function laden() {
  const bereich = document.getElementById("kacheln");
  const stand = document.getElementById("stand");
  try {
    const antwort = await fetch("data/latest.json", { cache: "no-store" });
    if (!antwort.ok) throw new Error(antwort.status);
    const daten = await antwort.json();

    stand.textContent = daten.aktualisiert
      ? `Aktualisiert ${vorWieLange(daten.aktualisiert)}`
      : "Die ersten Trends werden gerade gesammelt …";
    const vorlage = document.getElementById("kachel-vorlage");
    bereich.replaceChildren();

    for (const k of daten.kategorien) {
      const kachel = vorlage.content.cloneNode(true);
      kachel.querySelector(".symbol").textContent = k.symbol;
      kachel.querySelector(".name").textContent = k.name;
      const liste = kachel.querySelector(".liste");
      if (k.eintraege.length) {
        k.eintraege.forEach((e, i) => liste.append(eintragBauen(e, i + 1, k.symbol)));
        kachel.querySelector(".kachel-stand").textContent = `Stand: ${vorWieLange(k.stand)}`;
      } else {
        liste.replaceWith(element("p", "bald", "Kommt bald …"));
      }
      bereich.append(kachel);
    }
  } catch (fehler) {
    stand.textContent = "Die Trends konnten gerade nicht geladen werden. Bitte später nochmals versuchen.";
    console.error(fehler);
  }
}

laden();
