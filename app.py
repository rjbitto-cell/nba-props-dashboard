import streamlit as st
import pandas as pd
import numpy as np
from scipy.stats import norm
from nba_api.stats.endpoints import playergamelog
from nba_api.stats.static import players

st.set_page_config(page_title="NBA Sharp Props Tool", layout="wide")
st.title("🏀 NBA Sharp Props Tool")

# -------------------------
# SETTINGS
# -------------------------
SEASON = "2025-26"
IMPLIED_PROB = 0.524

# -------------------------
# HELPERS
# -------------------------
def get_player_id(name):
    p = players.find_players_by_full_name(name)
    return p[0]['id'] if p else None

@st.cache_data(ttl=3600)
def get_active_players():
    return players.get_active_players()

@st.cache_data(ttl=600)
def get_logs(player_id):
    df = playergamelog.PlayerGameLog(player_id=player_id, season=SEASON).get_data_frames()[0]
    return df

def calculate_projection(logs):
    if len(logs) < 5:
        return None

    last5 = logs.head(5)
    last10 = logs.head(10)

    # Base stats
    pts = 0.4*last5['PTS'].mean() + 0.4*last10['PTS'].mean() + 0.2*logs['PTS'].mean()
    reb = 0.4*last5['REB'].mean() + 0.4*last10['REB'].mean() + 0.2*logs['REB'].mean()
    ast = 0.4*last5['AST'].mean() + 0.4*last10['AST'].mean() + 0.2*logs['AST'].mean()

    # Minutes trend (usage proxy)
    minutes_avg = logs['MIN'].mean()
    minutes_recent = last5['MIN'].mean()
    trend = minutes_recent / max(minutes_avg, 1)

    pts *= trend
    reb *= trend
    ast *= trend

    # Std dev for probability calc
    std_pts = max(last10['PTS'].std(), 1)
    std_reb = max(last10['REB'].std(), 1)
    std_ast = max(last10['AST'].std(), 1)

    return {
        "PTS": (pts, std_pts),
        "REB": (reb, std_reb),
        "AST": (ast, std_ast)
    }

# -------------------------
# LOAD PLAYERS
# -------------------------
players_list = get_active_players()

# Limit for performance (you can increase later)
players_list = players_list[:50]

rows = []

st.subheader("📊 Generating projections...")

for p in players_list:
    try:
        name = p['full_name']
        pid = p['id']

        logs = get_logs(pid)

        proj = calculate_projection(logs)
        if not proj:
            continue

        for stat in ["PTS", "REB", "AST"]:
            projection, std = proj[stat]

            rows.append({
                "player": name,
                "stat": stat,
                "projection": round(projection, 2),
                "std": std
            })

    except:
        continue

df = pd.DataFrame(rows)

# -------------------------
# USER INPUT (SPORTSBOOK LINES)
# -------------------------
st.subheader("✍️ Enter Sportsbook Lines")

input_df = df.copy()
input_df["line"] = ""

input_df = st.data_editor(input_df, use_container_width=True)

# -------------------------
# EDGE CALCULATION
# -------------------------
def calculate_edge(row):
    try:
        if row["line"] == "" or pd.isna(row["line"]):
            return None

        line = float(row["line"])
        projection = row["projection"]
        std = row["std"]

        prob = 1 - norm.cdf(line, projection, std)
        edge = prob - IMPLIED_PROB

        return edge
    except:
        return None

input_df["edge"] = input_df.apply(calculate_edge, axis=1)

# -------------------------
# FILTER + DISPLAY
# -------------------------
st.subheader("🔥 Best Value Bets")

filtered = input_df.dropna(subset=["edge"])
filtered = filtered.sort_values(by="edge", ascending=False)

st.dataframe(filtered.head(25), use_container_width=True)

# -------------------------
# PLAYER VIEW
# -------------------------
st.subheader("🔍 Player Detail")

player = st.selectbox("Select Player", filtered["player"].unique() if not filtered.empty else [])

if player:
    row = filtered[filtered["player"] == player].iloc[0]

    st.metric("Projection", row["projection"])
    st.metric("Line", row["line"])
    st.metric("Edge", f"{round(row['edge']*100,2)}%")
