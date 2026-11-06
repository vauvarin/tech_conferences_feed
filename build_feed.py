#!/usr/bin/env python3
"""
Génère un flux Atom stable des NOUVELLES conférences de developers.events.

Principe : la source n'a ni date d'ajout ni id stable. On garde donc dans
state.json la date de première apparition de chaque événement, et on s'en
sert comme <published>/<updated>. Rien d'autre que la bibliothèque standard.

Premier lancement : tous les événements déjà présents sont enregistrés comme
"baseline" et n'apparaissent pas dans le flux (sinon Mastofeed risquerait de
poster des centaines de toots d'un coup). Seuls les ajouts ultérieurs sont publiés.
"""
import argparse
import hashlib
import json
import re
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

SOURCE = "https://developers.events/feed-events.json"
BASELINE = "baseline"
DATE_RE = re.compile(r"[A-Z][a-z]{2} [A-Z][a-z]{2} \d{2} \d{4}")


def load_source(src):
    if src.startswith("http"):
        req = urllib.request.Request(src, headers={"User-Agent": "conf-feed-builder/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    return json.loads(Path(src).read_text(encoding="utf-8"))


def parse_item(item):
    """content_html = '<titre> @ <lieu> - Mon Jan 05 2026 00:00:00 GMT+0000 (...)'"""
    title = (item.get("title") or "").strip()
    url = (item.get("url") or "").strip()
    html = item.get("content_html") or ""
    matches = list(DATE_RE.finditer(html))
    if not (title and url and matches):
        return None
    m = matches[-1]
    start = datetime.strptime(m.group(0), "%a %b %d %Y").date()

    head = html[: m.start()]
    if head.startswith(title):
        head = head[len(title):]
    head = head.strip()
    if head.endswith("-"):
        head = head[:-1].strip()
    place = head.lstrip("@").strip()

    # Clé stable : indépendante de la position dans le flux source.
    # L'année évite qu'une édition 2027 soit prise pour un doublon de 2026.
    raw = f"{title.lower()}|{place.lower()}|{start.year}"
    key = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return key, {"title": title, "url": url, "place": place, "start": start.isoformat()}


def q(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def build_atom(entries, feed_url, updated):
    out = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"  <id>{q(feed_url)}</id>",
        "  <title>Developer Conferences : nouveautés</title>",
        f"  <updated>{updated}</updated>",
        f'  <link rel="self" href="{q(feed_url)}"/>',
        '  <link rel="alternate" href="https://developers.events/"/>',
        "  <rights>Données : developers.events (CC BY-NC 4.0)</rights>",
        "  <author><name>developers.events</name><uri>https://developers.events</uri></author>",
    ]
    for key, ev in entries:
        d = date.fromisoformat(ev["start"]).strftime("%d/%m/%Y")
        title = f'{ev["title"]} — {ev["place"]} — {d}'
        out += [
            "  <entry>",
            f"    <id>urn:developers-events:{key}</id>",
            f"    <title>{q(title)}</title>",
            f'    <link href="{q(ev["url"])}"/>',
            f'    <published>{ev["first_seen"]}</published>',
            f'    <updated>{ev["first_seen"]}</updated>',
            f"    <summary>{q(title)}</summary>",
            "  </entry>",
        ]
    out.append("</feed>")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=SOURCE, help="URL ou fichier JSON Feed")
    ap.add_argument("--state", default="state.json")
    ap.add_argument("--out", default="feed.xml")
    ap.add_argument("--feed-url", default="https://example.github.io/conf-feed/feed.xml")
    ap.add_argument("--limit", type=int, default=30, help="nb max d'entrées dans le flux")
    args = ap.parse_args()

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    state_path = Path(args.state)
    first_run = not state_path.exists()
    state = (json.loads(state_path.read_text(encoding="utf-8"))
             if not first_run else {"created": now, "events": {}})
    events = state["events"]

    new = 0
    for item in load_source(args.source).get("items", []):
        parsed = parse_item(item)
        if not parsed:
            continue
        key, ev = parsed
        if key in events:
            continue  # déjà vu : on ne touche ni à la date ni au contenu
        ev["first_seen"] = BASELINE if first_run else now
        events[key] = ev
        new += 1

    state_path.write_text(json.dumps(state, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
                          encoding="utf-8")

    today = date.today().isoformat()
    fresh = [(k, e) for k, e in events.items()
             if e["first_seen"] != BASELINE and e["start"] >= today]
    fresh.sort(key=lambda ke: (ke[1]["first_seen"], ke[0]), reverse=True)
    fresh = fresh[: args.limit]

    # <updated> du flux = dernière nouveauté (stable tant que rien ne change)
    stamps = [e["first_seen"] for e in events.values() if e["first_seen"] != BASELINE]
    updated = max(stamps) if stamps else state["created"]

    Path(args.out).write_text(build_atom(fresh, args.feed_url, updated), encoding="utf-8")
    print(f"{new} nouvel(s) événement(s) vu(s), {len(fresh)} entrée(s) dans le flux"
          + (" (premier lancement : baseline enregistrée)" if first_run else ""))


if __name__ == "__main__":
    main()
