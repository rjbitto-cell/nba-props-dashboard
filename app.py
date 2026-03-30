import streamlit as st
import pandas as pd
from scipy.stats import norm
from nba_api.stats.endpoints import leaguedashplayerstats

st.set_page_config(page_title="NBA Sharp Props Tool", layout="wide")
st.title("🏀 NBA Sharp Props Tool")

IMPLIED_PROB = 0.524

# -------------------------
# LOAD FAST NBA DATA (ONE CALL)
# -------------------------
@st.cache_data(ttl=600)
def load_player_stats():
    df = leaguedashplayerstats.LeagueDashPlayerStats(
        season='2025-26',
        per_mode_detailed='PerGame'
    ).get_data_frames()[0]
    return df

st.subheader("📊 Generating projections...")

player_stats = load_player_stats()

# -------------------------
# BUILD PROJECTIONS (FAST)
# -------------------------
rows = []

for _, p in player_stats.iterrows():
    try:
        name = p["PLAYER_NAME"]

        pts = p["PTS"]
        reb = p["REB"]
        ast = p["AST"]

        # Simple base projections (fast)
        projection_pts = pts
        projection_reb = reb
        projection_ast = ast

        # Std dev approximation (important for edge calc)
        std_pts = max(pts * 0.25, 1)
        std_reb = max(reb * 0.30, 1)
        std_ast = max(ast * 0.30, 1)

        rows.append({"player": name, "stat": "Points", "projection": round(projection_pts, 2), "std": std_pts})
        rows.append({"player": name, "stat": "Rebounds", "projection": round(projection_reb, 2), "std": std_reb})
        rows.append({"player": name, "stat": "Assists", "projection": round(projection_ast, 2), "std": std_ast})

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
# PLAYER DETAIL
# -------------------------
st.subheader("🔍 Player Detail")

if not filtered.empty:
    player = st.selectbox("Select Player", filtered["player"].unique())
    row = filtered[filtered["player"] == player].iloc[0]

    st.metric("Projection", row["projection"])
    st.metric("Line", row["line"])
    st.metric("Edge", f"{round(row['edge'] * 100, 2)}%")
