import streamlit as st
import pandas as pd
from scipy.stats import norm
from nba_api.stats.endpoints import leaguedashplayerstats

st.set_page_config(page_title="NBA Sharp Props Tool", layout="wide")
st.title("🏀 NBA Sharp Props Tool")

# -------------------------
# SETTINGS
# -------------------------
IMPLIED_PROB = 0.524  # -110 odds baseline

# -------------------------
# LOAD DATA (FAST - ONE CALL)
# -------------------------
@st.cache_data(ttl=600)
def load_player_stats():
    df = leaguedashplayerstats.LeagueDashPlayerStats(
        season='2025-26',
        per_mode_detailed='PerGame'
    ).get_data_frames()[0]
    return df

st.subheader("📊 Generating smart projections...")

player_stats = load_player_stats()

# -------------------------
# SMART PROJECTIONS ENGINE
# -------------------------
rows = []

for _, p in player_stats.iterrows():
    try:
        name = p["PLAYER_NAME"]

        pts = p["PTS"]
        reb = p["REB"]
        ast = p["AST"]
        minutes = p["MIN"]

        # -------------------------
        # 1. MINUTES ADJUSTMENT
        # -------------------------
        minute_factor = minutes / 30
        minute_factor = max(0.8, min(1.2, minute_factor))  # cap extremes

        # -------------------------
        # 2. USAGE PROXY
        # -------------------------
        usage_proxy = (p["FGA"] + 0.5 * p["AST"]) / max(minutes, 1)
        usage_factor = max(0.85, min(1.15, usage_proxy / 1.2))

        # -------------------------
        # 3. EFFICIENCY BOOST
        # -------------------------
        fg = p["FG_PCT"]
        efficiency_factor = 1 + ((fg - 0.45) * 0.3)

        # -------------------------
        # FINAL PROJECTIONS
        # -------------------------
        projection_pts = pts * minute_factor * usage_factor * efficiency_factor
        projection_reb = reb * minute_factor
        projection_ast = ast * usage_factor

        # -------------------------
        # 4. SMART VOLATILITY
        # -------------------------
        volatility = max(0.15, min(0.35, (p["FGA"] / max(minutes,1)) * 0.5))

        std_pts = max(projection_pts * volatility, 1)
        std_reb = max(projection_reb * 0.30, 1)
        std_ast = max(projection_ast * 0.30, 1)

        rows.append({
            "player": name,
            "stat": "Points",
            "projection": round(projection_pts, 2),
            "std": std_pts
        })

        rows.append({
            "player": name,
            "stat": "Rebounds",
            "projection": round(projection_reb, 2),
            "std": std_reb
        })

        rows.append({
            "player": name,
            "stat": "Assists",
            "projection": round(projection_ast, 2),
            "std": std_ast
        })

    except:
        continue

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
# FILTER + DISPLAY
# -------------------------
st.subheader("🔥 Best Value Bets")

filtered = input_df.dropna(subset=["edge"])
filtered = filtered.sort_values(by="edge", ascending=False)

st.dataframe(filtered.head(25), use_container_width=True)

# -------------------------
# PLAYER DETAIL VIEW
# -------------------------
st.subheader("🔍 Player Detail")

if not filtered.empty:
    player = st.selectbox("Select Player", filtered["player"].unique())
    row = filtered[filtered["player"] == player].iloc[0]

    st.metric("Projection", row["projection"])
    st.metric("Line", row["line"])
    st.metric("Edge", f"{round(row['edge'] * 100, 2)}%")
