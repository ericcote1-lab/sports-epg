# sports-epg

XMLTV guide with one channel per team for NHL, NBA, NFL, MLB, AHL and LHJMQ.
Each team channel shows its games ("Away @ Home", with venue and TV) and
"Next game" filler in between. Rebuilt every 3 hours by GitHub Actions and
published with GitHub Pages:

- `https://<user>.github.io/sports-epg/sports.xml`
- `https://<user>.github.io/sports-epg/sports.xml.gz`
- `https://<user>.github.io/sports-epg/teams.json` (channel IDs)

Channel IDs are `<league>.<team abbreviation>`, e.g. `nhl.mtl`, `nba.tor`,
`nfl.buf`, `mlb.tor`, `ahl.lav`, `lhjmq.gat`.

Sources: api-web.nhle.com (NHL), ESPN site API (NBA/NFL/MLB),
HockeyTech (AHL, LHJMQ). `teams_cache.json` keeps off-season teams listed.

Run locally: `python sports_epg.py public`
