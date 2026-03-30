import streamlit as st
import pandas as pd
import numpy as np
import requests
from scipy.stats import norm

st.set_page_config(page_title="NBA Props Dashboard", layout="wide")
st.title("🏀 NBA Props Dashboard (PrizePicks)")

# -------------------------
# LOAD STATIC DATA
# -------------------------
@st.cache_data
def load_player_data():
    return pd.read_csv("data/player_stats.csv")

@st.cache_data
def load_defense_data():
    return pd.read_csv("data/team_defense.csv")

@st.cache_data
def load_matchups():
    return pd.read_csv("data/matchups.csv")

player_data = load_player_data()
defense_data = load_defense_data()
matchups = load_matchups()

# -------------------------
# LOAD PRIZEPICKS (FIXED)
# -------------------------
@st.cache_data(ttl=300)
def load_props():
    try:
        url = "https://api.prizepicks.com/projections"

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json"
        }

        res = requests.get(url, headers=headers, timeout=10)

        if res.status_code != 200:
            st.warning(f"PrizePicks failed: {res.status_code}")
            return fallback_data()

        res = res.json()

        data = res.get("data", [])
        included = res.get("included", [])

        players = {
            p["id"]: p.get("attributes", {}).get("name")
            for p in included if p.get("type") == "new_player"
        }

        rows = []

        for item in data:
            try:
                attr = item.get("attributes", {})
                rel = item.get("relationships", {})
                player_id = rel.get("new_player", {}).get("data", {}).get("id")

                name = players.get(player_id)
                stat = attr.get("stat_type")
                line = attr.get("line_score")

                if not name or line is None:
                    continue

                if stat not in ["Points", "Rebounds", "Assists"]:
                    continue

                rows.append({
                    "player": name,
                    "stat": stat,
                    "line": float(line),
                    "odds": -110
                })

            except:
                continue

        df = pd.DataFrame(rows)

        if df.empty:
            st.warning("No PrizePicks props returned")
            return fallback_data()

        return df

    except Exception as e:
        st.error("PrizePicks API failed — using fallback")
        return fallback_data()

# -------------------------
# FALLBACK DATA (NEVER BREAKS)
# -------------------------
def fallback_data():
    return pd.DataFrame({
        "player": ["LeBron James", "Stephen Curry", "Nikola Jokic"],
        "stat": ["Points", "Points", "Rebounds"],
        "line": [27.5, 29.5, 11.5],
        "odds": [-110, -110, -110]
    })

df = load_props()

# -------------------------
# NAME CLEANING
# -------------------------
def normalize_name(name):
    return str(name).lower().replace(".", "").strip()

player_data["clean_name"] = player_data["player"].apply(normalize_name)
df["clean_name"] = df["player"].apply(normalize_name)

# -------------------------
# EDGE MODEL
# -------------------------
def calculate_edge(row):
    try:
        pdata = player_data[player_data["clean_name"] == row["clean_name"]]

        if pdata.empty:
            return row["line"], 0

        pdata = pdata.iloc[0]

        # STAT-SPECIFIC MODEL
        if row["stat"] == "Points":
            base = (
                0.4 * pdata["last5_pts"] +
                0.4 * pdata["last10_pts"] +
                0.2 * pdata["avg_pts"]
            )
            std = pdata["std_dev"]

        elif row["stat"] == "Rebounds":
            base = pdata.get("avg_reb", 5)
            std = pdata.get("reb_std", 2)

        elif row["stat"] == "Assists":
            base = pdata.get("avg_ast", 5)
            std = pdata.get("ast_std", 2)

        else:
            return row["line"], 0

        # MINUTES MODEL
        minutes = pdata["minutes"]
        trend = pdata["minutes_trend"]
        adj_minutes = minutes * trend

        ppm = base / minutes
        projection = ppm * adj_minutes

        # MATCHUP
        match = matchups[matchups["player"] == pdata["player"]]
        opponent = match.iloc[0]["opponent"] if not match.empty else None

        # DVP
        def_row = defense_data[
            (defense_data["team"] == opponent) &
            (defense_data["position"] == pdata["position"])
        ]

        if not def_row.empty:
            def_rating = def_row.iloc[0]["def_rating"]
            league_avg = defense_data["def_rating"].mean()
            projection *= (league_avg / def_rating)

        # EDGE
        std = max(std, 1)
        edge_multiplier = 1.15
        adj_projection = projection * edge_multiplier

        prob = 1 - norm.cdf(row["line"], adj_projection, std)
        implied = 0.524

        edge = prob - implied

        return projection, edge

    except:
        return row["line"], 0

# -------------------------
# APPLY MODEL
# -------------------------
df[["projection", "edge"]] = df.apply(
    lambda row: pd.Series(calculate_edge(row)), axis=1
)

df = df.sort_values(by="edge", ascending=False)

# -------------------------
# UI
# -------------------------
st.subheader("🔥 Best Bets")

st.dataframe(df.head(25), use_container_width=True)

player = st.selectbox("Select Player", df["player"].unique())
row = df[df["player"] == player].iloc[0]

st.metric("Projection", round(row["projection"], 2))
st.metric("Line", row["line"])
st.metric("Edge", f"{round(row['edge'] * 100, 2)}%")
