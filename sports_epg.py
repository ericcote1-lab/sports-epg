#!/usr/bin/env python3
"""Build an XMLTV guide with one channel per team (NHL, NBA, NFL, MLB, AHL, LHJMQ).

Each team channel gets a programme for every game (title "Away @ Home") and
"Next game" filler between games, so the guide is never empty.

Usage:  python sports_epg.py [output_dir]
Writes  <output_dir>/sports.xml, sports.xml.gz and teams.json
Standard library only.
"""
import datetime as dt
import gzip
import json
import os
import sys
import urllib.request
from xml.sax.saxutils import escape

UTC = dt.timezone.utc
NOW = dt.datetime.now(UTC)
WINDOW_START = (NOW - dt.timedelta(hours=12)).replace(minute=0, second=0, microsecond=0)
DAYS_AHEAD = 7
WINDOW_END = WINDOW_START + dt.timedelta(days=DAYS_AHEAD, hours=12)
FILLER_MAX = dt.timedelta(hours=6)  # split long filler blocks
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(HERE, "teams_cache.json")

DURATION = {
    "nhl": dt.timedelta(hours=2, minutes=45),
    "ahl": dt.timedelta(hours=2, minutes=45),
    "lhjmq": dt.timedelta(hours=2, minutes=45),
    "ohl": dt.timedelta(hours=2, minutes=45),
    "whl": dt.timedelta(hours=2, minutes=45),
    "nba": dt.timedelta(hours=2, minutes=30),
    "nfl": dt.timedelta(hours=3, minutes=30),
    "mlb": dt.timedelta(hours=3, minutes=15),
}
LEAGUE_LABEL = {"nhl": "NHL", "ahl": "AHL", "lhjmq": "LHJMQ", "ohl": "OHL", "whl": "WHL", "nba": "NBA", "nfl": "NFL", "mlb": "MLB"}
HOCKEYTECH = {  # public widget keys used by the leagues' own websites
    "lhjmq": ("lhjmq", "f1aa699db3d81487"),
    "ohl": ("ohl", "f1aa699db3d81487"),
    "whl": ("whl", "f1aa699db3d81487"),
    "ahl": ("ahl", "50c2cd9b5e18e390"),
}
ESPN = {"nba": "basketball/nba", "nfl": "football/nfl", "mlb": "baseball/mlb"}

# Eastern time for "Next game" text (no external tz database needed)
def to_eastern(t):
    y = t.year
    # DST: 2nd Sunday of March 07:00 UTC -> 1st Sunday of November 06:00 UTC
    mar = dt.datetime(y, 3, 8, 7, tzinfo=UTC)
    dst_start = mar + dt.timedelta(days=(6 - mar.weekday()) % 7)
    nov = dt.datetime(y, 11, 1, 6, tzinfo=UTC)
    dst_end = nov + dt.timedelta(days=(6 - nov.weekday()) % 7)
    off = -4 if dst_start <= t < dst_end else -5
    return t + dt.timedelta(hours=off)


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (sports-epg)"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


def log(*a):
    print(*a, file=sys.stderr)


# ---------------------------------------------------------------- collectors
# team record: {"id": "nhl.mtl", "league": "nhl", "abbr": "MTL", "name": "Montréal Canadiens", "short": "Canadiens"}
# game record: {"league", "start": datetime, "home": team_id, "away": team_id, "venue", "tv"}

def team(league, abbr, name, short):
    return {"id": f"{league}.{abbr.lower()}", "league": league, "abbr": abbr.upper(), "name": name, "short": short or name}


def collect_nhl(teams, games):
    try:
        st = get_json("https://api-web.nhle.com/v1/standings/now")
        for s in st.get("standings", []):
            ab = s["teamAbbrev"]["default"]
            teams[f"nhl.{ab.lower()}"] = team("nhl", ab, s["teamName"]["default"], s.get("teamCommonName", {}).get("default"))
    except Exception as e:
        log("NHL standings failed:", e)
    day = WINDOW_START.date()
    seen = set()
    while day <= WINDOW_END.date():
        try:
            data = get_json(f"https://api-web.nhle.com/v1/schedule/{day.isoformat()}")
        except Exception as e:
            log("NHL schedule failed", day, e)
            break
        for gw in data.get("gameWeek", []):
            for g in gw.get("games", []):
                if g["id"] in seen:
                    continue
                seen.add(g["id"])
                h, a = g["homeTeam"], g["awayTeam"]
                for side in (h, a):
                    tid = f"nhl.{side['abbrev'].lower()}"
                    if tid not in teams:
                        full = f"{side.get('placeName', {}).get('default', '')} {side.get('commonName', {}).get('default', '')}".strip()
                        teams[tid] = team("nhl", side["abbrev"], full or side["abbrev"], side.get("commonName", {}).get("default"))
                tv = sorted({b.get("network", "") for b in g.get("tvBroadcasts", []) if b.get("network")})
                games.append({
                    "league": "nhl",
                    "start": dt.datetime.fromisoformat(g["startTimeUTC"].replace("Z", "+00:00")),
                    "home": f"nhl.{h['abbrev'].lower()}", "away": f"nhl.{a['abbrev'].lower()}",
                    "venue": g.get("venue", {}).get("default", ""), "tv": ", ".join(tv),
                })
        day += dt.timedelta(days=7)


def collect_espn(league, teams, games):
    path = ESPN[league]
    try:
        t = get_json(f"https://site.api.espn.com/apis/site/v2/sports/{path}/teams")
        for x in t["sports"][0]["leagues"][0]["teams"]:
            x = x["team"]
            teams[f"{league}.{x['abbreviation'].lower()}"] = team(league, x["abbreviation"], x["displayName"], x.get("name"))
    except Exception as e:
        log(league, "teams failed:", e)
    day = WINDOW_START.date()
    while day <= WINDOW_END.date():
        try:
            data = get_json(f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={day:%Y%m%d}")
        except Exception as e:
            log(league, "scoreboard failed", day, e)
            day += dt.timedelta(days=1)
            continue
        for ev in data.get("events", []) or []:
            comp = ev["competitions"][0]
            side = {c["homeAway"]: c["team"] for c in comp["competitors"]}
            if "home" not in side or "away" not in side:
                continue
            for s in side.values():
                tid = f"{league}.{s['abbreviation'].lower()}"
                teams.setdefault(tid, team(league, s["abbreviation"], s.get("displayName", s["abbreviation"]), s.get("name")))
            tv = ", ".join(n for b in comp.get("broadcasts", []) for n in b.get("names", []))
            games.append({
                "league": league,
                "start": dt.datetime.fromisoformat(ev["date"].replace("Z", "+00:00")),
                "home": f"{league}.{side['home']['abbreviation'].lower()}",
                "away": f"{league}.{side['away']['abbreviation'].lower()}",
                "venue": comp.get("venue", {}).get("fullName", ""), "tv": tv,
            })
        day += dt.timedelta(days=1)


def collect_hockeytech(league, teams, games):
    code, key = HOCKEYTECH[league]
    back = max(0, (NOW.date() - WINDOW_START.date()).days)
    ahead = (WINDOW_END.date() - NOW.date()).days
    url = (f"https://lscluster.hockeytech.com/feed/index.php?feed=modulekit&view=scorebar&key={key}"
           f"&client_code={code}&numberofdaysahead={ahead}&numberofdaysback={back}&fmt=json&lang=en")
    try:
        data = get_json(url)
    except Exception as e:
        log(league, "scorebar failed:", e)
        return
    for g in data.get("SiteKit", {}).get("Scorebar", []):
        for pre in ("Home", "Visitor"):
            ab = g[f"{pre}Code"]
            full = f"{g.get(pre + 'City', '')} {g.get(pre + 'Nickname', '')}".strip() or g.get(pre + "LongName", ab)
            teams.setdefault(f"{league}.{ab.lower()}", team(league, ab, full, g.get(pre + "Nickname")))
        try:
            start = dt.datetime.fromisoformat(g["GameDateISO8601"]).astimezone(UTC)
        except Exception:
            continue
        games.append({
            "league": league, "start": start,
            "home": f"{league}.{g['HomeCode'].lower()}", "away": f"{league}.{g['VisitorCode'].lower()}",
            "venue": g.get("venue_name", ""), "tv": "",
        })


# ---------------------------------------------------------------- xmltv
def ts(t):
    return t.astimezone(UTC).strftime("%Y%m%d%H%M%S +0000")


def prog(ch, start, stop, title, desc, category, live=False):
    out = [f'  <programme start="{ts(start)}" stop="{ts(stop)}" channel="{escape(ch)}">',
           f'    <title lang="en">{escape(title)}</title>']
    if desc:
        out.append(f'    <desc lang="en">{escape(desc)}</desc>')
    out.append(f'    <category lang="en">{escape(category)}</category>')
    if live:
        out.append("    <live />")
    out.append("  </programme>")
    return "\n".join(out)


def fmt_next(t):
    e = to_eastern(t)
    return e.strftime("%a %b %d, %I:%M %p ET").replace(" 0", " ")


def build(teams, games):
    by_team = {tid: [] for tid in teams}
    for g in games:
        for tid in (g["home"], g["away"]):
            by_team.setdefault(tid, []).append(g)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<tv generator-info-name="sports-epg">']
    for tid in sorted(teams):
        t = teams[tid]
        lines.append(f'  <channel id="{escape(tid)}">')
        lines.append(f'    <display-name lang="en">{escape(LEAGUE_LABEL[t["league"]] + " " + t["name"])}</display-name>')
        lines.append(f'    <display-name lang="en">{escape(t["abbr"])}</display-name>')
        lines.append("  </channel>")
    for tid in sorted(teams):
        t = teams[tid]
        lg = LEAGUE_LABEL[t["league"]]
        dur = DURATION[t["league"]]
        gl = sorted({(g["start"], g["home"], g["away"]): g for g in by_team.get(tid, [])}.values(), key=lambda g: g["start"])
        cursor = WINDOW_START
        for i, g in enumerate(gl + [None]):
            nxt_start = g["start"] if g else WINDOW_END
            # filler until the next game
            if nxt_start > cursor:
                if g:
                    title = f"{lg} {t['name']} - Next: {teams.get(g['away'], {}).get('short', g['away'])} @ {teams.get(g['home'], {}).get('short', g['home'])}"
                    desc = f"Next game {fmt_next(g['start'])}."
                else:
                    title = f"{lg} {t['name']} - No game scheduled"
                    desc = "No game in the next few days."
                s = cursor
                while s < min(nxt_start, WINDOW_END):
                    e = min(s + FILLER_MAX, nxt_start, WINDOW_END)
                    lines.append(prog(tid, s, e, title, desc, "Sports"))
                    s = e
            if not g:
                break
            gs, ge = g["start"], g["start"] + dur
            if ge <= WINDOW_START or gs >= WINDOW_END:
                cursor = max(cursor, ge)
                continue
            gs = max(gs, cursor)
            away = teams.get(g["away"], {"name": g["away"], "short": g["away"]})
            home = teams.get(g["home"], {"name": g["home"], "short": g["home"]})
            title = f"{lg}: {away['name']} @ {home['name']}"
            bits = [f"{lg} game, {fmt_next(g['start'])}."]
            if g.get("venue"):
                bits.append(f"Venue: {g['venue']}.")
            if g.get("tv"):
                bits.append(f"TV: {g['tv']}.")
            lines.append(prog(tid, gs, ge, title, " ".join(bits), "Sports", live=True))
            cursor = ge
    lines.append("</tv>")
    return "\n".join(lines) + "\n"


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "public")
    os.makedirs(out_dir, exist_ok=True)
    teams, games = {}, []
    if os.path.exists(CACHE_FILE):  # keeps off-season teams in the guide
        with open(CACHE_FILE, encoding="utf-8") as f:
            for t in json.load(f):
                teams[t["id"]] = t
    collect_nhl(teams, games)
    for lg in ESPN:
        collect_espn(lg, teams, games)
    for lg in HOCKEYTECH:
        collect_hockeytech(lg, teams, games)
    xml = build(teams, games)
    with open(os.path.join(out_dir, "sports.xml"), "w", encoding="utf-8") as f:
        f.write(xml)
    with gzip.open(os.path.join(out_dir, "sports.xml.gz"), "wt", encoding="utf-8") as f:
        f.write(xml)
    team_list = sorted(teams.values(), key=lambda t: t["id"])
    with open(os.path.join(out_dir, "teams.json"), "w", encoding="utf-8") as f:
        json.dump(team_list, f, ensure_ascii=False, indent=1)
    counts = {}
    for g in games:
        counts[g["league"]] = counts.get(g["league"], 0) + 1
    log(f"teams={len(teams)} games={len(games)} by league={counts}")


if __name__ == "__main__":
    main()
