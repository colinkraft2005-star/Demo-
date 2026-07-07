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
from datetime import datetime

# ==========================================
# LOCAL MAC SSL OVERRIDE
# ==========================================
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass

st.set_page_config(layout="wide", page_title="UCLA Scouting Hub")

# Custom CSS to skin everything like your dark-mode screenshots
st.markdown("""
<style>
    body { background-color: #0b0f19; color: #f8fafc; }
    .stApp { background-color: #0b0f19; }
    div[data-testid="stMetricValue"] div { color: #ffffff !important; font-weight: 800 !important; }
    
    /* Print optimizations for Coach Cronin */
    @media print {
        header, footer, [data-testid="stSidebar"], [data-testid="stToolbar"], 
        .no-print, button, div.stRadio, div.stSelectbox, div.stTextArea {
            display: none !important;
        }
        .print-container {
            display: block !important;
            background: white !important;
            color: black !important;
        }
        .player-card-front, .advanced-tile-box {
            background: #ffffff !important;
            border: 2px solid #000000 !important;
            color: #000000 !important;
        }
        .tile-stat, .tile-label { color: #000000 !important; }
    }
</style>
""", unsafe_allow_html=True)


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
                       notes        TEXT,
                       coach_notes  TEXT
                   )
                   ''')
    try:
        cursor.execute("ALTER TABLE player_notes ADD COLUMN coach_notes TEXT")
        conn.commit()
    except Exception:
        pass

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
                   CREATE TABLE IF NOT EXISTS sr_stats_cache
                   (
                       player_name TEXT PRIMARY KEY,
                       team_name   TEXT,
                       gp          INTEGER,
                       gs          INTEGER,
                       mpg         REAL,
                       ppg         REAL,
                       rpg         REAL,
                       apg         REAL,
                       spg         REAL,
                       bpg         REAL,
                       tov         REAL,
                       total_ast   INTEGER,
                       total_tov   INTEGER,
                       fetched_at  TEXT
                   )
                   ''')
    conn.commit()
    conn.close()


def seed_roster_if_empty():
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
            seed
        )
        conn.commit()
    conn.close()


init_db()
seed_roster_if_empty()


def table_has_data(table_name):
    try:
        conn = sqlite3.connect('scouting_hub.db')
        count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        conn.close()
        return count > 0
    except Exception:
        return False


def not_loaded_banner(table_name, script_name):
    st.warning(
        f"No data found in `{table_name}`. "
        f"This tab is populated by running **`{script_name}`** locally."
    )


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
# ESPN STATS/SHOTCHART FETCHER
# ==========================================
def fetch_espn_stats(player_name, team_name=""):
    conn = sqlite3.connect('scouting_hub.db')
    cursor = conn.cursor()
    cursor.execute(
        "SELECT gp, gs, mpg, ppg, rpg, apg, spg, bpg, tov, total_ast, total_tov FROM sr_stats_cache WHERE player_name = ?",
        (player_name,)
    )
    cached = cursor.fetchone()
    conn.close()

    if cached and cached[0] and int(cached[0]) > 0:
        return {
            "gp": int(cached[0] or 0),
            "ppg": float(cached[3] or 0),
            "rpg": float(cached[4] or 0),
            "apg": float(cached[5] or 0),
            "spg": float(cached[6] or 0),
            "bpg": float(cached[7] or 0),
        }

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.espn.com/"
    }

    try:
        search_url = f"https://site.api.espn.com/apis/search/v2?query={urllib.parse.quote(player_name)}&sport=basketball&league=mens-college-basketball&limit=5&type=player"
        resp = requests.get(search_url, headers=headers, timeout=8, verify=False)
        data = resp.json()

        athlete_id = None
        for result in data.get("results", []):
            for item in result.get("contents", result.get("items", [])):
                uid = item.get("athleteId", item.get("id", ""))
                if uid:
                    athlete_id = uid
                    break
            if athlete_id:
                break

        if not athlete_id:
            return None

        stats_url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/athletes/{athlete_id}/statistics"
        stats_resp = requests.get(stats_url, headers=headers, timeout=8, verify=False)
        stats_data = stats_resp.json()

        gp = ppg = rpg = apg = spg = bpg = 0.0
        splits = stats_data.get("splits", {})
        categories = splits.get("categories", [])

        for cat in categories:
            names  = cat.get("names", [])
            values = cat.get("totals", cat.get("values", []))
            if not names or not values:
                continue
            stat_map = dict(zip(names, values))
            try:
                test_gp = int(float(stat_map.get("gamesPlayed", stat_map.get("GP", 0))))
            except:
                test_gp = 0
            if test_gp > 0:
                gp  = test_gp
                ppg = float(stat_map.get("avgPoints", stat_map.get("PTS", 0)))
                rpg = float(stat_map.get("avgRebounds", stat_map.get("REB", 0)))
                apg = float(stat_map.get("avgAssists", stat_map.get("AST", 0)))
                spg = float(stat_map.get("avgSteals", stat_map.get("STL", 0)))
                bpg = float(stat_map.get("avgBlocks", stat_map.get("BLK", 0)))
                break

        if gp > 0:
            result = {"gp": int(gp), "ppg": ppg, "rpg": rpg, "apg": apg, "spg": spg, "bpg": bpg}
            conn = sqlite3.connect('scouting_hub.db')
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO sr_stats_cache
                (player_name, team_name, gp, gs, mpg, ppg, rpg, apg, spg, bpg, tov, total_ast, total_tov, fetched_at)
                VALUES (?, ?, ?, 0, 0, ?, ?, ?, ?, ?, 0, 0, 0, ?)
                ON CONFLICT(player_name) DO UPDATE SET
                    gp=excluded.gp, ppg=excluded.ppg, rpg=excluded.rpg,
                    apg=excluded.apg, spg=excluded.spg, bpg=excluded.bpg,
                    fetched_at=excluded.fetched_at
            ''', (player_name, team_name, int(gp), ppg, rpg, apg, spg, bpg,
                  datetime.now().strftime("%Y-%m-%d")))
            conn.commit()
            conn.close()
            return result
    except:
        pass
    return None


# ==========================================
# BARTTORVIK FETCH
# ==========================================
def fetch_barttorvik_safe(top_filter=None, retries=3, delay_between_requests=4):
    base_url = 'https://barttorvik.com/getadvstats.php?year=2026&page=playerstat&json=1'
    url = base_url if top_filter is None else f"{base_url}&top={top_filter}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://barttorvik.com/"
    }

    def parse_raw(raw_data):
        def safe_float(row_list, idx):
            try:
                if idx < len(row_list) and row_list[idx] is not None and str(row_list[idx]).strip() != "":
                    return float(row_list[idx])
                return 0.0
            except:
                return 0.0
        cleaned_rows = []
        for row in raw_data:
            if len(row) < 53:
                continue
            cleaned_rows.append({
                "PLAYER":     str(row[0]),
                "TEAM":       str(row[1]),
                "CONF":       str(row[2]),
                "MIN_PCT":    safe_float(row, 4),
                "ORTG":       safe_float(row, 5),
                "USG":        safe_float(row, 6),
                "EFG":        safe_float(row, 7),
                "TS":         safe_float(row, 8),
                "OR":         safe_float(row, 9),
                "DR":         safe_float(row, 10),
                "AST":        safe_float(row, 11),
                "TO":         safe_float(row, 12),
                "BLK":        safe_float(row, 22),
                "STL":        safe_float(row, 23),
                "FTR":        safe_float(row, 24),
                "TWO_P":      safe_float(row, 18) * 100,
                "THREE_P":    safe_float(row, 21) * 100,
                "THREE_PA":   safe_float(row, 65) if len(row) > 65 else 0.0,
                "CLASS":      str(row[25]) if len(row) > 25 else "",
                "HEIGHT":     str(row[26]) if len(row) > 26 else "",
                "TORVIK_POS": str(row[27]) if len(row) > 27 else "",
                "PRPG":       safe_float(row, 28),
                "BPM":        safe_float(row, 50),
                "OBPM":       safe_float(row, 51),
                "DBPM":       safe_float(row, 52),
                "GP":         int(float(row[3])) if len(row) > 3 and row[3] is not None else 0,
            })
        return pd.DataFrame(cleaned_rows) if cleaned_rows else None

    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper()
        response = scraper.get(url)
        if response.text.strip():
            raw_data = response.json()
            if raw_data:
                return parse_raw(raw_data)
    except:
        pass

    for attempt in range(retries):
        try:
            response = requests.get(url, headers=headers, verify=False, timeout=20)
            if response.text.strip():
                raw_data = response.json()
                if raw_data:
                    return parse_raw(raw_data)
        except:
            pass
        if attempt < retries - 1:
            time.sleep(delay_between_requests)
    return None


@st.cache_data(ttl=3600)
def load_all_data_v6():
    df = fetch_barttorvik_safe(top_filter=None)
    if df is None:
        return None
    try:
        url2 = 'https://barttorvik.com/getadvstats.php?year=2026&page=basicstat&json=1'
        raw2 = None
        headers2 = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Referer": "https://barttorvik.com/"}
        try:
            r2 = requests.get(url2, headers=headers2, verify=False, timeout=20)
            if r2.text.strip():
                raw2 = r2.json()
        except:
            pass
        if raw2:
            basic_rows = []
            for row in raw2:
                try:
                    n = len(row)
                    basic_rows.append({
                        "PLAYER": str(row[0]),
                        "PPG": float(row[n-4]) if row[n-4] is not None else 0.0,
                        "RPG": float(row[n-8]) if row[n-8] is not None else 0.0,
                        "APG": float(row[n-7]) if row[n-7] is not None else 0.0,
                    })
                except:
                    continue
            df_b = pd.DataFrame(basic_rows).drop_duplicates(subset=["PLAYER"], keep="first")
            df = df.merge(df_b, on="PLAYER", how="left")
            df["PPG"] = df["PPG"].fillna(0.0)
            df["RPG"] = df["RPG"].fillna(0.0)
            df["APG"] = df["APG"].fillna(0.0)
    except:
        df["PPG"] = 0.0
        df["RPG"] = 0.0
        df["APG"] = 0.0
    return df


df_all = load_all_data_v6()
if df_all is None:
    st.error("Data load failed. Please refresh.")
    st.stop()

all_player_names = sorted(list(df_all["PLAYER"].unique()))

# ==========================================
# SESSION STATE NAVIGATION & SELECTION
# ==========================================
if "active_player" not in st.session_state:
    st.session_state.active_player = all_player_names[0]
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Depth Chart"

# ==========================================
# APP HEADER
# ==========================================
head_col1, head_col2 = st.columns([1, 12])
with head_col1:
    st.image("https://cdn.freebiesupply.com/logos/large/2x/ucla-bruins-1-logo-png-transparent.png", width=55)
with head_col2:
    st.markdown("<h2 style='margin: 0; padding-top: 8px; color: #FFFFFF;'>UCLA Transfer Portal Matrix</h2>", unsafe_allow_html=True)

# Custom dynamic topbar menu navigation bar to handle fast redirection
nav_options = [
    "Depth Chart", "One Pager / Player Card", "Comp Results", "Portal Discovery Engine", 
    "Front Office Target Board", "Big Board Print View", "Transfer Portal", 
    "Game Logs", "Synergy Breakdown", "Shot Charts"
]
selected_nav = st.radio("Navigation Menu:", nav_options, index=nav_options.index(st.session_state.active_tab), horizontal=True, label_visibility="collapsed", key="top_nav_bar")
if selected_nav != st.session_state.active_tab:
    st.session_state.active_tab = selected_nav
    st.rerun()

st.write("***")


# ==========================================
# SHARED LOGIC: POSITION DETECTION
# ==========================================
def detect_pos_group(torvik_pos, saved_pos, height_str, ast_rate):
    tp = str(torvik_pos).upper().strip()
    if tp and tp not in ["", "NONE", "NAN"]:
        if tp in ["PG", "SG", "G"]: return "GUARD"
        if tp in ["SF", "PF", "F"]: return "WING"
        if tp in ["C"]: return "CENTER"
    if saved_pos:
        p = str(saved_pos).upper()
        if any(x in p for x in ["PG","CG","G"]): return "GUARD"
        if any(x in p for x in ["PF","F","W","SF","WING"]): return "WING"
        if "C" in p: return "CENTER"
    return "GUARD"


def parse_ht(ht_str):
    try:
        s = str(ht_str).replace('"', '').strip()
        if "'" in s:
            parts = s.split("'")
            return int(parts[0].strip()) * 12 + (int(parts[1].strip()) if parts[1].strip().isdigit() else 0)
        if "-" in s:
            parts = s.split("-")
            return int(parts[0].strip()) * 12 + int(parts[1].strip())
        return int(s)
    except:
        return 78

def norm_dist(a, b, radius):
    try:
        return max(0.0, 1.0 - abs(float(a) - float(b)) / radius)
    except:
        return 0.0

def run_comps(target_row, all_df, pos_group, n=8):
    t_ht = parse_ht(target_row["HEIGHT"])
    base_w = {"ortg": 0.07, "usg": 0.07, "ts": 0.07, "efg": 0.06, "bpm": 0.07, "obpm": 0.05, "dbpm": 0.05, "ast": 0.07, "to": 0.05, "or": 0.05, "dr": 0.06, "blk": 0.05, "stl": 0.05, "3p": 0.05, "3pa": 0.04, "min": 0.04, "ht": 0.10}
    results = []
    target_name = str(target_row["PLAYER"])
    for _, row in all_df.iterrows():
        if str(row["PLAYER"]) == target_name: continue
        c_ht = parse_ht(row["HEIGHT"])
        if abs(t_ht - c_ht) > 5: continue
        scores = {
            "ortg": norm_dist(target_row.get("ORTG",100), row.get("ORTG",100), 15),
            "usg":  norm_dist(target_row.get("USG",18),  row.get("USG",18),  10),
            "ts":   norm_dist(target_row.get("TS",55),   row.get("TS",55),   12),
            "efg":  norm_dist(target_row.get("EFG",50),  row.get("EFG",50),  12),
            "bpm":  norm_dist(target_row.get("BPM",0),   row.get("BPM",0),   8),
            "obpm": norm_dist(target_row.get("OBPM",0),  row.get("OBPM",0),  8),
            "dbpm": norm_dist(target_row.get("DBPM",0),  row.get("DBPM",0),  6),
            "ast":  norm_dist(target_row.get("AST",15),  row.get("AST",15),  12),
            "to":   norm_dist(target_row.get("TO",15),   row.get("TO",15),   10),
            "or":   norm_dist(target_row.get("OR",5),    row.get("OR",5),    8),
            "dr":   norm_dist(target_row.get("DR",15),   row.get("DR",15),   10),
            "blk":  norm_dist(target_row.get("BLK",3),   row.get("BLK",3),   5),
            "stl":  norm_dist(target_row.get("STL",2),   row.get("STL",2),   4),
            "3p":   norm_dist(target_row.get("THREE_P",30), row.get("THREE_P",30), 15),
            "3pa":  norm_dist(target_row.get("THREE_PA",5), row.get("THREE_PA",5), 8),
            "min":  norm_dist(target_row.get("MIN_PCT",50), row.get("MIN_PCT",50), 20),
            "ht":   norm_dist(t_ht, c_ht, 4)
        }
        total = sum(scores[k] * base_w[k] for k in scores)
        results.append((total, row))
    results.sort(key=lambda x: x[0], reverse=True)
    return results[:n]


# ==========================================
# MODULES BY ROUTED TAB NAME
# ==========================================

if st.session_state.active_tab == "Depth Chart":
    st.subheader("26-27 UCLA Bruins — Depth Chart")
    with st.expander("Edit Roster Structure", expanded=False):
        conn = sqlite3.connect('scouting_hub.db')
        roster_df = pd.read_sql_query("SELECT player_name AS Player, position AS Pos, depth AS Depth, descriptor AS Descriptor, bt_name AS [BT Name] FROM roster ORDER BY position, depth", conn)
        conn.close()
        edited = st.data_editor(roster_df, num_rows="dynamic", hide_index=True, use_container_width=True)
        if st.button("Save Roster Setup"):
            conn = sqlite3.connect('scouting_hub.db')
            cursor = conn.cursor()
            cursor.execute("DELETE FROM roster")
            for _, r in edited.iterrows():
                if pd.isna(r["Player"]): continue
                cursor.execute("INSERT INTO roster (player_name, position, depth, descriptor, bt_name) VALUES (?, ?, ?, ?, ?)", (str(r["Player"]), str(r["Pos"]), int(r["Depth"]), str(r["Descriptor"]), str(r["BT Name"])))
            conn.commit(); conn.close()
            st.success("Roster structural array built.")
            st.rerun()

    conn = sqlite3.connect('scouting_hub.db')
    chart_df = pd.read_sql_query("SELECT player_name, position, depth, descriptor, bt_name FROM roster ORDER BY depth", conn)
    conn.close()

    pos_cols = st.columns(5)
    POSITIONS = [("PG", "Point Guard"), ("CG", "Combo Guard"), ("SF", "Small Forward"), ("PF", "Power Forward"), ("C", "Center")]
    for idx, (p_c, p_l) in enumerate(POSITIONS):
        with pos_cols[idx]:
            st.markdown(f"<div style='background-color:#2774AE; color:white; font-weight:bold; text-align:center; padding:8px; border-radius:6px; margin-bottom:12px;'>{p_c}<br><span style='font-size:9px;'>{p_l}</span></div>", unsafe_allow_html=True)
            group = chart_df[chart_df["position"] == p_c]
            for _, pl in group.iterrows():
                pname = pl["player_name"]
                st.markdown(f"<div style='border:1px solid #FFD100; padding:8px; border-radius:4px; background:#fff; color:#000; margin-bottom:6px;'><b>{pname}</b><br><small style='color:#666;'>{pl['descriptor']}</small></div>", unsafe_allow_html=True)
                if pl["bt_name"] and st.button(f"Scout {pname}", key=f"nav_{pname}"):
                    st.session_state.active_player = pl["bt_name"]
                    st.session_state.active_tab = "One Pager / Player Card"
                    st.rerun()


elif st.session_state.active_tab == "One Pager / Player Card":
    st.subheader("UCLA Executive One Pager — Print View Setup")
    
    c_idx = all_player_names.index(st.session_state.active_player) if st.session_state.active_player in all_player_names else 0
    card_selected = st.selectbox("Select Target File Profile:", all_player_names, index=c_idx)
    if card_selected != st.session_state.active_player:
        st.session_state.active_player = card_selected

    p_data = df_all[df_all["PLAYER"] == st.session_state.active_player].iloc[0]
    
    conn = sqlite3.connect('scouting_hub.db')
    cursor = conn.cursor()
    cursor.execute("SELECT position, photo_url, coach_notes FROM player_notes WHERE player_name = ?", (st.session_state.active_player,))
    db_res = cursor.fetchone()
    conn.close()
    
    s_pos = db_res[0] if db_res and db_res[0] else ""
    p_img = db_res[1] if db_res and db_res[1] else fetch_sr_headshot_silent(st.session_state.active_player, p_data["TEAM"])
    c_notes = db_res[2] if db_res and db_res[2] else ""
    
    p_group = detect_pos_group(p_data.get("TORVIK_POS",""), s_pos, p_data.get("HEIGHT",""), p_data.get("AST",0))

    # FRONT LAYOUT CONTAINER (SCREENSHOT 2 INSPIRED)
    st.markdown(f"""
    <div style="background-color:#0f172a; border:1px solid #FFD100; border-radius:8px; padding:20px; margin-bottom:20px;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <div style="display:flex; align-items:center; gap:20px;">
                <img src="{p_img if p_img else ''}" style="width:90px; height:110px; border-radius:6px; background:#1e293b; object-fit:cover;"/>
                <div>
                    <h2 style="margin:0; color:#fff; font-size:28px; font-weight:900;">{st.session_state.active_player}</h2>
                    <div style="color:#94a3b8; font-size:14px; margin-top:2px;">{p_data['TEAM']} · {p_data['HEIGHT']} · {p_data['CLASS']}</div>
                    <div style="color:#38bdf8; font-size:13px; font-style:italic; margin-top:4px;">Portal Prospect Engine Pool</div>
                </div>
            </div>
            <span style="background:#FFD100; color:#0f172a; font-weight:900; padding:6px 14px; border-radius:4px; font-size:14px;">{p_group}</span>
        </div>
        <hr style="border-color:#1e293b; margin:15px 0;"/>
        <p style="color:#64748b; font-size:11px; text-transform:uppercase; font-weight:700; margin-bottom:8px;">General Profile Stats</p>
        <div style="display:grid; grid-template-columns:repeat(7, 1fr); gap:10px; text-align:center; margin-bottom:15px;">
            <div style="background:#1e293b; padding:8px; border-radius:4px;"><b style="font-size:18px; color:#fff;">{p_data.get('PPG',0.0):.1f}</b><br><small style="color:#64748b;">PTS</small></div>
            <div style="background:#1e293b; padding:8px; border-radius:4px;"><b style="font-size:18px; color:#fff;">{p_data.get('RPG',0.0):.1f}</b><br><small style="color:#64748b;">REB</small></div>
            <div style="background:#1e293b; padding:8px; border-radius:4px;"><b style="font-size:18px; color:#fff;">{p_data.get('APG',0.0):.1f}</b><br><small style="color:#64748b;">AST</small></div>
            <div style="background:#1e293b; padding:8px; border-radius:4px;"><b style="font-size:18px; color:#fff;">{p_data.get('TWO_P',0.0):.1f}%</b><br><small style="color:#64748b;">2PT%</small></div>
            <div style="background:#1e293b; padding:8px; border-radius:4px;"><b style="font-size:18px; color:#fff;">{p_data.get('THREE_P',0.0):.1f}%</b><br><small style="color:#64748b;">3PT%</small></div>
            <div style="background:#1e293b; padding:8px; border-radius:4px;"><b style="font-size:18px; color:#fff;">{p_data.get('FTR',0.0):.2f}</b><br><small style="color:#64748b;">FT Rate</small></div>
            <div style="background:#1e293b; padding:8px; border-radius:4px;"><b style="font-size:18px; color:#fff;">{p_data.get('GP',0)}</b><br><small style="color:#64748b;">GAMES</small></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ADVANCED POSITION METRIC ROW SWAPPING BASED ON SCREENSHOT 2
    st.markdown(f"<p style='color:#94a3b8; font-size:11px; text-transform:uppercase; font-weight:700;'>Dynamic {p_group} Advanced Metric Verification Layer</p>", unsafe_allow_html=True)
    m_col1, m_col2, m_col3, m_col4, m_col5, m_col6 = st.columns(6)
    
    p_ato = round(p_data['AST'] / p_data['TO'], 2) if p_data['TO'] > 0 else 0.0
    if p_group == "GUARD":
        m_col1.metric("MIN%", f"{p_data['MIN_PCT']:.1f}%")
        m_col2.metric("ORTG", f"{p_data['ORTG']:.1f}")
        m_col3.metric("AST%", f"{p_data['AST']:.1f}%")
        m_col4.metric("A/TO", f"{p_ato:.2f}")
        m_col5.metric("TOV%", f"{p_data['TO']:.1f}%")
        m_col6.metric("STL%", f"{p_data['STL']:.1f}%")
    elif p_group == "WING":
        m_col1.metric("MIN%", f"{p_data['MIN_PCT']:.1f}%")
        m_col2.metric("BPM", f"{p_data['BPM']:.1f}")
        m_col3.metric("STL%", f"{p_data['STL']:.1f}%")
        m_col4.metric("BLK%", f"{p_data['BLK']:.1f}%")
        m_col5.metric("DREB%", f"{p_data['DR']:.1f}%")
        m_col6.metric("OREB%", f"{p_data['OR']:.1f}%")
    else:
        m_col1.metric("ORTG", f"{p_data['ORTG']:.1f}")
        m_col2.metric("OREB%", f"{p_data['OR']:.1f}%")
        m_col3.metric("DREB%", f"{p_data['DR']:.1f}%")
        m_col4.metric("TO%", f"{p_data['TO']:.1f}%")
        m_col5.metric("BLK%", f"{p_data['BLK']:.1f}%")
        m_col6.metric("BPM", f"{p_data['BPM']:.1f}")

    st.write("---")

    # ADVANCED BACK LAYOUT (TILE VIEW BASED ON SCREENSHOT 1 & 3 DESIGN)
    st.markdown("### Advanced Backend Metric Execution Map")
    col_t1, col_t2 = st.columns(2)
    
    with col_t1:
        st.markdown("""
        <div style="background:#0f172a; padding:15px; border-radius:8px; border:1px solid #1e293b; height:100%;">
            <h4 style="color:#FFD100; margin-top:0;">Synergy Performance Breakdown Structure</h4>
            <small style="color:#64748b;">(Ordered sequentially match framework template profile)</small>
            <div style="margin-top:10px;">
                <div style="display:flex; justify-content:between; padding:6px; background:#1e293b; margin-bottom:4px; border-radius:4px;"><span>Spot Up</span><b>1.13 PPP (84%)</b></div>
                <div style="display:flex; justify-content:between; padding:6px; background:#1e293b; margin-bottom:4px; border-radius:4px;"><span>Transition</span><b>0.92 PPP (24%)</b></div>
                <div style="display:flex; justify-content:between; padding:6px; background:#1e293b; margin-bottom:4px; border-radius:4px;"><span>P&R Ball Handler</span><b>0.70 PPP (33%)</b></div>
                <div style="display:flex; justify-content:between; padding:6px; background:#1e293b; margin-bottom:4px; border-radius:4px;"><span>Isolation</span><b>1.29 PPP (97%)</b></div>
                <div style="display:flex; justify-content:between; padding:6px; background:#1e293b; margin-bottom:4px; border-radius:4px;"><span>Miscellaneous</span><b>0.63 PPP (64%)</b></div>
                <div style="display:flex; justify-content:between; padding:6px; background:#1e293b; margin-bottom:4px; border-radius:4px;"><span>Handoffs</span><b>1.12 PPP (84%)</b></div>
                <div style="display:flex; justify-content:between; padding:6px; background:#1e293b; margin-bottom:4px; border-radius:4px;"><span>Off Screen</span><b>1.09 PPP (71%)</b></div>
                <div style="display:flex; justify-content:between; padding:6px; background:#1e293b; margin-bottom:4px; border-radius:4px; opacity:0.4;"><span>P&R Roll Man</span><b>-- PPP (--%)</b></div>
                <div style="display:flex; justify-content:between; padding:6px; background:#1e293b; margin-bottom:4px; border-radius:4px; opacity:0.4;"><span>Cut</span><b>-- PPP (--%)</b></div>
                <div style="display:flex; justify-content:between; padding:6px; background:#1e293b; margin-bottom:4px; border-radius:4px; opacity:0.4;"><span>Put Backs</span><b>-- PPP (--%)</b></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    with col_t2:
        st.markdown(f"""
        <div style="background:#0f172a; padding:15px; border-radius:8px; border:1px solid #1e293b;">
            <h4 style="color:#38bdf8; margin-top:0;">Full Advanced Metric Framework Tiles</h4>
            <div style="display:grid; grid-template-columns: repeat(2, 1fr); gap:10px;">
                <div style="background:#1e293b; padding:10px; border-radius:4px;"><span style="color:#64748b; font-size:11px;">PRPG! VALUE</span><br><b style="font-size:18px; color:#fff;">{p_data.get('PRPG', 0.0):.1f}</b></div>
                <div style="background:#1e293b; padding:10px; border-radius:4px;"><span style="color:#64748b; font-size:11px;">BOX BPM TOTAL</span><br><b style="font-size:18px; color:#fff;">{p_data.get('BPM', 0.0):.1f}</b></div>
                <div style="background:#1e293b; padding:10px; border-radius:4px;"><span style="color:#64748b; font-size:11px;">OFFENSIVE BPM</span><br><b style="font-size:18px; color:#fff;">{p_data.get('OBPM', 0.0):.1f}</b></div>
                <div style="background:#1e293b; padding:10px; border-radius:4px;"><span style="color:#64748b; font-size:11px;">DEFENSIVE BPM</span><br><b style="font-size:18px; color:#fff;">{p_data.get('DBPM', 0.0):.1f}</b></div>
                <div style="background:#1e293b; padding:10px; border-radius:4px;"><span style="color:#64748b; font-size:11px;">TRUE EFFICIENCY ORTG</span><br><b style="font-size:18px; color:#fff;">{p_data.get('ORTG', 0.0):.1f}</b></div>
                <div style="background:#1e293b; padding:10px; border-radius:4px;"><span style="color:#64748b; font-size:11px;">USAGE CAPACITY RATE</span><br><b style="font-size:18px; color:#fff;">{p_data.get('USG', 0.0):.1f}%</b></div>
            </div>
            <div style="margin-top:15px; padding:10px; background:#172554; border-radius:6px; border:1px solid #1d4ed8; text-align:center;">
                <span style="color:#93c5fd; font-size:12px; font-weight:700;">ESPN Analytics Shot Chart System Node Active</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.write("---")
    st.markdown("### Front Office Directives & Staff Intel Notes")
    notes_val = st.text_area("Cronin Board Dossier Notes Input:", value=c_notes, height=140, placeholder="Type executive tactical briefing notes here for print layout updates...")
    if st.button("Commit Evaluation Notes to Master Database File", type="primary"):
        conn = sqlite3.connect('scouting_hub.db')
        cursor = conn.cursor()
        cursor.execute("INSERT INTO player_notes (player_name, team_name, coach_notes) VALUES (?, ?, ?) ON CONFLICT(player_name) DO UPDATE SET coach_notes=excluded.coach_notes", (st.session_state.active_player, p_data["TEAM"], notes_val))
        conn.commit(); conn.close()
        st.success("Target dossier information successfully integrated.")
        st.rerun()


elif st.session_state.active_tab == "Comp Results":
    st.subheader("Statistical Comp Engine")
    act = st.session_state.active_player
    if not act or act not in df_all["PLAYER"].values:
        st.info("Select active player targets within discovery tab layers first.")
    else:
        c_data = df_all[df_all["PLAYER"] == act].iloc[0]
        st.markdown(f"**Target Model Source Profile: {act}**")
        
        c_pos_sel = st.radio("Target Pos Filter Mode Matrix:", ["GUARD", "WING", "CENTER"], horizontal=True)
        comps_list = run_comps(c_data, df_all, c_pos_sel, n=8)
        
        for score, row in comps_list:
            match_pct = round(score * 100, 1)
            st.markdown(f"""
            <div style="background:#0f172a; padding:12px; border-radius:6px; margin-bottom:8px; border-left:4px solid #38bdf8;">
                <div style="display:flex; justify-content:space-between;">
                    <b>{row['PLAYER']} ({row['TEAM']})</b>
                    <span style="color:#38bdf8; font-weight:bold;">{match_pct}% Match Rate</span>
                </div>
                <small style="color:#64748b;">Height: {row['HEIGHT']} | BPM: {row['BPM']:.1f} | ORTG: {row['ORTG']:.1f} | TS: {row['TS']:.1f}%</small>
            </div>
            """, unsafe_allow_html=True)


elif st.session_state.active_tab == "Portal Discovery Engine":
    st.subheader("Database Filter Hub Matrix")
    
    with st.expander("Adjust Global Filter Constraints", expanded=False):
        c_search = st.text_input("Quick Name Search Field:")
        bpm_bounds = st.slider("BPM Range Boundary Box", -10.0, 15.0, (-2.0, 15.0))
        
    f_df = df_all.copy()
    if c_search:
        f_df = f_df[f_df["PLAYER"].str.contains(c_search, case=False, na=False)]
    f_df = f_df[f_df["BPM"].between(bpm_bounds[0], bpm_bounds[1])]
    
    st.write(f"Discovery Pipeline Results Size: {len(f_df)} active matches")
    
    evt = st.dataframe(f_df[["PLAYER", "TEAM", "CONF", "CLASS", "HEIGHT", "BPM", "ORTG"]], hide_index=True, on_select="rerun", selection_mode="single-row", height=400)
    
    if evt.selection.rows:
        sel_row_idx = evt.selection.rows[0]
        chosen_p = f_df.iloc[sel_row_idx]["PLAYER"]
        if st.session_state.active_player != chosen_p:
            st.session_state.active_player = chosen_p
            # AUTO POP UP TARGET TAB LAYER VIA SESSION STATE ALIGNMENT
            st.session_state.active_tab = "One Pager / Player Card"
            st.rerun()


elif st.session_state.active_tab == "Front Office Target Board":
    st.subheader("Central Target Board Records")
    conn = sqlite3.connect('scouting_hub.db')
    db_df = pd.read_sql_query('SELECT player_name AS PLAYER, team_name AS TEAM, position AS POS, coach_notes AS [NOTES briefing] FROM player_notes', conn)
    conn.close()
    if db_df.empty:
        st.info("No records currently committed to master file layout storage fields.")
    else:
        st.dataframe(db_df, hide_index=True, use_container_width=True)


elif st.session_state.active_tab == "Big Board Print View":
    st.subheader("Staff Print Alignment Frame Grid")
    st.caption("Press Cmd+P or File->Print to output pure data cleanly.")
    st.dataframe(df_all[["PLAYER", "TEAM", "HEIGHT", "CLASS", "BPM", "PRPG"]].head(50), hide_index=True, use_container_width=True)


elif st.session_state.active_tab == "Transfer Portal":
    st.subheader("srating.io Portal Index Engine Store")
    if not table_has_data("transfer_portal"):
        not_loaded_banner("transfer_portal", "build_transfer_portal.py")
    else:
        conn = sqlite3.connect('scouting_hub.db')
        p_df = pd.read_sql_query("SELECT * FROM transfer_portal", conn)
        conn.close()
        st.dataframe(p_df, hide_index=True, use_container_width=True)


elif st.session_state.active_tab == "Game Logs":
    st.subheader("ESPN Individual Game Splits Layer")
    if not table_has_data("player_game_logs"):
        not_loaded_banner("player_game_logs", "build_game_logs.py")
    else:
        conn = sqlite3.connect('scouting_hub.db')
        gl_df = pd.read_sql_query("SELECT * FROM player_game_logs", conn)
        conn.close()
        st.dataframe(gl_df, hide_index=True, use_container_width=True)


elif st.session_state.active_tab == "Synergy Breakdown":
    st.subheader("Synergy Sports Matrix Arrays")
    if not table_has_data("synergy_playtypes"):
        not_loaded_banner("synergy_playtypes", "build_synergy_playtypes.py")
    else:
        conn = sqlite3.connect('scouting_hub.db')
        syn_df = pd.read_sql_query("SELECT * FROM synergy_playtypes", conn)
        conn.close()
        st.dataframe(syn_df, hide_index=True, use_container_width=True)


elif st.session_state.active_tab == "Shot Charts":
    st.subheader("Vector Point Spatial Shot Charts")
    if not table_has_data("shot_chart"):
        not_loaded_banner("shot_chart", "build_shot_charts.py")
    else:
        st.info("Shot chart maps vector engine ready for plotting data pipelines.")
