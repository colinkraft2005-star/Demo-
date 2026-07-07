import streamlit as st
import pandas as pd
import requests
import sqlite3
import urllib.parse
import re
import math
import ssl
import urllib3
import time
import bisect
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Arc, Circle, FancyArrow, Rectangle
from datetime import datetime

P5_CONFS = {"ACC", "B10", "B12", "BE", "SEC"}

# ==========================================
# LOCAL MAC SSL OVERRIDE
# ==========================================
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass

st.set_page_config(layout="wide")

# HoopsHub palette (matches the existing app)
UCLA_BLUE = "#2774AE"
UCLA_GOLD = "#FFD100"


# ==========================================
# DATABASE INIT
# ==========================================
def init_db():
    conn = sqlite3.connect('scouting_hub.db')
    cursor = conn.cursor()
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS player_notes
                   (
                       player_name  TEXT PRIMARY KEY,
                       team_name    TEXT,
                       scout_name   TEXT,
                       priority_tier TEXT,
                       position     TEXT,
                       role         TEXT,
                       rumored_nil  TEXT,
                       personal_val TEXT,
                       agent        TEXT,
                       agency       TEXT,
                       photo_url    TEXT,
                       eval_date    TEXT,
                       notes        TEXT
                   )
                   ''')
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS roster
                   (
                       id          INTEGER PRIMARY KEY AUTOINCREMENT,
                       player_name TEXT,
                       position    TEXT,
                       depth       INTEGER,
                       descriptor  TEXT,
                       bt_name     TEXT
                   )
                   ''')
    # Synergy layer — filled by a print-to-PDF parser off exports (NOT a scraper).
    # Empty in the demo; the advanced-back Synergy tiles show a sample/empty state.
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS synergy_play_types
                   (player_name TEXT, play_type TEXT, poss INTEGER, ppp REAL,
                    ppp_rank INTEGER, rating TEXT, PRIMARY KEY (player_name, play_type))
                   ''')
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS synergy_shot_types
                   (player_name TEXT, shot_type TEXT, poss INTEGER, pps REAL,
                    pps_rank INTEGER, rating TEXT, PRIMARY KEY (player_name, shot_type))
                   ''')
    conn.commit()
    conn.close()


def seed_roster_if_empty():
    """Pre-load the 26-27 UCLA roster on first run only."""
    conn = sqlite3.connect('scouting_hub.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM roster")
    count = cursor.fetchone()[0]
    if count == 0:
        seed = [
            ("Trent Perry",      "PG", 1, "13 PPG / 59.5 TS%",            "Trent Perry"),
            ("Stink Robinson",   "PG", 2, "4.5% STL rate / 43.3% from 3", ""),
            ("Markell Alston",   "PG", 3, "Rs-Fr",                         ""),
            ("Jaylen Petty",     "CG", 1, "67 made 3s as FR / 10 PPG on a Top 15 team", "Jaylen Petty"),
            ("Eric Freeny",      "CG", 2, "Glue guy",                      ""),
            ("Gunars Grinvalds", "CG", 3, "Freshman",                      ""),
            ("OPEN",             "SF", 1, "Starting SF — TBD",             ""),
            ("Brandon Williams", "SF", 2, "Rs-Junior",                     "Brandon Williams"),
            ("JoJo Philon",      "SF", 3, "Freshman",                      ""),
            ("Eric Dailey Jr.",  "PF", 1, "12 PPG / 6 RPG",               "Eric Dailey Jr."),
            ("Sergej Macura",    "PF", 2, "Top 15 Rebounder in SEC",      "Sergej Macura"),
            ("Xavier Booker",    "C",  1, "43.3% 3PT% / 4th best Block rate in B1G", "Xavier Booker"),
            ("Filip Jovic",      "C",  2, "Top 10 O-Rebounder in SEC / 9.5 PPG last two months", "Filip Jovic"),
            ("Javonte Floyd",    "C",  3, "Freshman",                      ""),
        ]
        cursor.executemany(
            "INSERT INTO roster (player_name, position, depth, descriptor, bt_name) VALUES (?, ?, ?, ?, ?)",
            seed)
        conn.commit()
    conn.close()


init_db()
seed_roster_if_empty()


# ==========================================
# HEADSHOT FETCHER
# ==========================================
def fetch_sr_headshot_silent(player_name, team_name=""):
    cleaned_name = player_name.replace(".", "").replace(",", "")
    safe_name = urllib.parse.quote(cleaned_name)
    search_url = f"https://www.sports-reference.com/cbb/search/search.fcgi?search={safe_name}"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    img_pattern = r'src="(https://www.sports-reference.com/req/[^"]+/cbb/images/players/[^"]+\.jpg)"'
    suffix_words = ['jr', 'ii', 'iii', 'iv', 'v']
    name_parts = cleaned_name.lower().split()
    detected_suffix = name_parts[-1] if (name_parts and name_parts[-1] in suffix_words) else None

    def parse_html_for_image(html, current_url):
        match = re.search(img_pattern, html)
        if match:
            return match.group(1)
        if "/cbb/search/search.fcgi" in current_url:
            results = re.findall(r'href="(/cbb/players/([^"]+)\.html)"[^>]*>(.*?)<\/a>(.*?)(?:<\/div>|<li>|<tr|<td>)',
                                 html, re.IGNORECASE | re.DOTALL)
            if results:
                for link, slug, display_name, context in results:
                    if team_name and (team_name.lower() in context.lower() or team_name.lower() in display_name.lower()):
                        if detected_suffix and f"-{detected_suffix}" not in slug.lower():
                            continue
                        return fetch_profile_image(link)
                suffix_matches = []
                for link, slug, display_name, context in results:
                    if detected_suffix and f"-{detected_suffix}" in slug.lower():
                        suffix_matches.append(link)
                if suffix_matches:
                    return fetch_profile_image(suffix_matches[-1])
                try:
                    def extract_num(r):
                        num_match = re.search(r'-(\d+)$', r[1])
                        return int(num_match.group(1)) if num_match else 0
                    best_link = max(results, key=extract_num)[0]
                    return fetch_profile_image(best_link)
                except Exception:
                    return fetch_profile_image(results[0][0])
        return ""

    def fetch_profile_image(player_page_path):
        try:
            player_url = f"https://www.sports-reference.com{player_page_path}"
            player_response = requests.get(player_url, headers=headers, timeout=5, verify=False)
            img_match = re.search(img_pattern, player_response.text)
            return img_match.group(1) if img_match else ""
        except Exception:
            return ""

    try:
        response = requests.get(search_url, headers=headers, timeout=5, verify=False)
        img_url = parse_html_for_image(response.text, response.url)
        if img_url:
            return img_url
        if detected_suffix:
            base_name = " ".join(name_parts[:-1])
            fallback_url = f"https://www.sports-reference.com/cbb/search/search.fcgi?search={urllib.parse.quote(base_name)}"
            fallback_resp = requests.get(fallback_url, headers=headers, timeout=5, verify=False)
            img_url = parse_html_for_image(fallback_resp.text, fallback_resp.url)
            if img_url:
                return img_url
    except Exception:
        pass
    return ""


# ==========================================
# BARTTORVIK FETCH (polite, sequential — public JSON endpoint)
# ==========================================
def fetch_barttorvik_safe(top_filter=None, retries=3, delay_between_requests=4):
    base_url = 'https://barttorvik.com/getadvstats.php?year=2026&page=playerstat&json=1'
    url = base_url if top_filter is None else f"{base_url}&top={top_filter}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://barttorvik.com/"}
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=headers, verify=False, timeout=20)
            if response.text.strip():
                raw_data = response.json()

                def safe_float(row_list, idx):
                    try:
                        if idx < len(row_list) and row_list[idx] is not None and str(row_list[idx]).strip() != "":
                            return float(row_list[idx])
                        return 0.0
                    except (ValueError, TypeError, IndexError):
                        return 0.0

                cleaned_rows = []
                for row in raw_data:
                    if len(row) < 53:
                        continue
                    cleaned_rows.append({
                        "PLAYER": str(row[0]), "TEAM": str(row[1]), "CONF": str(row[2]),
                        "GP": int(row[3]) if row[3] else 0,
                        "MIN_PCT": safe_float(row, 4), "MPG": safe_float(row, 54),
                        "PPG": safe_float(row, 63) if len(row) > 63 else 0.0,
                        "ORTG": safe_float(row, 5), "USG": safe_float(row, 6),
                        "EFG": safe_float(row, 7), "TS": safe_float(row, 8),
                        "OR": safe_float(row, 9), "DR": safe_float(row, 10),
                        "AST": safe_float(row, 11), "TO": safe_float(row, 12),
                        "BLK": safe_float(row, 22), "STL": safe_float(row, 23),
                        "FTR": safe_float(row, 24),
                        "TWO_P": safe_float(row, 18) * 100, "THREE_P": safe_float(row, 21) * 100,
                        "THREE_P_100": safe_float(row, 65) if len(row) > 65 else 0.0,
                        "CLASS": str(row[25]) if len(row) > 25 else "",
                        "HEIGHT": str(row[26]) if len(row) > 26 else "",
                        "PRPG": safe_float(row, 28), "BPM": safe_float(row, 50),
                        "OBPM": safe_float(row, 51), "DBPM": safe_float(row, 52)})
                return pd.DataFrame(cleaned_rows)
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(delay_between_requests)
    return None


@st.cache_data(ttl=3600)
def load_all_data_v6():
    return fetch_barttorvik_safe(top_filter=None)


@st.cache_data(ttl=3600)
def load_boxscore_lookup() -> pd.DataFrame:
    """
    Per-player box-score aggregates from the pre-built game-log DB (ESPN, run offline).
    Supplies FT%, per-game REB/AST that the Torvik advanced feed doesn't carry.
    Returns empty DataFrame if build_game_logs.py hasn't been run yet -> cells show n/a.
    """
    try:
        conn = sqlite3.connect("scouting_hub.db")
        df = pd.read_sql_query("""
            SELECT
                player_name AS PLAYER,
                team_name   AS TEAM,
                team_espn_id,
                COUNT(*)                                                       AS GP,
                ROUND(AVG(reb), 1)                                            AS RPG,
                ROUND(AVG(ast), 1)                                            AS APG,
                ROUND(SUM(ft_made)*100.0 / NULLIF(SUM(ft_att), 0), 1)         AS FT_PCT,
                ROUND(SUM(ft_att)*100.0  / NULLIF(SUM(fg_att), 0), 1)         AS FTR_BOX,
                ROUND(SUM(pts)*100.0 /
                    NULLIF(2.0*(SUM(fg_att)+0.44*SUM(ft_att)), 0), 1)         AS TS_BOX
            FROM player_game_logs
            WHERE min_played >= 1
            GROUP BY player_name, team_espn_id
            HAVING COUNT(*) >= 1
        """, conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


def game_log_db_ready() -> bool:
    try:
        conn = sqlite3.connect("scouting_hub.db")
        p = conn.execute("SELECT COUNT(*) FROM player_game_logs").fetchone()[0]
        conn.close()
        return p > 0
    except Exception:
        return False


@st.cache_data(ttl=3600)
def load_player_shots(player_name: str, team_espn_id=None) -> pd.DataFrame:
    try:
        conn = sqlite3.connect("scouting_hub.db")
        team_clause = "AND sc.team_id = :team_id" if team_espn_id else ""
        params = {"name": player_name}
        if team_espn_id:
            params["team_id"] = str(team_espn_id)
        df = pd.read_sql_query(f"""
            SELECT sc.coord_x_norm AS x, sc.coord_y_norm AS y,
                   sc.scoring_play AS made, sc.shot_type, sc.points_attempted AS pts
            FROM shot_chart sc
            WHERE sc.player_name = :name
              AND sc.shot_type != 'MadeFreeThrow'
              {team_clause}
        """, conn, params=params)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


# ==========================================
# TORVIK PERCENTILES + GOLD-TO-BLUE TILE HELPERS
# ==========================================
@st.cache_data(ttl=3600)
def build_torvik_percentiles(_df: pd.DataFrame) -> dict:
    cols = ["PPG", "ORTG", "USG", "EFG", "TS", "OR", "DR", "AST", "TO", "BLK", "STL",
            "FTR", "TWO_P", "THREE_P", "THREE_P_100", "BPM", "OBPM", "DBPM", "PRPG", "MIN_PCT"]
    out = {}
    for c in cols:
        if c in _df.columns:
            out[c] = sorted(pd.to_numeric(_df[c], errors="coerce").dropna().tolist())
    return out


def _pctile(val, sorted_vals, higher_better=True):
    if not sorted_vals or val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    r = bisect.bisect_left(sorted_vals, val)
    p = 100.0 * r / len(sorted_vals)
    return p if higher_better else 100 - p


def tile_bg(pct):
    """
    Diverging fill in the app's palette: blue (#2774AE, low) -> light neutral (mid)
    -> gold (#FFD100, high). Light-card friendly. Returns (bg_hex, text_hex).
    """
    if pct is None:
        return "#EEF1F5", "#9AA3AF"        # grayed n/a
    p = max(0.0, min(100.0, pct))
    blue, mid, gold = (39, 116, 174), (233, 238, 243), (255, 209, 0)
    if p < 50:
        t = p / 50.0
        c = [round(blue[i] + (mid[i] - blue[i]) * t) for i in range(3)]
    else:
        t = (p - 50) / 50.0
        c = [round(mid[i] + (gold[i] - mid[i]) * t) for i in range(3)]
    lum = 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
    text = "#FFFFFF" if lum < 140 else "#111827"
    return f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}", text


def stat_tile(label, value, pct=None, show_pct=False):
    """One stat tile in the app's light style, tinted by percentile."""
    bg, fg = tile_bg(pct)
    pct_html = ""
    if show_pct and pct is not None:
        pct_html = (f"<span style='font-size:13px;font-weight:600;color:{fg};'>"
                    f"{int(round(pct))}<span style='font-size:8px;opacity:.6;'>%</span></span>")
    val_row = (f"<div style='display:flex;justify-content:space-between;align-items:baseline;margin-top:2px;'>"
               f"<span style='font-size:16px;font-weight:700;color:{fg};line-height:1;'>{value}</span>"
               f"{pct_html}</div>") if show_pct else (
               f"<div style='font-size:16px;font-weight:700;color:{fg};margin-top:2px;line-height:1;'>{value}</div>")
    return (f"<div style='background:{bg};border-radius:7px;padding:9px 10px 8px;"
            f"border:1px solid rgba(0,0,0,.05);'>"
            f"<div style='font-size:8px;font-weight:600;letter-spacing:.03em;text-transform:uppercase;"
            f"color:{fg};opacity:.78;'>{label}</div>{val_row}</div>")


def tile_row(tiles, per_row=4):
    """Render a list of tile HTML strings in a responsive grid row."""
    for i in range(0, len(tiles), per_row):
        cols = st.columns(per_row)
        for col, html in zip(cols, tiles[i:i + per_row]):
            col.markdown(html, unsafe_allow_html=True)


def _draw_half_court(ax):
    COURT_COLOR = "#1a3a5c"; LINE_COLOR = "#e0e0e0"; LW = 1.4
    ax.set_facecolor(COURT_COLOR); ax.set_xlim(0, 50); ax.set_ylim(-2, 47)
    ax.set_aspect("equal"); ax.axis("off")
    ax.add_patch(Rectangle((0, 0), 50, 47, linewidth=LW, edgecolor=LINE_COLOR, facecolor=COURT_COLOR, zorder=1))
    ax.add_patch(Rectangle((19, 0), 12, 19, linewidth=LW, edgecolor=LINE_COLOR, facecolor="#0d2a46", zorder=2))
    ax.plot([19, 31], [19, 19], color=LINE_COLOR, linewidth=LW, zorder=3)
    th_top = np.linspace(0, np.pi, 120)
    ax.plot(25 + 6*np.cos(th_top), 19 + 6*np.sin(th_top), color=LINE_COLOR, linewidth=LW, zorder=3)
    th_bot = np.linspace(np.pi, 2*np.pi, 120)
    ax.plot(25 + 6*np.cos(th_bot), 19 + 6*np.sin(th_bot), color=LINE_COLOR, linewidth=LW, linestyle="--", zorder=3)
    BASKET_X, BASKET_Y = 25.0, 5.25
    th_ra = np.linspace(0, np.pi, 100)
    ax.plot(BASKET_X + 4*np.cos(th_ra), BASKET_Y + 4*np.sin(th_ra), color=LINE_COLOR, linewidth=LW, zorder=3)
    ax.plot([21.5, 28.5], [4.0, 4.0], color=LINE_COLOR, linewidth=2.5, zorder=4)
    ax.add_patch(Circle((BASKET_X, BASKET_Y), 0.75, linewidth=LW, edgecolor="#FFA500", facecolor="none", zorder=4))
    R3 = 22.15
    dx0 = math.sqrt(max(R3**2 - BASKET_Y**2, 0))
    right_ang = math.atan2(0 - BASKET_Y, (BASKET_X + dx0) - BASKET_X)
    left_ang = math.atan2(0 - BASKET_Y, (BASKET_X - dx0) - BASKET_X)
    th_3 = np.linspace(right_ang, left_ang + 2*np.pi, 250)
    ax.plot(BASKET_X + R3*np.cos(th_3), BASKET_Y + R3*np.sin(th_3), color=LINE_COLOR, linewidth=LW, zorder=3)


def draw_shot_chart(shots_df: pd.DataFrame, title: str = "") -> plt.Figure:
    shots_df = shots_df[shots_df["y"] >= 0].copy() if not shots_df.empty else shots_df
    fig, ax = plt.subplots(figsize=(6, 5.5))
    fig.patch.set_facecolor("#111827")
    _draw_half_court(ax)
    if shots_df.empty:
        ax.text(25, 24, "No shot data", ha="center", va="center", color="white", fontsize=12)
        if title:
            ax.set_title(title, color="white", fontsize=10, pad=6)
        return fig
    made = shots_df[shots_df["made"] == 1]; missed = shots_df[shots_df["made"] == 0]
    ax.scatter(missed["x"], missed["y"], c="#4a9eff", s=18, alpha=0.55, linewidths=0.3,
               edgecolors="#2060bb", zorder=5)
    ax.scatter(made["x"], made["y"], c="#FFD700", s=18, alpha=0.70, linewidths=0.3,
               edgecolors="#cc9900", zorder=6)
    total = len(shots_df); makes = int(shots_df["made"].sum())
    pct = makes / total * 100 if total else 0
    ax.text(25, -1.2, f"{makes}/{total} FG ({pct:.1f}%)", ha="center", va="top",
            color="#cccccc", fontsize=6.5, zorder=7)
    ax.legend(handles=[mpatches.Patch(color="#FFD700", label=f"Make ({makes})"),
                       mpatches.Patch(color="#4a9eff", label=f"Miss ({total-makes})")],
              loc="upper right", fontsize=7, framealpha=0.25, labelcolor="white",
              facecolor="#111827", edgecolor="none")
    if title:
        ax.set_title(title, color="white", fontsize=9, pad=4)
    plt.tight_layout(pad=0.3)
    return fig


def fmt(val, decimals=1, suffix=""):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "n/a"
    if decimals == 0:
        return f"{int(round(val))}{suffix}"
    return f"{round(float(val), decimals)}{suffix}"


# ==========================================
# DATA LOAD
# ==========================================
load_bar = st.progress(0, text="Loading BartTorvik player database...")
df_all = load_all_data_v6()
load_bar.progress(100, text="Database ready.")
time.sleep(0.2)
load_bar.empty()

if df_all is None:
    st.error(
        "BartTorvik returned empty data.\n\n"
        "This usually means your IP is temporarily rate-limited. "
        "Wait 10-15 minutes or switch networks and reload."
    )
    st.stop()

TORVIK_PCTLS = build_torvik_percentiles(df_all)
BOX_LOOKUP = load_boxscore_lookup()
_gl_ready = game_log_db_ready()

# ==========================================
# HEADER
# ==========================================
head_col1, head_col2 = st.columns([1, 12])
with head_col1:
    st.image("https://cdn.freebiesupply.com/logos/large/2x/ucla-bruins-1-logo-png-transparent.png", width=55)
with head_col2:
    st.markdown("<h2 style='margin:0;padding-top:8px;color:#FFFFFF;'>HoopsHub Scout — Card Format Demo</h2>",
                unsafe_allow_html=True)
if not _gl_ready:
    st.caption("Demo mode: BartTorvik advanced stats are live. FT%, per-game REB, and shot charts "
               "show **n/a** until `build_game_logs.py` and `build_shot_charts.py` are run once and "
               "scouting_hub.db is committed. Synergy tiles show sample formatting only.")
st.write("***")


# ==========================================
# CARD CONFIG
# ==========================================
# Demo cards = real UCLA roster guys, matched into BartTorvik by name.
DEMO_CARDS = [
    {"name": "Trent Perry",     "team": "UCLA", "pos": "GUARD",  "bt": "Trent Perry"},
    {"name": "Jaylen Petty",    "team": "UCLA", "pos": "GUARD",  "bt": "Jaylen Petty"},
    {"name": "Eric Dailey Jr.", "team": "UCLA", "pos": "WING",   "bt": "Eric Dailey Jr."},
    {"name": "Xavier Booker",   "team": "UCLA", "pos": "CENTER", "bt": "Xavier Booker"},
]

POS_METRICS = {
    "GUARD":  [("MIN%", "MIN_PCT", 1, True), ("ORTG", "ORTG", 1, True), ("AST%", "AST", 1, True),
               ("TO%", "TO", 1, False), ("STL%", "STL", 1, True), ("BPM", "BPM", 1, True)],
    "WING":   [("MIN%", "MIN_PCT", 1, True), ("BPM", "BPM", 1, True), ("STL%", "STL", 1, True),
               ("BLK%", "BLK", 1, True), ("DREB%", "DR", 1, True), ("OREB%", "OR", 1, True)],
    "CENTER": [("MIN%", "MIN_PCT", 1, True), ("ORTG", "ORTG", 1, True), ("ORB%", "OR", 1, True),
               ("DREB%", "DR", 1, True), ("BLK%", "BLK", 1, True), ("STL%", "STL", 1, True)],
}


def card_header(card, trow):
    ht = str(trow.get("HEIGHT", "")) if trow is not None else ""
    yr = str(trow.get("CLASS", "")) if trow is not None else ""
    meta = " · ".join([x for x in [card["team"], ht, yr] if x])
    role = card.get("role", "")  # blank slot for now
    role_html = (f"<div style='font-family:monospace;font-size:11px;color:{UCLA_BLUE};"
                 f"font-weight:600;margin-top:4px;'>{role}</div>") if role else (
                 f"<div style='font-family:monospace;font-size:10px;color:#9AA3AF;margin-top:4px;'>"
                 f"role tags — TBD</div>")
    return (
        f"<div style='display:flex;justify-content:space-between;align-items:flex-start;'>"
        f"<div><div style='font-size:20px;font-weight:800;color:#111827;'>{card['name']}</div>"
        f"<div style='font-size:11px;color:#6b7280;margin-top:2px;'>{meta}</div>{role_html}</div>"
        f"<span style='font-size:9px;font-weight:700;letter-spacing:.06em;background:{UCLA_GOLD};"
        f"color:#111827;padding:3px 9px;border-radius:4px;'>{card['pos']}</span></div>")


def render_general_row(trow, box):
    """General row: PTS REB AST 2PT% 3PT% FTr FT%  (REB/FT% from ESPN box, else n/a)."""
    def tv(key):
        try:
            return float(trow.get(key)) if trow is not None else None
        except Exception:
            return None
    ppg = tv("PPG"); two_p = tv("TWO_P"); three_p = tv("THREE_P"); ftr = tv("FTR")
    rpg = float(box["RPG"]) if (box is not None and pd.notna(box.get("RPG"))) else None
    apg = float(box["APG"]) if (box is not None and pd.notna(box.get("APG"))) else None
    ftpct = float(box["FT_PCT"]) if (box is not None and pd.notna(box.get("FT_PCT"))) else None

    tiles = [
        stat_tile("PTS", fmt(ppg), _pctile(ppg, TORVIK_PCTLS.get("PPG", []))),
        stat_tile("REB", fmt(rpg), None),
        stat_tile("AST", fmt(apg), None),
        stat_tile("2PT%", fmt(two_p), _pctile(two_p, TORVIK_PCTLS.get("TWO_P", []))),
        stat_tile("3PT%", fmt(three_p), _pctile(three_p, TORVIK_PCTLS.get("THREE_P", []))),
        stat_tile("FTr", fmt(ftr, 2), _pctile(ftr, TORVIK_PCTLS.get("FTR", []))),
        stat_tile("FT%", fmt(ftpct), None),
    ]
    tile_row(tiles, per_row=7)


def render_position_row(pos, trow):
    metrics = POS_METRICS.get(pos, POS_METRICS["WING"])
    tiles = []
    for label, key, dec, hb in metrics:
        try:
            v = float(trow.get(key)) if trow is not None else None
        except Exception:
            v = None
        pct = _pctile(v, TORVIK_PCTLS.get(key, []), hb)
        tiles.append(stat_tile(label, fmt(v, dec), pct))
    tile_row(tiles, per_row=len(tiles))


def render_synergy_tiles(player_name, table, label_col, val_col, rank_col):
    try:
        conn = sqlite3.connect("scouting_hub.db")
        df = pd.read_sql_query(f"SELECT * FROM {table} WHERE player_name = ? ORDER BY poss DESC",
                               conn, params=(player_name,))
        conn.close()
    except Exception:
        df = pd.DataFrame()
    if df.empty:
        st.caption("Synergy export not loaded (sample formatting only — fills via the print-to-PDF parser).")
        return
    rows = [r for _, r in df.iterrows() if pd.notna(r[rank_col])]
    tiles = [stat_tile(r[label_col], f"{r[val_col]:.2f}", int(r[rank_col]), show_pct=True) for r in rows]
    tile_row(tiles, per_row=4)


def render_torvik_tiles(trow):
    groups = [
        ("IMPACT", [("PRPG!", "PRPG", 1, True), ("BPM", "BPM", 1, True),
                    ("OBPM", "OBPM", 1, True), ("DBPM", "DBPM", 1, True)]),
        ("EFFICIENCY", [("ORTG", "ORTG", 1, True), ("USG%", "USG", 1, True),
                        ("EFG%", "EFG", 1, True), ("TS%", "TS", 1, True)]),
        ("SHOOTING", [("2P%", "TWO_P", 1, True), ("3P%", "THREE_P", 1, True),
                      ("FTr", "FTR", 2, True), ("3PA/100", "THREE_P_100", 1, True)]),
        ("PLAYMAKING / VOLUME", [("AST%", "AST", 1, True), ("TO%", "TO", 1, False),
                                 ("MIN%", "MIN_PCT", 1, True), ("PPG", "PPG", 1, True)]),
        ("REB / DEFENSE", [("OR%", "OR", 1, True), ("DR%", "DR", 1, True),
                           ("BLK%", "BLK", 1, True), ("STL%", "STL", 1, True)]),
    ]
    for glabel, items in groups:
        st.markdown(f"<div style='font-family:monospace;font-size:9px;letter-spacing:.12em;"
                    f"color:#9AA3AF;margin:8px 0 5px;'>{glabel}</div>", unsafe_allow_html=True)
        tiles = []
        for label, key, dec, hb in items:
            try:
                v = float(trow.get(key)) if trow is not None else None
            except Exception:
                v = None
            pct = _pctile(v, TORVIK_PCTLS.get(key, []), hb)
            tiles.append(stat_tile(label, fmt(v, dec), pct))
        tile_row(tiles, per_row=4)


# ==========================================
# PLAYER CARDS + ADVANCED BACK
# ==========================================
st.subheader("Player Cards")
st.caption("HoopsHub Scout card format. Click a card to open the advanced back "
           "(Synergy shot/play types, shot chart, full Torvik tiles).")

if "card_back" not in st.session_state:
    st.session_state.card_back = None

for card in DEMO_CARDS:
    match = df_all[df_all["PLAYER"] == card["bt"]]
    trow = match.iloc[0] if not match.empty else None
    box = None
    if not BOX_LOOKUP.empty:
        bmatch = BOX_LOOKUP[BOX_LOOKUP["PLAYER"] == card["name"]]
        if not bmatch.empty:
            box = bmatch.iloc[0]

    with st.container(border=True):
        st.markdown(card_header(card, trow), unsafe_allow_html=True)
        if trow is None:
            st.caption(f"No BartTorvik row matched for '{card['bt']}' — check the exact Torvik spelling.")
        st.markdown("<div style='font-size:9px;letter-spacing:.12em;color:#9AA3AF;"
                    "margin:10px 0 5px;'>GENERAL</div>", unsafe_allow_html=True)
        render_general_row(trow, box)
        st.markdown(f"<div style='font-size:9px;letter-spacing:.12em;color:#9AA3AF;"
                    f"margin:10px 0 5px;'>{card['pos']} METRICS</div>", unsafe_allow_html=True)
        render_position_row(card["pos"], trow)

        if st.button(f"Analyze Target Profile: {card['name']}", key=f"drill_{card['name']}"):
            st.session_state.card_back = card["name"] if st.session_state.card_back != card["name"] else None

        # ---- advanced back ----
        if st.session_state.card_back == card["name"]:
            st.divider()
            st.markdown(f"**{card['name']} — Advanced**")

            st.markdown("<div style='font-family:monospace;font-size:11px;letter-spacing:.12em;"
                        f"color:{UCLA_GOLD};background:#111827;display:inline-block;padding:2px 8px;"
                        "border-radius:4px;margin:6px 0;'>SYNERGY SHOT TYPES</div>", unsafe_allow_html=True)
            render_synergy_tiles(card["name"], "synergy_shot_types", "shot_type", "pps", "pps_rank")

            st.markdown("<div style='font-family:monospace;font-size:11px;letter-spacing:.12em;"
                        f"color:{UCLA_GOLD};background:#111827;display:inline-block;padding:2px 8px;"
                        "border-radius:4px;margin:10px 0 6px;'>SYNERGY PLAY TYPES</div>", unsafe_allow_html=True)
            render_synergy_tiles(card["name"], "synergy_play_types", "play_type", "ppp", "ppp_rank")

            st.markdown("<div style='font-family:monospace;font-size:11px;letter-spacing:.12em;"
                        f"color:{UCLA_GOLD};background:#111827;display:inline-block;padding:2px 8px;"
                        "border-radius:4px;margin:10px 0 6px;'>SHOT CHART</div>", unsafe_allow_html=True)
            team_id = box["team_espn_id"] if (box is not None and "team_espn_id" in box.index) else None
            shots = load_player_shots(card["name"], team_id)
            if shots.empty:
                st.caption("Shot locations show once build_shot_charts.py has populated the DB.")
            else:
                cc, _ = st.columns([3, 2])
                with cc:
                    fig = draw_shot_chart(shots, title=card["name"])
                    st.pyplot(fig, use_container_width=True)
                plt.close(fig)

            st.markdown("<div style='font-family:monospace;font-size:11px;letter-spacing:.12em;"
                        f"color:{UCLA_GOLD};background:#111827;display:inline-block;padding:2px 8px;"
                        "border-radius:4px;margin:10px 0 6px;'>FULL TORVIK STATS</div>", unsafe_allow_html=True)
            render_torvik_tiles(trow)
