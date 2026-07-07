import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np

# -----------------------------------------------------------------------------
# 1. PAGE CONFIG & STYLING
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="UCLA Basketball Scouting Hub",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Dark theme matching your Streamlit UI
st.markdown("""
    <style>
    .reportview-container { background: #0e1117; }
    div.stButton > button:first-child {
        background-color: #1b3a5c;
        color: white;
    }
    .stSlider { padding-bottom: 20px; }
    </style>
""", unsafe_allowed_html=True)

# -----------------------------------------------------------------------------
# 2. MOCK DATA GENERATION (Replace with your live scraped KenPom/Torvik CSV/DB)
# -----------------------------------------------------------------------------
@st.cache_data
def load_scouting_data():
    # Creating a sample dataset matching your 2612 active matches structure
    names = ["Azavier 'Stink' Robinson", "Elijah Elliott", "Doctor Bradley", "Addison Patterson", "Rienk Mast", "Rick Issanza", "Steele Venters", "Rashaun Agee"]
    teams = ["Butler", "New Mexico St.", "Bethune Cookman", "Eastern Michigan", "Nebraska", "Loyola Marymount", "Gonzaga", "Texas A&M"]
    confs = ["Big East", "CUSA", "SWAC", "MAC", "B10", "WCC", "WCC", "SEC"]
    classes = ["Fr", "Sr", "Sr", "Sr", "Sr", "Sr", "Sr", "Sr"]
    
    data = []
    for i in range(100): # Expanding out to simulate your full database matrix
        idx = i % len(names)
        p_name = names[idx] if i < len(names) else f"Prospect {i}"
        team = teams[idx] if i < len(names) else f"Team {i}"
        conf = confs[idx] if i < len(names) else "Other"
        cls = classes[idx] if i < len(names) else "Jr"
        
        # Simulating realistic advanced metrics
        bpm = float(np.random.uniform(-2.0, 15.0)) if i >= len(names) else [8.3, -0.97, 5.48, 1.91, 5.41, 2.51, 3.56, 8.55][idx]
        ortg = float(np.random.uniform(90.0, 130.0)) if i >= len(names) else [123.1, 101.6, 103.4, 109.6, 112.5, 104.9, 112.9, 111.2][idx]
        
        data.append({
            "PLAYER": p_name, "TEAM": team, "CONF": conf, "CLASS": cls, "HEIGHT": "6-2" if idx==0 else "6-7",
            "BPM": bpm, "ORTG": ortg, "PRPG": 5.9 if idx==0 else 2.1, "OBPM": 6.7 if idx==0 else 1.2, "DBPM": 1.6 if idx==0 else -0.4,
            "USG": 25.2 if idx==0 else 22.0, "EFG": 53.3, "TS": 53.4, "TWO_PCT": 40.6, "THREE_PCT": 43.3, "FTR": 0.28,
            "THREE_100": 12.1, "AST_PCT": 20.2, "TO_PCT": 14.0, "ATO": 1.4, "MIN_PCT": 92.7, "OR_PCT": 0.7, "DR_PCT": 8.7, 
            "BLK_PCT": 0.4, "STL_PCT": 2.2, "PPG": 6.1, "RPG": 1.9, "SPG": 1.5, "GP_GS": "22-15", "MIN": 18.3, "FGM_A": "47-100"
        })
    return pd.DataFrame(data)

df = load_scouting_data()

# -----------------------------------------------------------------------------
# 3. SIDEBAR NAVIGATION
# -----------------------------------------------------------------------------
st.sidebar.title("🏀 UCLA Hoops Board")
app_mode = st.sidebar.radio("Navigate Workspace", ["Portal Discovery Engine", "Roster Depth Manager"])

# -----------------------------------------------------------------------------
# 4. PORTAL DISCOVERY ENGINE TAB
# -----------------------------------------------------------------------------
if app_mode == "Portal Discovery Engine":
    st.title("Database Filter Hub Matrix")
    
    with st.expander("▼ Adjust Global Filter Constraints", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            search_query = st.text_input("Quick Name Search Field:")
        with col2:
            bpm_range = st.slider("BPM Range Boundary Box", -2.00, 15.00, (-2.00, 15.00))
            
    # Filter Pipeline Execution
    filtered_df = df[(df['BPM'] >= bpm_range[0]) & (df['BPM'] <= bpm_range[1])]
    if search_query:
        filtered_df = filtered_df[filtered_df['PLAYER'].str.contains(search_query, case=False)]
        
    st.markdown(f"**Discovery Pipeline Results Size:** {len(filtered_df)} active matches")
    
    # Render Interactive Matrix Table with Selection Feature
    # Using dynamic radio selection to cleanly tie the Matrix to the Player Cards
    selected_player = st.selectbox("Select a Prospect Matrix Node to Execute One-Pager Card Generator:", 
                                   options=filtered_df['PLAYER'].unique())
    
    # Display the Main Dashboard Grid Matrix View
    st.dataframe(filtered_df[['PLAYER', 'TEAM', 'CONF', 'CLASS', 'HEIGHT', 'BPM', 'ORTG']], use_container_width=True, hide_index=True)
    
    st.markdown("---")
    
    # -------------------------------------------------------------------------
    # 5. DYNAMIC TARGET PLAYER CARD COMPONENT GENERATOR
    # -------------------------------------------------------------------------
    if selected_player:
        p_data = df[df['PLAYER'] == selected_player].iloc[0]
        st.subheader(f"Target Scouting Analytics Framework: {selected_player}")
        
        # Split layout: Left is the Traditional One-Pager Card, Right is the Custom 5-Category Advanced Torvik Tiles
        card_col, tile_col = st.columns([1.1, 0.9])
        
        with card_col:
            st.markdown("### 📋 Executive One-Pager Print Framework")
            
            # Injecting your custom structural HTML/CSS directly into Streamlit
            html_one_pager = f"""
            <div style="background: #ffffff; padding: 20px; border-radius: 6px; font-family: 'Spectral', Georgia, serif; color: #1b3a5c; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                <div style="background: #3a6ea8; color: white; padding: 15px; border-radius: 4px; border-bottom: 3px solid #1b3a5c; display: flex; justify-content: space-between;">
                    <div>
                        <h1 style="margin:0; font-size: 28px; font-weight:600;">{p_data['PLAYER']}</h1>
                        <p style="margin: 5px 0 0 0; font-size:14px; font-weight:700;">
                            Current Team: {p_data['TEAM']} | HT: {p_data['HEIGHT']} | Class: {p_data['CLASS']}<br>
                            PPG: {p_data['PPG']} &nbsp;•&nbsp; RPG: {p_data['RPG']} &nbsp;•&nbsp; SPG: {p_data['SPG']}
                        </p>
                    </div>
                    <div style="width: 70px; height: 70px; background: #dce6f2; border-radius: 4px; display:flex; align-items:center; justify-content:center; font-size:10px; color:#4a6a94; font-family:sans-serif;">HEADSHOT</div>
                </div>
                
                <h3 style="margin-top: 15px; border-bottom: 2px solid #1b3a5c; padding-bottom:3px; font-size:18px;">TRADITIONAL STATSPLITS</h3>
                <table style="width:100%; border-collapse:collapse; font-family:sans-serif; font-size:12px; text-align:right; margin-top:5px;">
                    <tr style="border-bottom: 1px solid #b9c4cf; font-weight:700; color:#33475c;">
                        <th style="text-align:left;">Split</th><th>GP-GS</th><th>PTS</th><th>MIN</th><th>FGM-A</th><th>3P%</th>
                    </tr>
                    <tr style="border-bottom: 1px solid #dfe5ea; color:#22384e;">
                        <td style="text-align:left; font-weight:700;">All Splits</td><td>{p_data['GP_GS']}</td><td>{p_data['PPG']}</td><td>{p_data['MIN']}</td><td>{p_data['FGM_A']}</td><td>{p_data['THREE_PCT']}%</td>
                    </tr>
                </table>
                
                <h3 style="margin-top: 15px; border-bottom: 2px solid #1b3a5c; padding-bottom:3px; font-size:18px;">STAFF EVALUATION & NOTES</h3>
                <div style="font-family: sans-serif; font-size: 13px; color: #555; background: #f9f9f9; padding: 10px; border-radius: 4px; border-left: 3px solid #3a6ea8; margin-top:5px; min-height: 80px;">
                    • Projecting role fitment inside current halfcourt secondary actions...<br>
                    • Defensive engagement rates map cleanly to baseline parameters.
                </div>
            </div>
            """
            components.html(html_one_pager, height=390, scrolling=True)
            
        with tile_col:
            st.markdown("### 📊 Live Torvik Advanced Execution Layer")
            
            # Injecting your raw Claude HTML UI layout directly into the application instance
            html_advanced_tiles = f"""
            <div style="background-color: #161a23; padding: 20px; border-radius: 10px; font-family: sans-serif; color: #ffffff;">
                <h4 style="color: #e5ad35; margin-top:0; letter-spacing:1px; font-size:14px;">FULL TORVIK STATS <span style="font-size:10px; opacity:0.6; float:right;">LIVE FROM CBBDATA</span></h4>
                
                <!-- IMPACT ROW -->
                <p style="font-size:11px; color:#8a909d; margin: 10px 0 4px 0; text-transform:uppercase;">Impact</p>
                <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px;">
                    <div style="background:#2b2a1a; border: 1px solid #e5ad35; padding: 8px; border-radius:6px; text-align:center;">
                        <span style="font-size:9px; color:#e5ad35; display:block;">PRPG!</span><b style="font-size:16px;">{p_data['PRPG']}</b>
                    </div>
                    <div style="background:#2b2a1a; border: 1px solid #e5ad35; padding: 8px; border-radius:6px; text-align:center;">
                        <span style="font-size:9px; color:#e5ad35; display:block;">BPM</span><b style="font-size:16px;">{p_data['BPM']:.1f}</b>
                    </div>
                    <div style="background:#2b2a1a; border: 1px solid #e5ad35; padding: 8px; border-radius:6px; text-align:center;">
                        <span style="font-size:9px; color:#e5ad35; display:block;">OBPM</span><b style="font-size:16px;">{p_data['OBPM']}</b>
                    </div>
                    <div style="background:#242933; padding: 8px; border-radius:6px; text-align:center;">
                        <span style="font-size:9px; color:#8a909d; display:block;">DBPM</span><b style="font-size:16px;">{p_data['DBPM']}</b>
                    </div>
                </div>

                <!-- EFFICIENCY ROW -->
                <p style="font-size:11px; color:#8a909d; margin: 10px 0 4px 0; text-transform:uppercase;">Efficiency</p>
                <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px;">
                    <div style="background:#2b2a1a; border: 1px solid #e5ad35; padding: 8px; border-radius:6px; text-align:center;">
                        <span style="font-size:9px; color:#e5ad35; display:block;">ORTG</span><b style="font-size:16px;">{p_data['ORTG']:.1f}</b>
                    </div>
                    <div style="background:#242933; padding: 8px; border-radius:6px; text-align:center;">
                        <span style="font-size:9px; color:#8a909d; display:block;">USG%</span><b style="font-size:16px;">{p_data['USG']}%</b>
                    </div>
                    <div style="background:#242933; padding: 8px; border-radius:6px; text-align:center;">
                        <span style="font-size:9px; color:#8a909d; display:block;">EFG%</span><b style="font-size:16px;">{p_data['EFG']}%</b>
                    </div>
                    <div style="background:#242933; padding: 8px; border-radius:6px; text-align:center;">
                        <span style="font-size:9px; color:#8a909d; display:block;">TS%</span><b style="font-size:16px;">{p_data['TS']}%</b>
                    </div>
                </div>

                <!-- PLAYMAKING ROW -->
                <p style="font-size:11px; color:#8a909d; margin: 10px 0 4px 0; text-transform:uppercase;">Playmaking</p>
                <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px;">
                    <div style="background:#242933; padding: 8px; border-radius:6px; text-align:center;">
                        <span style="font-size:9px; color:#8a909d; display:block;">AST%</span><b style="font-size:16px;">{p_data['AST_PCT']}%</b>
                    </div>
                    <div style="background:#242933; padding: 8px; border-radius:6px; text-align:center;">
                        <span style="font-size:9px; color:#8a909d; display:block;">TO%</span><b style="font-size:16px;">{p_data['TO_PCT']}</b>
                    </div>
                    <div style="background:#242933; padding: 8px; border-radius:6px; text-align:center;">
                        <span style="font-size:9px; color:#8a909d; display:block;">A/TO</span><b style="font-size:16px;">{p_data['ATO']}</b>
                    </div>
                    <div style="background:#2b2a1a; border: 1px solid #e5ad35; padding: 8px; border-radius:6px; text-align:center;">
                        <span style="font-size:9px; color:#e5ad35; display:block;">MIN%</span><b style="font-size:16px;">{p_data['MIN_PCT']}%</b>
                    </div>
                </div>
            </div>
            """
            components.html(html_advanced_tiles, height=390, scrolling=True)

# -----------------------------------------------------------------------------
# 6. EMPTY ALTERNATE WORKSPACE VIEW
# -----------------------------------------------------------------------------
else:
    st.title("Roster Depth Manager Layout Workspace")
    st.info("Alternate analytical profile systems live inside this node framework.")
