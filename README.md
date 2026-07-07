# HoopsHub Scout — Card Format Demo

A stripped-down, deploy-safe build for showing Trey and Peyton the **card
formatting** and getting feedback before the full scraping pipeline gets wired
in. Live data is **BartTorvik only** (one fast call). Everything ESPN-derived
reads from a **pre-built `scouting_hub.db`** so nothing heavy scrapes while the
app is open.

## What's in the demo

- **Player Cards** in the HoopsHub format: position badge, role-tag slot,
  a **General** row (PTS · REB · AST · 2PT% · 3PT% · FTr · FT%) and a
  **position-specific metrics** row (Guard / Wing / Center).
- **Advanced back** on each card (click *Analyze Target Profile*): Synergy
  Shot Types, Synergy Play Types, a shot chart, and the **Full Torvik Stats**
  laid out as tiles.
- **Blue-to-gold tinting** on the tiles (the app's `#2774AE` / `#FFD100`),
  low = blue, high = gold, to signal percentile at a glance.

## Honest data state (important for the demo)

- **Live now:** BartTorvik advanced stats (PTS, ORTG, USG, EFG, TS, BPM,
  FTr, 2P%, 3P%, rebound/assist **rates**, etc.).
- **Shows `n/a` until the DB is built:** FT%, **per-game** REB/AST, and shot
  charts. The Torvik advanced feed does not carry those — they come from ESPN
  box scores in `scouting_hub.db`. Cells render as a grayed **n/a**, never a
  fake `0.0`.
- **Synergy tiles:** sample/empty state. Synergy is **not** scraped. Those
  tables fill later from print-to-PDF exports (or the Sportradar Synergy API).

## Build the data (one-time, run locally)

Full D1 (every player available on every card):

```bash
pip install -r requirements.txt
python3 build_game_logs.py      # ESPN box scores  -> scouting_hub.db  (~30 min)
python3 build_shot_charts.py    # ESPN shot charts -> scouting_hub.db
```

Then commit the filled `scouting_hub.db`. After that FT%, per-game REB/AST,
and shot charts show real numbers on open, for anyone in the DB.

> These are ESPN's public API. A single sequential pass with the built-in
> delays is well within normal use. The 30 min is just volume, not risk.
>
> Fast alternative: `build_demo_db.py` pulls only specific teams' games
> (~2 min) if you ever want a quick build instead of the full crawl. Edit
> `DEMO_TEAM_NAMES` at the top to control which teams.

## Run

```bash
streamlit run app.py
```

## Deploy (Streamlit Community Cloud)

1. Push this folder (including a **pre-built** `scouting_hub.db`) to GitHub.
2. On share.streamlit.io, point a new app at `app.py`.
3. Do **not** run the build scripts on the deploy — they're offline-only.
   The deployed app just reads the committed DB plus the one live Torvik call.

## Not included on purpose

No Synergy scraper, no KenPom scraper. Those are the paid-login sources and
they stay out of this build. The card layout is ready to receive that data
the moment it's ingested cleanly.
