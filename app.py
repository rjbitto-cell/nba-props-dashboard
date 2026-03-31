import streamlit as st
import pandas as pd
import requests
from scipy.stats import norm
import re

st.set_page_config(page_title="NBA Sharp Props Tool", layout="wide")
st.title("🏀 NBA Sharp Props Tool")

IMPLIED_PROB = 0.524
VALID_BOOKS = ["draftkings", "fanduel", "betmgm", "caesars"]
MAX_GAMES = 10

# -------------------------
# API KEY
# -------------------------
try:
    ODDS_API_KEY = st.secrets["ODDS_API_KEY"]
except:
    st.error("Missing ODDS_API_KEY in secrets")
    st.stop()

# -------------------------
# SESSION STATE
# -------------------------
if "odds_data" not in st.session_state:
    st.session_state.odds_data = pd.DataFrame()

# -------------------------
# NAME CLEANING
# -------------------------
def clean_name(name):
    name = str(name).lower()
    name = re.sub(r"[^a-z\s]", "", name)
    name = name.replace(" jr", "").replace(" sr", "")
    return name.strip()

# -------------------------
# LOAD PLAYER DATA
# -------------------------
@st.cache_data
def load_data():
    df = pd.read_csv("data/player_stats.csv")
    df["clean_name"] = df["player"].apply(clean_name)
    return df

player_data = load_data()

# -------------------------
# PROJECTIONS
# -------------------------
def project(p, stat):
    try:
        minutes = p["minutes"]
        trend = p["minutes_trend"]

        minute_factor = max(0.85, min(1.2, trend))
        usage_factor = (p["avg_pts"] + p["avg_ast"]) / max(minutes, 1)
        efficiency = 1 + ((p["fg_pct"] - 0.45) * 0.25)

        if stat == "Points":
            base = 0.4*p["last5_pts"] + 0.4*p["last10_pts"] + 0.2*p["avg_pts"]
            std = max(p["std_dev"], 1)
            proj = base * minute_factor * efficiency

        elif stat == "Rebounds":
            base = p["avg_reb"]
            std = max(p["reb_std"], 1)
            proj = base * minute_factor

        elif stat == "Assists":
            base = p["avg_ast"]
            std = max(p["ast_std"], 1)
            proj = base * usage_factor

        else:
            return None, None

        return proj, std
    except:
        return None, None

rows = []
for _, p in player_data.iterrows():
    for stat in ["Points", "Rebounds", "Assists"]:
        proj, std = project(p, stat)
        if proj:
            rows.append({
                "player": p["player"],
                "clean_name": p["clean_name"],
                "stat": stat,
                "projection": proj,
                "std": std
            })

proj_df = pd.DataFrame(rows)

# -------------------------
# LOAD EVENTS
# -------------------------
@st.cache_data(ttl=3600)
def load_events():
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/events"
    res = requests.get(url, params={"apiKey": ODDS_API_KEY}, timeout=10)
    if res.status_code != 200:
        return []
    return res.json()

# -------------------------
# LOAD ODDS
# -------------------------
@st.cache_data(ttl=1800)
def load_odds():
    try:
        events = load_events()
        rows = []

        for event in events[:MAX_GAMES]:
            event_id = event.get("id")

            url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/events/{event_id}/odds"

            params = {
                "apiKey": ODDS_API_KEY,
                "regions": "us",
                "markets": "player_points,player_rebounds,player_assists",
                "oddsFormat": "american"
            }

            res = requests.get(url, params=params, timeout=10)
            if res.status_code != 200:
                continue

            data = res.json()

            for book in data.get("bookmakers", []):
                if book.get("key") not in VALID_BOOKS:
                    continue

                for market in book.get("markets", []):
                    stat_map = {
                        "player_points": "Points",
                        "player_rebounds": "Rebounds",
                        "player_assists": "Assists"
                    }

                    stat = stat_map.get(market.get("key"))
                    if not stat:
                        continue

                    for o in market.get("outcomes", []):
                        player = o.get("description")
                        line = o.get("point")

                        if not player or line is None:
                            continue

                        rows.append({
                            "player": player,
                            "clean_name": clean_name(player),
                            "stat": stat,
                            "line": float(line),
                            "book": book.get("key")
                        })

        return pd.DataFrame(rows)

    except Exception as e:
        st.error(f"Odds load failed: {e}")
        return pd.DataFrame()

# -------------------------
# BUTTON
# -------------------------
if st.button("🔄 Load / Refresh Odds"):
    with st.spinner("Fetching odds..."):
        st.session_state.odds_data = load_odds()

odds_df = st.session_state.odds_data

# -------------------------
# BEST LINE
# -------------------------
def get_best_lines(df):
    if df.empty:
        return pd.DataFrame()

    return (
        df.sort_values("line")
        .groupby(["clean_name", "stat"], as_index=False)
        .first()
        .rename(columns={"line": "best_line"})
    )

# -------------------------
# LINE RANGE
# -------------------------
def add_line_range(df):
    if df.empty:
        return pd.DataFrame()

    ranges = (
        df.groupby(["clean_name", "stat"])["line"]
        .agg(["min", "max"])
        .reset_index()
    )

    ranges["line_diff"] = ranges["max"] - ranges["min"]

    return ranges

best_df = get_best_lines(odds_df)
range_df = add_line_range(odds_df)

# -------------------------
# MERGE
# -------------------------
merged = proj_df.merge(best_df, on=["clean_name", "stat"], how="inner")
merged = merged.merge(range_df, on=["clean_name", "stat"], how="left")

# -------------------------
# EDGE
# -------------------------
def calculate_edge(row):
    try:
        prob = 1 - norm.cdf(row["best_line"], row["projection"], row["std"])
        return prob - IMPLIED_PROB
    except:
        return None

def label_edge(edge):
    if edge is None:
        return "N/A"
    elif edge > 0.06:
        return "🔥 STRONG"
    elif edge > 0.03:
        return "✅ PLAYABLE"
    elif edge > 0.015:
        return "👀 LEAN"
    else:
        return "❌ PASS"

# -------------------------
# PROCESS
# -------------------------
if not merged.empty:
    merged["edge"] = merged.apply(calculate_edge, axis=1)
    merged["edge_tier"] = merged["edge"].apply(label_edge)

    merged = merged[
        (merged["edge"] > 0.005) &
        (merged["projection"] > 5)
    ]

    merged = merged.sort_values(
        ["edge", "line_diff"],
        ascending=[False, False]
    )

# -------------------------
# DEBUG
# -------------------------
st.write("Total props analyzed:", len(merged))
st.write("Columns:", merged.columns.tolist())

# -------------------------
# DISPLAY
# -------------------------
st.subheader("🔥 Sharp Bets")

if odds_df.empty:
    st.info("Click 'Load / Refresh Odds'")
elif merged.empty:
    st.warning("No sharp bets found right now")
else:
    # Fix player column
    if "player_x" in merged.columns:
        merged["player"] = merged["player_x"]
    elif "player_y" in merged.columns:
        merged["player"] = merged["player_y"]

    # Ensure book exists
    if "book" not in merged.columns:
        merged["book"] = "N/A"

    cols = [
        "player",
        "stat",
        "best_line",
        "projection",
        "edge",
        "edge_tier",
        "line_diff",
        "book"
    ]

    safe_cols = [c for c in cols if c in merged.columns]

    st.dataframe(
        merged[safe_cols].head(25),
        use_container_width=True
    )
