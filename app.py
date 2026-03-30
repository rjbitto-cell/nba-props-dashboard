import streamlit as st
import pandas as pd
from scipy.stats import norm
import os

st.set_page_config(page_title="NBA Sharp Props Tool", layout="wide")
st.title("🏀 NBA Sharp Props Tool")

IMPLIED_PROB = 0.524

# -------------------------
# SAFE DATA LOADER
# -------------------------
@st.cache_data
def load_data():
    try:
        files = os.listdir("data")
        st.sidebar.write("📁 Data files:", files)

        player_data = pd.read_csv("data/player_stats.csv")
        defense_data = pd.read_csv("data/team_defense.csv")
        matchups = pd.read_csv("data/matchups.csv")

        if player_data.empty:
            raise ValueError("player_stats.csv is empty")

        return player_data, defense_data, matchups

    except Exception as e:
        st.error(f"⚠️ Data load failed: {e}")
        return fallback_data()

# -------------------------
# FALLBACK DATA (NEVER BREAKS)
# -------------------------
def fallback_data():
    player_data = pd.DataFrame({
        "player": ["LeBron James", "Stephen Curry"],
        "team": ["LAL", "GSW"],
        "position": ["SF", "PG"],
        "minutes": [35, 34],
        "minutes_trend": [1.0, 1.0],
        "avg_pts": [27, 29],
        "avg_reb": [8, 5],
        "avg_ast": [7, 6],
        "last5_pts": [28, 30],
        "last10_pts": [27, 29],
        "fg_pct": [0.5, 0.48],
        "std_dev": [6, 7],
        "reb_std": [3, 2],
        "ast_std": [3, 3],
    })

    defense_data = pd.DataFrame({
        "team": ["LAL", "GSW"],
        "position": ["PG", "SF"],
        "def_rating": [112, 110]
    })

    matchups = pd.DataFrame({
        "player": ["LeBron James", "Stephen Curry"],
        "opponent": ["GSW", "LAL"]
    })

    return player_data, defense_data, matchups

player_data, defense_data, matchups = load_data()

# -------------------------
# INJURY INPUT
# -------------------------
st.sidebar.header("🚑 Injuries")

injured_players = st.sidebar.multiselect(
    "Select Out Players",
    player_data["player"].unique()
)

# -------------------------
# PROJECTION MODEL
# -------------------------
def calculate_projection(pdata, stat):
    try:
        minutes = pdata["minutes"]
        trend = pdata["minutes_trend"]

        minute_factor = max(0.8, min(1.2, trend))

        usage_proxy = (pdata["avg_pts"] + pdata["avg_ast"]) / max(minutes, 1)
        usage_factor = max(0.85, min(1.15, usage_proxy / 1.5))

        efficiency_factor = 1 + ((pdata["fg_pct"] - 0.45) * 0.3)

        # -------------------------
        # INJURY BOOST
        # -------------------------
        team = pdata["team"]

        team_injuries = player_data[
            (player_data["team"] == team) &
            (player_data["player"].isin(injured_players))
        ]

        injury_boost = 1 + (0.05 * len(team_injuries))

        # -------------------------
        # BASE
        # -------------------------
        if stat == "Points":
            base = (
                0.4 * pdata["last5_pts"] +
                0.4 * pdata["last10_pts"] +
                0.2 * pdata["avg_pts"]
            )
            projection = base * minute_factor * usage_factor * efficiency_factor * injury_boost
            std = max(pdata["std_dev"], 1)

        elif stat == "Rebounds":
            base = pdata["avg_reb"]
            projection = base * minute_factor * injury_boost
            std = max(pdata["reb_std"], 1)

        elif stat == "Assists":
            base = pdata["avg_ast"]
            projection = base * usage_factor * injury_boost
            std = max(pdata["ast_std"], 1)

        else:
            return None, None

        # -------------------------
        # DVP
        # -------------------------
        matchup = matchups[matchups["player"] == pdata["player"]]

        if not matchup.empty:
            opponent = matchup.iloc[0]["opponent"]

            def_row = defense_data[
                (defense_data["team"] == opponent) &
                (defense_data["position"] == pdata["position"])
            ]

            if not def_row.empty:
                def_rating = def_row.iloc[0]["def_rating"]
                league_avg = defense_data["def_rating"].mean()
                projection *= (league_avg / def_rating)

        return projection, std

    except:
        return None, None

# -------------------------
# BUILD DATA
# -------------------------
rows = []

for _, pdata in player_data.iterrows():
    for stat in ["Points", "Rebounds", "Assists"]:
        projection, std = calculate_projection(pdata, stat)

        if projection is None:
            continue

        rows.append({
            "player": pdata["player"],
            "stat": stat,
            "projection": round(projection, 2),
            "std": std
        })

df = pd.DataFrame(rows)

# -------------------------
# USER INPUT
# -------------------------
st.subheader("✍️ Enter Sportsbook Lines")

input_df = df.copy()
input_df["line"] = ""

input_df = st.data_editor(input_df, use_container_width=True)

# -------------------------
# EDGE
# -------------------------
def calculate_edge(row):
    try:
        if row["line"] == "" or pd.isna(row["line"]):
            return None

        prob = 1 - norm.cdf(float(row["line"]), row["projection"], row["std"])
        return prob - IMPLIED_PROB
    except:
        return None

input_df["edge"] = input_df.apply(calculate_edge, axis=1)

# -------------------------
# DISPLAY
# -------------------------
st.subheader("🔥 Best Value Bets")

filtered = input_df.dropna(subset=["edge"])

if filtered.empty:
    st.warning("No edges yet — enter sportsbook lines above")
else:
    filtered = filtered.sort_values(by="edge", ascending=False)
    st.dataframe(filtered.head(25), use_container_width=True)

# -------------------------
# PLAYER DETAIL
# -------------------------
st.subheader("🔍 Player Detail")

if not filtered.empty:
    player = st.selectbox("Select Player", filtered["player"].unique())
    row = filtered[filtered["player"] == player].iloc[0]

    st.metric("Projection", row["projection"])
    st.metric("Line", row["line"])
    st.metric("Edge", f"{round(row['edge'] * 100, 2)}%")
