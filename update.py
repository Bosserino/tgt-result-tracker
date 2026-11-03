#!/usr/bin/env python3
"""Build site/data.json with the TGT roster's VGC results from Pokedata.

For every VGC Regional / International / World event on Pokedata that starts on
or after config.since, finds the configured players in the Masters standings,
takes record, placement and top bracket, pulls their team list and stores the
Pokémon Champions menu icon (PokeAPI sprites) of each of the 6 Pokémon locally
so the page can offer them as same-origin downloads.

Standard library only. Run: python3 update.py
"""
import json
import math
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
SPRITES = SITE / "sprites"
CACHE = ROOT / "cache"
DATA = SITE / "data.json"

POKEDATA = "https://www.pokedata.ovh/standings2/"
SPECIES = "https://pokeapi.co/api/v2/pokemon-species/{}"
ICON = ("https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/"
        "pokemon/versions/generation-ix/champions/icons/{}.png")
EVENT_KINDS = {
    "Regional Championships": "Regional",
    "International Championships": "International",
    "World Championship": "Worlds",
}
MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}
HEADERS = {"User-Agent": "TGT-Result-Tracker/1.0"}


def fetch(url, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as res:
                return res.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if attempt == retries - 1:
                raise
        except urllib.error.URLError:
            if attempt == retries - 1:
                raise
        time.sleep(2 * (attempt + 1))


def fetch_json(url):
    body = fetch(url)
    return json.loads(body) if body else None


def name_key(name):
    """Order-insensitive, accent/apostrophe-insensitive key: "Nicolo' Venturin" == "Nicolò Venturin"."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"['’`´.]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(sorted(s.split()))


def start_date(text):
    """'October 31-November 1, 2026' -> date(2026, 10, 31)."""
    months = [m for m in re.findall(r"[A-Za-z]+", text) if m in MONTHS]
    day = int(re.search(r"[A-Za-z]+\s+(\d+)", text).group(1))
    year = int(re.search(r"(\d{4})\s*$", text).group(1))
    if len(months) > 1 and MONTHS[months[0]] > MONTHS[months[1]]:
        year -= 1  # event across new year, the printed year is the end date's
    return date(year, MONTHS[months[0]], day)


def list_events(since):
    html = fetch(POKEDATA).decode("utf-8")
    pattern = re.compile(
        r'<div class="tournament vg"[^>]*><div class="title">([^<]*)</div>'
        r'<div class="dates">([^<]*)</div>.*?name="id" value="(\d+)"', re.S)
    events = []
    for title, dates, eid in pattern.findall(html):
        kind = next((v for k, v in EVENT_KINDS.items() if k in title), None)
        if not kind:
            continue
        start = start_date(dates)
        if start >= since:
            events.append({"id": eid, "title": title, "date": dates,
                           "start": start.isoformat(), "kind": kind})
    return events


def top_label(place):
    if place == 1:
        return "Campione"
    if place == 2:
        return "Finalista"
    return f"Top {2 ** math.ceil(math.log2(place))}"


# --- sprites ---------------------------------------------------------------

FORMS_CACHE = CACHE / "forms.json"
STOPWORDS = {"form", "of", "the"}


def tokens(text):
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t and t not in STOPWORDS}


def token_match(a, b):
    return a == b or (min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)))


def resolve_form(dex, name):
    """Pick the PokeAPI variety matching Pokedata's '[Form]' label, default otherwise."""
    species = fetch_json(SPECIES.format(int(dex)))
    varieties = species["varieties"]
    default = next(v for v in varieties if v["is_default"])
    label = re.search(r"\[(.*)\]", name)
    best, best_score = default, 0
    if label:
        wanted = tokens(label.group(1))
        base = tokens(species["name"])
        for v in varieties:
            vt = tokens(v["pokemon"]["name"]) - base
            score = sum(any(token_match(w, t) for t in vt) for w in wanted)
            if score > best_score:
                best, best_score = v, score
    pid = int(best["pokemon"]["url"].rstrip("/").split("/")[-1])
    default_id = int(default["pokemon"]["url"].rstrip("/").split("/")[-1])
    return {"id": pid, "slug": best["pokemon"]["name"], "fallback": default_id}


class Sprites:
    def __init__(self):
        self.forms = json.loads(FORMS_CACHE.read_text()) if FORMS_CACHE.exists() else {}
        SPRITES.mkdir(parents=True, exist_ok=True)

    def get(self, dex, name):
        key = f"{int(dex)}|{name}"
        if key not in self.forms:
            self.forms[key] = resolve_form(dex, name)
        form = self.forms[key]
        path = SPRITES / f"{form['slug']}.png"
        if not path.exists():
            body = fetch(ICON.format(form["id"])) or fetch(ICON.format(form["fallback"]))
            if not body:
                print(f"  ! no Champions icon for {name}", file=sys.stderr)
                return None
            path.write_bytes(body)
        return f"sprites/{path.name}"

    def save(self):
        CACHE.mkdir(exist_ok=True)
        FORMS_CACHE.write_text(json.dumps(self.forms, indent=1, sort_keys=True))


# --- events ----------------------------------------------------------------

def build_event(event, division, wanted, sprites):
    standings = fetch_json(f"{POKEDATA}standings/{event['id']}_{division}.json")
    if not standings:
        return None  # not started yet
    roster = fetch_json(f"{POKEDATA}RosterData/{event['id']}.json") or []
    teams = {}
    for entry in roster:
        if entry.get("d") == division[0] and entry.get("tl"):
            teams.setdefault(name_key(entry["n"]), entry["tl"])

    info = standings["tournament"]
    players = standings["standings"]["players"]
    day1 = info.get("day1") or 0
    leader = players[0] if players else {}
    bracket = leader.get("bracket_size")
    complete = bool(bracket) and len(leader.get("r", [])) >= (
        day1 + (info.get("day2") or 0) + int(math.log2(bracket)))

    results = []
    for index, p in enumerate(players):
        key = name_key(p["n"])
        if key not in wanted:
            continue
        place = index + 1
        wins, losses, ties = (p.get("s") or [0, 0, 0])[:3]
        team = []
        for mon in teams.get(key, [])[:6]:
            dex, _form, _nature, _tera, ability, name, item = mon[:7]
            team.append({"name": name, "item": item, "ability": ability,
                         "sprite": sprites.get(dex, name)})
        results.append({
            "name": wanted[key],
            "country": p.get("c"),
            "place": place,
            "record": f"{wins}-{losses}" + (f"-{ties}" if ties else ""),
            "top": top_label(place),
            "day2": bool(info.get("day2")) and len(p.get("r", [])) > day1,
            "topcut": p.get("top_cut_seed") is not None,
            "team": team,
        })

    return {**event, "complete": complete, "entrants": len(players),
            "url": f"{POKEDATA}{event['id']}/{division}", "results": results}


def main():
    config = json.loads((ROOT / "config.json").read_text())
    since = date.fromisoformat(config["since"])
    division = config.get("division", "Masters")
    wanted = {name_key(n): n for n in config["players"]}
    sprites = Sprites()
    event_cache = CACHE / "events"
    event_cache.mkdir(parents=True, exist_ok=True)

    events = []
    for event in list_events(since):
        cached = event_cache / f"{event['id']}.json"
        if cached.exists():
            built = json.loads(cached.read_text())
            if built.get("players_hash") == sorted(wanted):
                print(f"= {event['title']} (finished, cached)")
                events.append(built["event"])
                continue
        print(f"> {event['title']}")
        built = build_event(event, division, wanted, sprites)
        if built is None:
            continue
        if built["complete"]:
            cached.write_text(json.dumps({"players_hash": sorted(wanted), "event": built}))
        events.append(built)
        for r in built["results"]:
            print(f"    {r['name']}: {r['record']} {r['place']}° {r['top']}")
    sprites.save()

    events = [e for e in events if e["results"]]
    events.sort(key=lambda e: (e["start"], e["id"]), reverse=True)

    previous = json.loads(DATA.read_text()) if DATA.exists() else {}
    if previous.get("events") == events:
        print("No changes.")
        return
    SITE.mkdir(exist_ok=True)
    DATA.write_text(json.dumps({
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "events": events,
    }, ensure_ascii=False, indent=1))
    print(f"Wrote {DATA.relative_to(ROOT)} ({len(events)} events).")


if __name__ == "__main__":
    main()
