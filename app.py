import streamlit as st
import pandas as pd
from scipy.stats import norm

st.set_page_config(page_title="NBA Sharp Props Tool", layout="wide")
st.title("🏀 NBA Sharp Props Tool")

IMPLIED_PROB = 0.524

# -------------------------
# LOAD CSV DATA (PRIMARY SOURCE)
# -------------------------
@st.cache_data
def load_csv_data():
    player_data = pd.read_csv("data/player_stats.csv")
    defense_data = pd.read_csv("data/team_defense.csv")
    matchups = pd.read_csv("data/matchups.csv")
    return player_data, defense_data, matchups

player_data, defense_data, matchups = load_csv_data()

# -------------------------
# OPTIONAL LIVE UPDATE (SAFE)
# -------------------------
def try_live_update():
    try:
        from nba_api.stats.endpoints import leaguedashplayerstats

        df = leaguedashplayerstats.LeagueDashPlayerStats(
            season='2025-26',
            per_mode_detailed='PerGame',
            timeout=5
        ).get_data_frames()[0]

        return df

    except:
        return None

live_data = try_live_update()

# -------------------------
# NORMALIZE NAMES
# -------------------------
def normalize_name(name):
    return str(name).lower().replace(".", "").strip()

player_data["clean_name"] = player_data["player"].apply(normalize_name)

# -------------------------
# SMART PROJECTION MODEL
# -------------------------
def calculate_projection(pdata, stat):
    try:
        minutes = pdata["minutes"]
        trend = pdata["minutes_trend"]

        minute_factor = max(0.8, min(1.2, trend))

        usage_proxy = (pdata["avg_pts"] + pdata["avg_ast"]) / max(minutes, 1)
        usage_factor = max(0.85, min(1.15, usage_proxy / 1.5))

        efficiency_factor = 1 + ((pdata["fg_pct"] - 0.45) * 0.3)

        if stat == "Points":
            base = (
                0.4 * pdata["last5_pts"] +
                0.4 * pdata["last10_pts"] +
                0.2 * pdata["avg_pts"]
            )
            projection = base * minute_factor * usage_factor * efficiency_factor
            std = max(pdata["std_dev"], 1)

        elif stat == "Rebounds":
            base = pdata["avg_reb"]
            projection = base * minute_factor
            std = max(pdata.get("reb_std", 2), 1)

        elif stat == "Assists":
            base = pdata["avg_ast"]
            projection = base * usage_factor
            std = max(pdata.get("ast_std", 2), 1)

        else:
            return None, None

        return projection, std

    except:
        return None, None

# -------------------------
# BUILD PROPS TABLE
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
# USER INPUT (LINES)
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
# DISPLAY
# -------------------------
st.subheader("🔥 Best Value Bets")

filtered = input_df.dropna(subset=["edge"])
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
