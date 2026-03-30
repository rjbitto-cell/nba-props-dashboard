import streamlit as st
import pandas as pd
import numpy as np
import requests
from scipy.stats import norm

st.set_page_config(page_title="NBA Props Dashboard", layout="wide")
st.title("🏀 NBA Props Dashboard (PrizePicks)")

# -------------------------
# LOAD DATA
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
# LOAD PRIZEPICKS PROPS
# -------------------------
@st.cache_data(ttl=300)
def load_props():
    try:
        url = "https://api.prizepicks.com/projections"
        res = requests.get(url, timeout=10).json()

        data = res.get("data", [])
        included = res.get("included", [])

        players = {
            p["id"]: p["attributes"]["name"]
            for p in included if p["type"] == "new_player"
        }

        rows = []

        for item in data:
            attr = item["attributes"]

            player_id = item["relationships"]["new_player"]["data"]["id"]
            name = players.get(player_id)

            stat = attr.get("stat_type")
            line = attr.get("line_score")

            if stat != "Points":
                continue

            rows.append({
                "player": name,
                "stat": stat,
                "line": line,
                "odds": -110
            })

        df = pd.DataFrame(rows)

        if df.empty:
            st.warning("No PrizePicks data found")

        return df

    except:
        st.error("PrizePicks API failed")
        return pd.DataFrame()

df = load_props()

# -------------------------
# NAME CLEANING (IMPORTANT)
# -------------------------
def normalize_name(name):
    return name.lower().replace(".", "").strip()

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

        # Base projection
        base = (
            0.4 * pdata["last5_pts"] +
            0.4 * pdata["last10_pts"] +
            0.2 * pdata["avg_pts"]
        )

        # Minutes model
        minutes = pdata["minutes"]
        trend = pdata["minutes_trend"]
        adj_minutes = minutes * trend

        ppm = base / minutes
        projection = ppm * adj_minutes

        # Matchup
        match = matchups[matchups["player"] == pdata["player"]]
        opponent = match.iloc[0]["opponent"] if not match.empty else None

        # DvP
        def_row = defense_data[
            (defense_data["team"] == opponent) &
            (defense_data["position"] == pdata["position"])
        ]

        if not def_row.empty:
            def_rating = def_row.iloc[0]["def_rating"]
            league_avg = defense_data["def_rating"].mean()
            projection *= (league_avg / def_rating)

        # Variance
        std = pdata["std_dev"]

        # Edge calc
        edge_multiplier = 1.15
        adj_projection = projection * edge_multiplier

        prob = 1 - norm.cdf(row["line"], adj_projection, std)

        implied = 0.524  # -110 baseline
        edge = prob - implied

        return projection, edge

    except:
        return row["line"], 0

# -------------------------
# APPLY MODEL
# -------------------------
if not df.empty:
    df[["projection", "edge"]] = df.apply(
        lambda row: pd.Series(calculate_edge(row)), axis=1
    )

    df = df.sort_values(by="edge", ascending=False)

# -------------------------
# UI
# -------------------------
st.subheader("🔥 Best Bets")

if not df.empty:
    st.dataframe(df.head(20), use_container_width=True)

    player = st.selectbox("Select Player", df["player"].dropna().unique())
    row = df[df["player"] == player].iloc[0]

    st.metric("Projection", round(row["projection"], 2))
    st.metric("Line", row["line"])
    st.metric("Edge", f"{round(row['edge']*100,2)}%")

else:
    st.warning("No data available")
