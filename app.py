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
import matplotlib.patches mpatches
from matplotlib.patches import Arc, Circle, FancyArrow, Rectangle
from datetime import datetime
import streamlit.components.v1 as components

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

# App-wide palette configurations
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
# BARTTORVIK FETCH
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
def load_consistent_boxscore_stats(max_opp_rank=None) -> pd.DataFrame:
    try:
        conn = sqlite3.connect("scouting_hub.db")
        where = f"AND COALESCE(p.kp_opp_rank, p.opp_rank) <= {int(max_opp_rank)}" if max_opp_rank else ""
        df = pd.read_sql_query(f"""
            SELECT
                p.player_name                                                    AS PLAYER,
                p.team_espn_id,
                p.team_name                                                      AS TEAM,
                COUNT(*)                                                         AS GP,
                ROUND(AVG(p.pts), 1)                                             AS PPG,
                ROUND(SUM(p.pts)*100.0 /
                    NULLIF(2.0*(SUM(p.fg_att)+0.44*SUM(p.ft_att)), 0), 1)       AS TS,
                ROUND((SUM(p.fg_made)+0.5*SUM(p.fg3_made))*100.0 /
                    NULLIF(SUM(p.fg_att), 0), 1)                                 AS EFG,
                ROUND((SUM(p.fg_made)-SUM(p.fg3_made))*100.0 /
                    NULLIF(SUM(p.fg_att)-SUM(p.fg3_att), 0), 1)                 AS TWO_P,
                ROUND(SUM(p.fg3_made)*100.0 /
                    NULLIF(SUM(p.fg3_att), 0), 1)                                AS THREE_P,
                ROUND(SUM(p.ft_made)*100.0 /
                    NULLIF(SUM(p.ft_att), 0), 1)                                 AS FT_PCT,
                ROUND(SUM(p.ft_att)*100.0 /
                    NULLIF(SUM(p.fg_att), 0), 1)                                 AS FTR,
                ROUND(SUM(CASE WHEN t.fga IS NOT NULL THEN p.fg_att + 0.44*p.ft_att + p.tov END)*100.0 /
                    NULLIF(SUM(t.fga)+0.44*SUM(t.fta)+SUM(t.tov), 0), 1)        AS USG,
                ROUND(SUM(CASE WHEN t.fgm IS NOT NULL THEN p.ast END)*100.0 /
                    NULLIF(
                        (SUM(CASE WHEN t.fgm IS NOT NULL THEN p.min_played END)*1.0 /
                         NULLIF(SUM(CASE WHEN t.fgm IS NOT NULL THEN tm.team_mp END)/5.0, 0))
                        * SUM(t.fgm)
                        - SUM(CASE WHEN t.fgm IS NOT NULL THEN p.fg_made END),
                    0), 1) AS AST_PCT,
                ROUND(SUM(CASE WHEN t.orb IS NOT NULL THEN p.orb END)*100.0 /
                    NULLIF(SUM(t.orb)+SUM(t.opp_drb), 0), 1)                    AS OR_PCT,
                ROUND(SUM(CASE WHEN t.drb IS NOT NULL THEN p.drb END)*100.0 /
                    NULLIF(SUM(t.drb)+SUM(t.opp_orb), 0), 1)                    AS DR_PCT,
                ROUND(SUM(CASE WHEN t.opp_fga IS NOT NULL THEN p.blk END)*100.0 /
                    NULLIF(SUM(t.opp_fga)-SUM(t.opp_fg3a), 0), 1)               AS BLK_PCT,
                ROUND(SUM(CASE WHEN t.possessions IS NOT NULL THEN p.stl END)*100.0 /
                    NULLIF(SUM(t.possessions), 0), 1)                            AS STL_PCT,
                ROUND(AVG(CASE WHEN p.ortg_kp IS NOT NULL THEN p.ortg_kp END), 1) AS ORTG_KP,
                ROUND(AVG(CASE WHEN p.usage_kp IS NOT NULL THEN p.usage_kp END), 1) AS USAGE_KP
            FROM player_game_logs p
            LEFT JOIN game_team_stats t
                ON t.team_espn_id = p.team_espn_id AND t.game_date = p.game_date
            LEFT JOIN (
                SELECT team_espn_id, game_date, SUM(min_played) AS team_mp
                FROM player_game_logs
                GROUP BY team_espn_id, game_date
            ) tm ON tm.team_espn_id = p.team_espn_id AND tm.game_date = p.game_date
            WHERE p.min_played >= 1 {where}
            GROUP BY p.player_name, p.team_espn_id
            HAVING COUNT(*) >= 3
        """, conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_p5_percentile_benchmarks(_df_all: pd.DataFrame, max_opp_rank=None) -> dict:
    try:
        conn0 = sqlite3.connect("scouting_hub.db")
        orb_rows = conn0.execute("SELECT COUNT(*) FROM player_game_logs WHERE orb > 0").fetchone()[0]
        conn0.close()
        if orb_rows < 50000:
            return {}
        all_box = load_consistent_boxscore_stats(max_opp_rank)
        if all_box.empty:
            return {}
        conn = sqlite3.connect("scouting_hub.db")
        rankings = pd.read_sql_query("SELECT espn_id, bart_name FROM team_rankings", conn)
        positions = pd.read_sql_query("SELECT player_name, position_group FROM player_positions", conn)
        conn.close()
        p5_bart_teams = set(_df_all[_df_all["CONF"].isin(P5_CONFS)]["TEAM"].unique())
        p5_espn_ids   = set(rankings[rankings["bart_name"].isin(p5_bart_teams)]["espn_id"].tolist())
        p5 = all_box[all_box["team_espn_id"].isin(p5_espn_ids)].copy()
        p5 = p5.merge(positions, left_on="PLAYER", right_on="player_name", how="left")
        p5["position_group"] = p5["position_group"].fillna("Wing")
        STAT_COLS = ["PPG", "TS", "EFG", "TWO_P", "THREE_P", "FT_PCT", "FTR", "USG", "AST_PCT", "OR_PCT", "DR_PCT", "BLK_PCT", "STL_PCT", "ORTG_KP", "USAGE_KP"]
        benchmarks = {}
        for grp in ("Guard", "Wing", "Big"):
            sub = p5[p5["position_group"] == grp]
            benchmarks[grp] = {col: sorted(sub[col].dropna().tolist()) for col in STAT_COLS if col in sub.columns}
        return benchmarks
    except Exception:
        return {}


def get_player_position_group(player_name: str) -> str:
    try:
        conn = sqlite3.connect("scouting_hub.db")
        row = conn.execute("SELECT position_group FROM player_positions WHERE player_name = ?", (player_name,)).fetchone()
        conn.close()
        return row[0] if row else "Wing"
    except Exception:
        return "Wing"


def get_pct(val, sorted_vals: list):
    if not sorted_vals or val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    rank = bisect.bisect_left(sorted_vals, val)
    return 100.0 * rank / len(sorted_vals)


# ==========================================
# PALETTE / COLOR SYSTEM (0-100 Percentile Map)
# ==========================================
def pct_color(pct):
    """Blue (0th pct) → White (50th pct) → Gold (100th pct). Returns (bg_hex, text_hex)."""
    if pct is None:
        return "#EAECF0", "#1A1A1A"
    t = max(0.0, min(100.0, pct)) / 100.0
    if t <= 0.5:
        s = t / 0.5
        r = int(39  + (255 - 39)  * s)
        g = int(116 + (255 - 116) * s)
        b = int(174 + (255 - 174) * s)
    else:
        s = (t - 0.5) / 0.5
        r = int(255 + (255 - 255) * s)
        g = int(255 + (209 - 255) * s)
        b = int(255 + (0   - 255) * s)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    text = "#FFFFFF" if lum < 148 else "#1A1A1A"
    return f"#{r:02x}{g:02x}{b:02x}", text


def stat_tile(label, value, pct=None, show_pct=False):
    bg, fg = pct_color(pct)
    pct_html = ""
    if show_pct and pct is not None:
        pct_html = f"<span style='font-size:13px;font-weight:600;color:{fg};'>{int(round(pct))}<span style='font-size:8px;opacity:.6;'>%</span></span>"
    val_row = (f"<div style='display:flex;justify-content:space-between;align-items:baseline;margin-top:2px;'>"
               f"<span style='font-size:16px;font-weight:700;color:{fg};line-height:1;'>{value}</span>"
               f"{pct_html}</div>")
    return (f"<div style='background:{bg};border-radius:7px;padding:9px 10px 8px;border:1px solid rgba(0,0,0,.05);'>"
            f"<div style='font-size:8px;font-weight:600;letter-spacing:.03em;text-transform:uppercase;color:{fg};opacity:.78;'>{label}</div>{val_row}</div>")


def tile_row(tiles, per_row=4):
    for i in range(0, len(tiles), per_row):
        cols = st.columns(per_row)
        for col, html in zip(cols, tiles[i:i + per_row]):
            col.markdown(html, unsafe_allow_html=True)


def render_pct_stat_cards(cards: list, per_row: int = 4):
    for row_start in range(0, len(cards), per_row):
        row_cards = cards[row_start: row_start + per_row]
        cols = st.columns(per_row)
        for col, (label, val, pct) in zip(cols, row_cards):
            bg, fg = pct_color(pct)
            pct_label = f" ({pct:.0f}th)" if pct is not None else ""
            col.markdown(
                f"""<div style="background:{bg};border-radius:8px;padding:11px 6px 9px;text-align:center;margin:3px 0;min-height:60px;">
                  <div style="font-size:9.5px;color:{fg};opacity:0.9;font-weight:500;letter-spacing:0.3px;line-height:1.2;">{label}</div>
                  <div style="font-size:17px;font-weight:700;color:{fg};margin-top:4px;line-height:1;">{val}</div>
                  <div style="font-size:8px;color:{fg};opacity:0.75;margin-top:2px;">{pct_label}</div>
                </div>""", unsafe_allow_html=True)


@st.cache_data(ttl=3600)
def load_quality_game_stats(max_opp_rank: int) -> pd.DataFrame:
    try:
        conn = sqlite3.connect("scouting_hub.db")
        df = pd.read_sql_query("""
            SELECT player_name AS PLAYER, team_name AS TEAM, COUNT(*) AS GP,
                ROUND(AVG(pts), 1) AS PPG, ROUND(AVG(reb), 1) AS RPG, ROUND(AVG(ast), 1) AS APG,
                ROUND(AVG(tov), 1) AS TOV, ROUND(AVG(stl), 1) AS STL, ROUND(AVG(blk), 1) AS BLK,
                ROUND(CAST(SUM(fg_made) AS REAL) / NULLIF(SUM(fg_att), 0) * 100, 1) AS [FG%],
                ROUND(CAST(SUM(fg3_made) AS REAL) / NULLIF(SUM(fg3_att), 0) * 100, 1) AS [3P%],
                ROUND(CAST(SUM(ft_made) AS REAL) / NULLIF(SUM(ft_att), 0) * 100, 1) AS [FT%],
                ROUND(CAST(SUM(pts) AS REAL) / NULLIF(2.0 * (SUM(fg_att) + 0.44 * SUM(ft_att)), 0) * 100, 1) AS [TS%],
                ROUND((CAST(SUM(fg_made) AS REAL) + 0.5 * SUM(fg3_made)) / NULLIF(SUM(fg_att), 0) * 100, 1) AS [EFG%]
            FROM player_game_logs WHERE opp_rank <= ?
            GROUP BY player_name, team_name HAVING COUNT(*) >= 1 ORDER BY PPG DESC""", conn, params=(max_opp_rank,))
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


def game_log_db_ready() -> bool:
    try:
        conn = sqlite3.connect("scouting_hub.db")
        p = conn.execute("SELECT COUNT(*) FROM player_game_logs").fetchone()[0]
        g = conn.execute("SELECT COUNT(*) FROM game_team_stats").fetchone()[0]
        conn.close()
        return p > 0 and g > 0
    except Exception:
        return False


def get_player_sos(espn_name: str, espn_team: str):
    try:
        conn = sqlite3.connect("scouting_hub.db")
        row = conn.execute("""
            SELECT ROUND(AVG(opp_rank), 0), COUNT(*) FROM player_game_logs
            WHERE player_name = ? AND team_name = ? AND opp_rank < 999""", (espn_name, espn_team)).fetchone()
        conn.close()
        if row and row[1] and row[1] > 0:
            return int(row[0]), int(row[1])
    except Exception:
        pass
    return None, None


@st.cache_data(ttl=3600)
def load_player_shots(player_name: str, team_espn_id=None, max_opp_rank=None) -> pd.DataFrame:
    try:
        conn = sqlite3.connect("scouting_hub.db")
        rank_clause = "AND gl.kp_opp_rank <= :rank" if max_opp_rank else ""
        team_clause = "AND sc.team_id = :team_id" if team_espn_id else ""
        df = pd.read_sql_query(f"""
            SELECT sc.coord_x_norm AS x, sc.coord_y_norm AS y, sc.scoring_play AS made, sc.shot_type, sc.points_attempted AS pts
            FROM shot_chart sc
            JOIN player_game_logs gl ON gl.game_date = sc.game_date AND gl.player_name = sc.player_name AND gl.team_espn_id = sc.team_id
            WHERE sc.player_name = :name AND sc.shot_type != 'MadeFreeThrow' {team_clause} {rank_clause}""",
            conn, params={"name": player_name, "rank": max_opp_rank, "team_id": str(team_espn_id) if team_espn_id else None})
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


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
        if title: ax.set_title(title, color="white", fontsize=10, pad=6)
        return fig
    made = shots_df[shots_df["made"] == 1]; missed = shots_df[shots_df["made"] == 0]
    ax.scatter(missed["x"], missed["y"], c="#4a9eff", s=18, alpha=0.55, linewidths=0.3, edgecolors="#2060bb", zorder=5)
    ax.scatter(made["x"], made["y"], c="#FFD700", s=18, alpha=0.70, linewidths=0.3, edgecolors="#cc9900", zorder=6)
    total = len(shots_df); makes = int(shots_df["made"].sum())
    pct = makes / total * 100 if total else 0
    threes = shots_df[shots_df["pts"] == 3]; twos = shots_df[shots_df["pts"] == 2]
    info = f"{makes}/{total} FG ({pct:.1f}%)  2pt {int(twos['made'].sum())}/{len(twos)}  3pt {int(threes['made'].sum())}/{len(threes)}"
    ax.text(25, -1.2, info, ha="center", va="top", color="#cccccc", fontsize=6.5, zorder=7)
    ax.legend(handles=[mpatches.Patch(color="#FFD700", label=f"Make ({makes})"), mpatches.Patch(color="#4a9eff", label=f"Miss ({total-makes})")],
              loc="upper right", fontsize=7, framealpha=0.25, labelcolor="white", facecolor="#111827", edgecolor="none")
    if title: ax.set_title(title, color="white", fontsize=9, pad=4)
    plt.tight_layout(pad=0.3)
    return fig


def fmt(val, decimals=1, suffix=""):
    if val is None or val == 0.0 or (isinstance(val, float) and math.isnan(val)):
        return "—"
    if decimals == 0:
        return f"{int(round(val))}{suffix}"
    return f"{round(float(val), decimals)}{suffix}"


# ==========================================
# DATA LOADING ENGINE
# ==========================================
load_bar = st.progress(0, text="Loading full scouting base database...")
df_all = load_all_data_v6()
load_bar.progress(100, text="Database ready.")
time.sleep(0.2)
load_bar.empty()

if df_all is None:
    st.error("BartTorvik database request rate-limited. Switch network connections or retry shortly.")
    st.stop()

_gl_ready = game_log_db_ready()
all_player_names = sorted(list(df_all["PLAYER"].unique()))

if "active_player" not in st.session_state:
    st.session_state.active_player = all_player_names[0]

# ==========================================
# GLOBAL APPLICATION HEADER
# ==========================================
head_col1, head_col2 = st.columns([1, 12])
with head_col1:
    st.image("https://cdn.freebiesupply.com/logos/large/2x/ucla-bruins-1-logo-png-transparent.png", width=55)
with head_col2:
    st.markdown("<h2 style='margin: 0; padding-top: 8px; color: #FFFFFF;'>UCLA Transfer Portal Hub & Database</h2>", unsafe_allow_html=True)
st.write("***")

tab_depth, tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Depth Chart",
    "Individual Player Profile",
    "Portal Discovery Engine",
    "Front Office Target Board",
    "Big Board Print View",
    "Player Card / Ranking System"
])

components.html("""
<script>
(function() {
    var savedTab = parseInt(localStorage.getItem('uclaActiveTab') || '0');
    function attachListeners(tabs) {
        tabs.forEach(function(tab, i) {
            tab.addEventListener('click', function() { localStorage.setItem('uclaActiveTab', i); });
        });
    }
    function tryRestore() {
        var tabs = window.parent.document.querySelectorAll('[data-baseweb="tab"]');
        if (tabs.length >= 6) { attachListeners(tabs); if (savedTab > 0) tabs[savedTab].click(); }
        else { setTimeout(tryRestore, 100); }
    }
    setTimeout(tryRestore, 150);
})();
</script>""", height=0, width=0)

# ==========================================
# TAB: DEPTH CHART
# ==========================================
with tab_depth:
    st.subheader("26-27 UCLA Bruins — Depth Chart")
    with st.expander("Edit Roster Structure", expanded=False):
        conn = sqlite3.connect('scouting_hub.db')
        roster_df = pd.read_sql_query("SELECT player_name AS Player, position AS Pos, depth AS Depth, descriptor AS Descriptor, bt_name AS [BT Name] FROM roster ORDER BY position, depth", conn)
        conn.close()
        edited = st.data_editor(roster_df, num_rows="dynamic", hide_index=True, use_container_width=True,
                                column_config={"Pos": st.column_config.SelectboxColumn("Pos", options=["PG", "CG", "SF", "PF", "C"], required=True),
                                               "Depth": st.column_config.NumberColumn("Depth", min_value=1, max_value=10, step=1)}, key="roster_editor")
        if st.button("Save Roster Changes"):
            conn = sqlite3.connect('scouting_hub.db'); cursor = conn.cursor(); cursor.execute("DELETE FROM roster")
            for _, r in edited.iterrows():
                pname = str(r["Player"]).strip() if pd.notna(r["Player"]) else ""
                if not pname: continue
                cursor.execute("INSERT INTO roster (player_name, position, depth, descriptor, bt_name) VALUES (?, ?, ?, ?, ?)",
                               (pname, str(r["Pos"]) if pd.notna(r["Pos"]) else "PG", int(r["Depth"]) if pd.notna(r["Depth"]) else 1, str(r["Descriptor"]) if pd.notna(r["Descriptor"]) else "", str(r["BT Name"]) if pd.notna(r["BT Name"]) else ""))
            conn.commit(); conn.close(); st.success("Roster updated."); st.rerun()

    conn = sqlite3.connect('scouting_hub.db')
    chart_df = pd.read_sql_query("SELECT player_name, position, depth, descriptor, bt_name FROM roster ORDER BY depth", conn)
    conn.close()

    POSITIONS = [("PG", "Point Guard"), ("CG", "Combo Guard"), ("SF", "Small Forward"), ("PF", "Power Forward"), ("C", "Center")]
    pos_cols = st.columns(5)
    for i, (pos_code, pos_label) in enumerate(POSITIONS):
        with pos_cols[i]:
            st.markdown(f"<div style='background-color:#2774AE; color:white; font-weight:bold; text-align:center; padding:8px; border-radius:6px; margin-bottom:12px; font-size:13px; letter-spacing:0.5px;'>{pos_code}<br><span style='font-size:9px; font-weight:400; opacity:0.85;'>{pos_label}</span></div>", unsafe_allow_html=True)
            group = chart_df[chart_df["position"] == pos_code].sort_values("depth")
            if group.empty:
                st.caption("No players assigned")
                continue
            for _, pl in group.iterrows():
                pname = pl["player_name"]; descriptor = pl["descriptor"] if pl["descriptor"] else ""; bt_name = pl["bt_name"] if pl["bt_name"] else ""
                is_open = pname.strip().upper() == "OPEN"; is_starter = int(pl["depth"]) == 1
                if is_open:
                    st.markdown(f"<div style=\"border:2px dashed #FFD100;border-radius:8px;padding:14px 10px;margin-bottom:10px;background-color:rgba(255,209,0,0.06);text-align:center;\"><div style=\"font-size:13px;font-weight:bold;color:#FFD100;\">OPEN</div><div style=\"font-size:10px;color:#FFD100;opacity:0.85;margin-top:2px;\">{descriptor}</div></div>", unsafe_allow_html=True)
                    continue
                stat_line = ""
                if bt_name:
                    match = df_all[df_all["PLAYER"] == bt_name]
                    if not match.empty:
                        s = match.iloc[0]
                        stat_line = f"BPM {s['BPM']:.1f} · USG {s['USG']:.0f}% · eFG {s['EFG']:.0f}%"
                border = "#FFD100" if is_starter else "#CBD5E1"
                starter_badge = "<span style=\"font-size:8px;background:#FFD100;color:#0F172A;font-weight:bold;padding:1px 5px;border-radius:3px;\">STARTER</span>" if is_starter else ""
                card_html = f"""<div style="border:1px solid {border};border-left:4px solid {border};border-radius:6px;padding:9px 10px;margin-bottom:10px;background-color:#FFFFFF;box-shadow:1px 1px 3px rgba(0,0,0,0.05);"><div style="display:flex;justify-content:space-between;align-items:center;"><span style=\"font-size:12.5px;font-weight:bold;color:#0F172A;\">{pname}</span>{starter_badge}</div>{"<div style='font-size:9.5px;color:#2774AE;font-weight:600;margin-top:3px;'>"+stat_line+"</div>" if stat_line else ""}{"<div style='font-size:9.5px;color:#64748B;margin-top:2px;'>"+descriptor+"</div>" if descriptor else ""}</div>"""
                st.markdown(card_html, unsafe_allow_html=True)
                if bt_name and not df_all[df_all["PLAYER"] == bt_name].empty:
                    if st.button(f"View {pname}", key=f"depth_view_{pos_code}_{pname}", use_container_width=True):
                        st.session_state.active_player = bt_name
                        st.rerun()

# ==========================================
# TAB 1: INDIVIDUAL PLAYER SCOUTING
# ==========================================
with tab1:
    st.subheader("Personnel Target Evaluation")
    current_idx = all_player_names.index(st.session_state.active_player)
    selected_dropdown = st.selectbox("Search or select player profile:", all_player_names, index=current_idx)
    if selected_dropdown != st.session_state.active_player:
        st.session_state.active_player = selected_dropdown
        st.rerun()

    current_player = st.session_state.active_player
    p_data = df_all[df_all["PLAYER"] == current_player].iloc[0]

    conn = sqlite3.connect('scouting_hub.db'); cursor = conn.cursor()
    cursor.execute("SELECT scout_name, priority_tier, position, role, rumored_nil, personal_val, agent, agency, photo_url, eval_date, notes FROM player_notes WHERE player_name = ?", (current_player,))
    db_row = cursor.fetchone()

    saved_scout = db_row[0] if db_row else "Trey Doty"; saved_tier = db_row[1] if db_row else "Watchlist"; saved_pos = db_row[2] if db_row else "PG"
    saved_role = db_row[3] if db_row else ""; saved_nil = db_row[4] if db_row else ""; saved_val = db_row[5] if db_row else ""
    saved_agent = db_row[6] if db_row else ""; saved_agency = db_row[7] if db_row else ""; saved_photo = db_row[8] if db_row else ""
    saved_date = db_row[9] if db_row else "No previous evaluations logged"; saved_notes = db_row[10] if db_row else ""

    if not saved_photo:
        saved_photo = fetch_sr_headshot_silent(current_player, p_data["TEAM"])
        if db_row and saved_photo:
            cursor.execute("UPDATE player_notes SET photo_url = ? WHERE player_name = ?", (saved_photo, current_player))
            conn.commit()
    conn.close()

    col_img, col_info = st.columns([1, 5])
    with col_img:
        if saved_photo: st.image(saved_photo, width=130)
        else: st.info("No headshot logged")
    with col_info:
        c1, c2, c3, c4 = st.columns([2.5, 1, 1, 1])
        c1.metric("Program", p_data["TEAM"]); c2.metric("Conference", p_data["CONF"]); c3.metric("Class", p_data["CLASS"]); c4.metric("Height", p_data["HEIGHT"])
        st.caption(f"📅 **Last Evaluation Update Stamped:** {saved_date}")

    st.write("**Player Metrics Line**")
    _split = st.radio("Competition split", ["All Games", "Top 100", "Top 50"], horizontal=True, key="profile_split", label_visibility="collapsed")
    _max_rank = None if _split == "All Games" else (100 if _split == "Top 100" else 50)

    if not _gl_ready:
        st.info("Run database engine to populate granular splits.")
    else:
        _box_df = load_consistent_boxscore_stats(_max_rank)
        _p5_bench = load_p5_percentile_benchmarks(df_all, _max_rank)
        _pos_group = get_player_position_group(current_player)
        _pbox = _box_df[_box_df["PLAYER"] == current_player]
        if len(_pbox) > 1:
            _team_match = _pbox[_pbox["TEAM"].str.contains(p_data["TEAM"], case=False, na=False)]
            if not _team_match.empty: _pbox = _team_match

        if _pbox.empty:
            st.info(f"No splits found for {current_player} in {_split} games.")
        else:
            r = _pbox.iloc[0]; gp = int(r["GP"]); bench = _p5_bench.get(_pos_group, {})
            def _card(label, stat_key, val=None, higher_is_better=True):
                v = float(r[stat_key]) if val is None else float(val)
                pct = get_pct(v, sorted(bench.get(stat_key, [])))
                if pct is not None and not higher_is_better: pct = 100 - pct
                return (label, fmt(v), pct)
            sos_rank, _ = get_player_sos(current_player, r["TEAM"])
            cards = [
                ("Avg Opp Rank (SOS)", f"Avg Rank {sos_rank}" if sos_rank else "—", None),
                _card("PPG", "PPG"), _card("TS%", "TS"), _card("eFG%", "EFG"), _card("USG%", "USG"),
                _card("AST%", "AST_PCT"), _card("OREB%", "OR_PCT"), _card("DREB%", "DR_PCT"),
                _card("BLK%", "BLK_PCT"), _card("STL%", "STL_PCT"), _card("FT Rate", "FTR"),
                _card("2P%", "TWO_P"), _card("3P%", "THREE_P"), _card("FT%", "FT_PCT")
            ]
            if "ORTG_KP" in r.index and not pd.isna(r["ORTG_KP"]):
                cards += [_card("KP ORtg", "ORTG_KP"), _card("KP Usage%", "USAGE_KP")]
            render_pct_stat_cards(cards, per_row=4)

            _shots = load_player_shots(current_player, r["team_espn_id"] if "team_espn_id" in r.index else None, _max_rank)
            if not _shots.empty:
                st.write("**Shot Chart Visualization**")
                fig = draw_shot_chart(_shots, title=f"{current_player} · {_split}")
                cc, _ = st.columns([3, 2]); cc.pyplot(fig, use_container_width=True); plt.close(fig)

    st.write("***")
    col_scout, col_tier = st.columns(2)
    scout_input = col_scout.text_input("Assigned Staff Member / Scout Name:", value=saved_scout)
    tier_input = col_tier.selectbox("Recruitment Board Category Hierarchy:", ["High Priority", "Watchlist", "Pass"], index=["High Priority", "Watchlist", "Pass"].index(saved_tier))

    col_pos, col_role = st.columns(2)
    position_input = col_pos.selectbox("Primary Position Grouping:", ["PG", "CG", "W", "F", "C"], index=["PG", "CG", "W", "F", "C"].index(saved_pos) if saved_pos in ["PG", "CG", "W", "F", "C"] else 0)
    role_input = col_role.text_input("Projected Tactical Role Allocation:", value=saved_role)

    col_agent, col_agency, col_nil, col_val = st.columns(4)
    agent_input = col_agent.text_input("Primary Agent:", value=saved_agent)
    agency_input = col_agency.text_input("Agency Affiliation:", value=saved_agency)
    nil_input = col_nil.text_input("Rumored NIL Requirements:", value=saved_nil)
    val_input = col_val.text_input("Internal Valuation Tag:", value=saved_val)

    photo_input = st.text_input("Manual Headshot URL Override:", value=saved_photo)
    notes_input = st.text_area("Detailed Scouting Intel and Background Background Evaluation:", value=saved_notes, height=150)

    if st.button("Commit Intel to Board"):
        ex_date = datetime.now().strftime("%Y-%m-%d")
        conn = sqlite3.connect('scouting_hub.db'); cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO player_notes (player_name, team_name, scout_name, priority_tier, position, role, rumored_nil, personal_val, agent, agency, photo_url, eval_date, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(player_name) DO UPDATE SET
            scout_name=excluded.scout_name, priority_tier=excluded.priority_tier, position=excluded.position, role=excluded.role, rumored_nil=excluded.rumored_nil,
            personal_val=excluded.personal_val, agent=excluded.agent, agency=excluded.agency, photo_url=excluded.photo_url, eval_date=excluded.eval_date, notes=excluded.notes''',
            (current_player, p_data["TEAM"], scout_input, tier_input, position_input, role_input, nil_input, val_input, agent_input, agency_input, photo_input if photo_input else saved_photo, ex_date, notes_input))
        conn.commit(); conn.close(); st.success("Scouting record updated successfully."); st.rerun()

# ==========================================
# TAB 2: PORTAL DISCOVERY ENGINE
# ==========================================
with tab2:
    st.subheader("Database Sifting & Portal Filtering")
    _disc_split = st.radio("Discovery split range", ["All Games", "Top 100", "Top 50"], horizontal=True, key="discovery_split", label_visibility="collapsed")
    _disc_max_rank = 100 if _disc_split == "Top 100" else (50 if _disc_split == "Top 50" else None)

    if _disc_max_rank is not None and _gl_ready:
        disc_base_df = load_consistent_boxscore_stats(_disc_max_rank).rename(columns={"OR_PCT": "OR", "DR_PCT": "DR", "AST_PCT": "AST", "BLK_PCT": "BLK", "STL_PCT": "STL"})
        _meta = df_all[["PLAYER", "CONF", "CLASS", "HEIGHT", "BPM", "OBPM", "DBPM", "PRPG", "MIN_PCT", "ORTG", "THREE_P_100"]].drop_duplicates("PLAYER")
        disc_base_df = disc_base_df.merge(_meta, on="PLAYER", how="left")
    else:
        disc_base_df = df_all

    with st.expander("Advanced Database Filters", expanded=False):
        col_cat1, col_cat2, col_cat3 = st.columns(3)
        selected_confs = col_cat1.multiselect("Filter by Conference:", sorted(list(df_all["CONF"].unique())))
        selected_teams = col_cat2.multiselect("Filter by Team:", sorted(list(df_all["TEAM"].unique())))
        selected_classes = col_cat3.multiselect("Filter by Class:", sorted(list(df_all["CLASS"].dropna().unique())))

        f1, f2, f3, f4 = st.columns(4)
        min_pct = f1.slider("Min %", 0.0, 100.0, (0.0, 100.0)); usg = f1.slider("Usage %", 0.0, 50.0, (0.0, 50.0)); bpm = f1.slider("Box BPM", -20.0, 30.0, (-20.0, 30.0))
        ortg = f2.slider("O-Rating", 0.0, 150.0, (0.0, 150.0)); efg = f2.slider("eFG %", 0.0, 100.0, (0.0, 100.0)); ts = f2.slider("TS %", 0.0, 100.0, (0.0, 100.0))
        three_p = f3.slider("3P %", 0.0, 100.0, (0.0, 100.0)); three_p_100 = f3.slider("3PA/100", 0.0, 30.0, (0.0, 30.0)); ftr = f3.slider("FTR", 0.0, 150.0, (0.0, 150.0))
        ast = f4.slider("Ast %", 0.0, 60.0, (0.0, 60.0)); tov = f4.slider("TO %", 0.0, 100.0, (0.0, 100.0)); blk = f4.slider("Blk %", 0.0, 30.0, (0.0, 30.0))

    filtered_df = disc_base_df.copy()
    if selected_confs: filtered_df = filtered_df[filtered_df["CONF"].isin(selected_confs)]
    if selected_teams: filtered_df = filtered_df[filtered_df["TEAM"].isin(selected_teams)]
    if selected_classes: filtered_df = filtered_df[filtered_df["CLASS"].isin(selected_classes)]

    def _col_filter(df, col, lo, hi): return df[df[col].between(lo, hi)] if col in df.columns else df
    filtered_df = _col_filter(filtered_df, "MIN_PCT", min_pct[0], min_pct[1])
    filtered_df = _col_filter(filtered_df, "BPM", bpm[0], bpm[1])
    filtered_df = _col_filter(filtered_df, "ORTG", ortg[0], ortg[1])
    filtered_df = _col_filter(filtered_df, "USG", usg[0], usg[1])
    filtered_df = _col_filter(filtered_df, "EFG", efg[0], efg[1])
    filtered_df = _col_filter(filtered_df, "TS", ts[0], ts[1])
    filtered_df = _col_filter(filtered_df, "THREE_P", three_p[0], three_p[1])

    sort_col = "PRPG" if "PRPG" in filtered_df.columns else "PPG"
    filtered_df = filtered_df.sort_values(by=sort_col, ascending=False)
    ordered_cols = ["PLAYER", "TEAM", "CONF", "CLASS", "HEIGHT", "GP", "PPG", "PRPG", "BPM", "MIN_PCT", "USG", "EFG", "TS"]
    filtered_df = filtered_df[[c for c in ordered_cols if c in filtered_df.columns]]

    st.write(f"**Discovery Profiles Found:** {len(filtered_df)} items matching criteria matches.")
    event_discovery = st.dataframe(filtered_df, hide_index=True, on_select="rerun", selection_mode="single-row", height=500)
    if event_discovery.selection.rows:
        clicked_player = filtered_df.iloc[event_discovery.selection.rows[0]]["PLAYER"]
        if st.session_state.active_player != clicked_player:
            st.session_state.active_player = clicked_player; st.rerun()

# ==========================================
# TAB 3: FRONT OFFICE TARGET BOARD
# ==========================================
with tab3:
    st.subheader("Central Board Records")
    conn = sqlite3.connect('scouting_hub.db')
    db_df = pd.read_sql_query("SELECT player_name AS PLAYER, team_name AS TEAM, position AS POS, role AS ROLE, agent AS AGENT, rumored_nil AS [RUMORED NIL], personal_val AS [OUR VALUE], priority_tier AS TIER FROM player_notes", conn)
    conn.close()

    if db_df.empty: st.info("No targets currently tracked on the system target board.")
    else:
        for tier in ["High Priority", "Watchlist", "Pass"]:
            st.markdown(f"### {tier}")
            tier_filtered = db_df[db_df["TIER"] == tier]
            if tier_filtered.empty: st.write("*No targets assigned here.*")
            else:
                ev_board = st.dataframe(tier_filtered.drop(columns=["TIER"]), hide_index=True, on_select="rerun", selection_mode="single-row", key=f"board_t_{tier}")
                if ev_board.selection.rows:
                    clicked_player = tier_filtered.iloc[ev_board.selection.rows[0]]["PLAYER"]
                    if st.session_state.active_player != clicked_player: st.session_state.active_player = clicked_player; st.rerun()

# ==========================================
# TAB 4: PRINTS / VISUAL BOARD VIEW
# ==========================================
with tab4:
    st.subheader("Staff Roster Print Layout")
    filter_tier = st.selectbox("Select Target Priority Tier to Display:", ["High Priority", "Watchlist", "All Records"], key="print_tier_select")
    conn = sqlite3.connect('scouting_hub.db')
    board_data = pd.read_sql_query("SELECT * FROM player_notes" if filter_tier == "All Records" else "SELECT * FROM player_notes WHERE priority_tier = ?", conn, params=() if filter_tier == "All Records" else (filter_tier,))
    conn.close()

    if board_data.empty: st.warning("No targets mapped to the print view tier criteria.")
    else:
        st_cols = st.columns(5)
        for i, pos_group in enumerate(["PG", "CG", "W", "F", "C"]):
            with st_cols[i]:
                st.markdown(f"<div style='background-color:#1E3A8A;color:white;font-weight:bold;text-align:center;padding:6px;border-radius:4px;margin-bottom:12px;'>{pos_group}</div>", unsafe_allow_html=True)
                group_players = board_data[board_data["position"] == pos_group]
                for _, player in group_players.iterrows():
                    p_name = player["player_name"]; stat_match = df_all[df_all["PLAYER"] == p_name]
                    s_line = f"BPM: {stat_match.iloc[0]['BPM']} | USG: {stat_match.iloc[0]['USG']}%" if not stat_match.empty else "No metrics line"
                    st.markdown(f"""
                        <div style="border:1px solid #CBD5E1;border-radius:6px;padding:10px;margin-bottom:12px;background-color:#FFFFFF;">
                        <span style="font-size:13px;font-weight:bold;color:#0F172A;">{p_name}</span><br>
                        <span style="font-size:11px;color:#475569;font-weight:600;">{player['team_name']}</span>
                        <div style="font-size:10px;font-weight:bold;color:#1E40AF;margin-top:4px;">🎯 {player['role'] or 'Unassigned'}</div>
                        <div style="font-size:9.5px;color:#475569;margin-top:2px;">📊 {s_line}</div></div>""", unsafe_allow_html=True)

# ==========================================
# TAB 5: PLAYER CARD / RANKING SYSTEM
# ==========================================
with tab5:
    st.subheader("Target Player Evaluation Matrix")
    
    # Fully defined and resolved target cards to eliminate data truncation errors
    PORTAL_PLAYERS = [
        {
            "name": "Dillian Shaw", "school": "Saint Mary's", "pos": "G/Wing", "cls": "Fr", "height": "6'7\"", "tier": "Tier 3",
            "shooting": 76, "playmaking": 68, "defense": 88, "rebounding": 64,
            "tags": ["Versatile Defender", "3.2 DBPM", "Real Shooter", "Winning Player"],
            "projection": "High-major role wing", "role": "Two-Way Role Wing", "ts": "58.6", "usg": "17.0", "p3": "42.0",
            "writeup": "High-level role wing who understands team basketball. Strong defender (3.2 DBPM), long, switchable, moves his feet well. Offensively efficient and disciplined. 59% TS, 42% from three on real volume. Projects as a high-major role wing who defends multiple spots, shoots it, and plays within structure."
        },
        {
            "name": "Allen Graves", "school": "Santa Clara", "pos": "PF", "cls": "Fr", "height": "6'9\"", "tier": "Tier 3",
            "shooting": 82, "playmaking": 62, "defense": 68, "rebounding": 72,
            "tags": ["Efficient Stretch 4", "Screening IQ", "Low-Mistake"],
            "projection": "High-major starting 4", "role": "Stretch 4 / Screener", "ts": "63.0", "usg": "22.0", "p3": "40.0",
            "writeup": "Efficient, low-mistake stretch 4 with real feel. 22% usage on 130 offensive rating layout parameters. Elite pick-and-pop option with high processing speed out of short rolls. Shows discipline on defensive rotations."
        }
    ]

    DEMO_CARDS = [
        {"name": "Trent Perry",     "team": "UCLA", "pos": "GUARD",  "bt": "Trent Perry"},
        {"name": "Jaylen Petty",    "team": "UCLA", "pos": "GUARD",  "bt": "Jaylen Petty"},
        {"name": "Eric Dailey Jr.", "team": "UCLA", "pos": "WING",   "bt": "Eric Dailey Jr."},
        {"name": "Xavier Booker",   "team": "UCLA", "pos": "CENTER", "bt": "Xavier Booker"},
    ]

    POS_METRICS = {
        "GUARD":  [("MIN%", "MIN_PCT", 1, True), ("ORTG", "ORTG", 1, True), ("AST%", "AST", 1, True), ("TO%", "TO", 1, False), ("STL%", "STL", 1, True), ("BPM", "BPM", 1, True)],
        "WING":   [("MIN%", "MIN_PCT", 1, True), ("BPM", "BPM", 1, True), ("STL%", "STL", 1, True), ("BLK%", "BLK", 1, True), ("DREB%", "DR", 1, True), ("OREB%", "OR", 1, True)],
        "CENTER": [("MIN%", "MIN_PCT", 1, True), ("ORTG", "ORTG", 1, True), ("ORB%", "OR", 1, True), ("DREB%", "DR", 1, True), ("BLK%", "BLK", 1, True), ("STL%", "STL", 1, True)],
    }

    TORVIK_PCTLS = {}
    for c in ["PPG", "ORTG", "USG", "EFG", "TS", "OR", "DR", "AST", "TO", "BLK", "STL", "FTR", "TWO_P", "THREE_P", "THREE_P_100", "BPM", "OBPM", "DBPM", "PRPG", "MIN_PCT"]:
        if c in df_all.columns: TORVIK_PCTLS[c] = sorted(pd.to_numeric(df_all[c], errors="coerce").dropna().tolist())

    def _pctile(val, sorted_vals, higher_better=True):
        if not sorted_vals or val is None or (isinstance(val, float) and math.isnan(val)): return None
        r = bisect.bisect_left(sorted_vals, val)
        p = 100.0 * r / len(sorted_vals)
        return p if higher_better else 100 - p

    def card_header(card, trow):
        ht = str(trow.get("HEIGHT", "")) if trow is not None else ""
        yr = str(trow.get("CLASS", "")) if trow is not None else ""
        meta = " · ".join([x for x in [card["team"], ht, yr] if x])
        return f"""
            <div style='display:flex;justify-content:space-between;align-items:flex-start;'>
            <div><div style='font-size:20px;font-weight:800;color:#111827;'>{card['name']}</div>
            <div style='font-size:11px;color:#6b7280;margin-top:2px;'>{meta}</div></div>
            <span style='font-size:9px;font-weight:700;letter-spacing:.06em;background:{UCLA_GOLD};color:#111827;padding:3px 9px;border-radius:4px;'>{card['pos']}</span></div>"""

    if "card_back" not in st.session_state: st.session_state.card_back = None

    for card in DEMO_CARDS:
        match = df_all[df_all["PLAYER"] == card["bt"]]; trow = match.iloc[0] if not match.empty else None
        with st.container(border=True):
            st.markdown(card_header(card, trow), unsafe_allow_html=True)
            
            st.markdown("<div style='font-size:9px;letter-spacing:.12em;color:#9AA3AF;margin:10px 0 5px;'>GENERAL LINEUP AGGREGATES</div>", unsafe_allow_html=True)
            ppg = float(trow.get("PPG", 0)) if trow is not None else None
            two_p = float(trow.get("TWO_P", 0)) if trow is not None else None
            three_p = float(trow.get("THREE_P", 0)) if trow is not None else None
            
            tiles = [
                stat_tile("PTS", fmt(ppg), _pctile(ppg, TORVIK_PCTLS.get("PPG", []))),
                stat_tile("2PT%", fmt(two_p), _pctile(two_p, TORVIK_PCTLS.get("TWO_P", []))),
                stat_tile("3PT%", fmt(three_p), _pctile(three_p, TORVIK_PCTLS.get("THREE_P", []))),
            ]
            tile_row(tiles, per_row=3)
            
            if st.button(f"Analyze Target Profile: {card['name']}", key=f"drill_{card['name']}"):
                st.session_state.card_back = card["name"] if st.session_state.card_back != card["name"] else None
            
            if st.session_state.card_back == card["name"]:
                st.divider(); st.markdown(f"**{card['name']} — Deep Advanced Attributes**")
                metrics = POS_METRICS.get(card["pos"], POS_METRICS["WING"])
                p_tiles = []
                for label, key, dec, hb in metrics:
                    v = float(trow.get(key)) if trow is not None else None
                    p_tiles.append(stat_tile(label, fmt(v, dec), _pctile(v, TORVIK_PCTLS.get(key, []), hb)))
                tile_row(p_tiles, per_row=len(p_tiles))

    st.write("---")
    st.write("**Portal Profile Board Evaluation Matrix**")
    for pl in PORTAL_PLAYERS:
        with st.expander(f"{pl['name']} ({pl['school']}) — {pl['tier']}", expanded=True):
            col_w1, col_w2 = st.columns([1, 2])
            with col_w1:
                st.markdown(f"**Position:** {pl['pos']} | **Height:** {pl['height']}")
                st.markdown(f"**Role Designation:** {pl['role']}")
                st.write(f"TS%: {pl['ts']} | USG%: {pl['usg']} | 3P%: {pl['p3']}%")
            with col_w2:
                st.markdown("**Staff Analyst Overview:**")
                st.write(pl["writeup"])
                st.caption(f"Tags: {', '.join(pl['tags'])}")
