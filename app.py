import streamlit as st
import pandas as pd
import requests
from scipy.stats import norm
import re

st.set_page_config(page_title="NBA Sharp Props Tool", layout="wide")
st.title("🏀 NBA Sharp Props Tool")

IMPLIED_PROB = 0.524
VALID_BOOKS = ["draftkings", "fanduel", "betmgm", "caesars"]
MAX_GAMES = 4  # limit API usage

# -------------------------
# API KEY
# -------------------------
try:
    ODDS_API_KEY = st.secrets["ODDS_API_KEY"]
except:
    st.error("Missing ODDS_API_KEY in secrets")
    st.stop()

# -------------------------
# SESSION STATE (KEY FEATURE)
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
    try:
        df = pd.read_csv("data/player_stats.csv")
        return df
    except:
        return pd.DataFrame({
            "player": ["LeBron James", "Stephen Curry"],
            "team": ["LAL", "GSW"],
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

player_data = load_data()
player_data["clean_name"] = player_data["player"].apply(clean_name)

# -------------------------
# PROJECTION MODEL
# -------------------------
def project(p, stat):
    try:
        minutes = p["minutes"]
        trend = p["minutes_trend"]

        minute_factor = max(0.8, min(1.2, trend))
        usage_factor = (p["avg_pts"] + p["avg_ast"]) / max(minutes, 1)
        efficiency = 1 + ((p["fg_pct"] - 0.45) * 0.3)

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

# Build projections
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
# CACHE EVENTS (SAVES CALLS)
# -------------------------
@st.cache_data(ttl=3600)
def load_events():
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/events"
    res = requests.get(url, params={"apiKey": ODDS_API_KEY}, timeout=10)

    if res.status_code != 200:
        return []

    return res.json()

# -------------------------
# LOAD ODDS (ON DEMAND)
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
# BUTTON (KEY FEATURE)
# -------------------------
if st.button("🔄 Load / Refresh Odds"):
    with st.spinner("Fetching odds..."):
        st.session_state.odds_data = load_odds()

# -------------------------
# USE STORED DATA
# -------------------------
odds_df = st.session_state.odds_data

def get_best_lines(df):
    if df.empty:
        return pd.DataFrame()

    return (
        df.sort_values("line")
        .groupby(["clean_name", "stat"], as_index=False)
        .first()
        .rename(columns={"line": "best_line"})
    )

best_df = get_best_lines(odds_df)

# -------------------------
# MERGE
# -------------------------
merged = proj_df.merge(best_df, on=["clean_name", "stat"], how="inner")

# -------------------------
# EDGE
# -------------------------
def calculate_edge(row):
    try:
        prob = 1 - norm.cdf(row["best_line"], row["projection"], row["std"])
        return prob - IMPLIED_PROB
    except:
        return None

if not merged.empty:
    merged["edge"] = merged.apply(calculate_edge, axis=1)

    merged = merged[
        (merged["edge"] > 0.03) &
        (merged["edge"] < 0.15) &
        (merged["projection"] > 5)
    ]

# -------------------------
# DISPLAY
# -------------------------
st.subheader("🔥 Sharp Bets")

if odds_df.empty:
    st.info("Click 'Load / Refresh Odds' to fetch data")
elif merged.empty:
    st.warning("No sharp bets found right now")
else:
    merged = merged.sort_values("edge", ascending=False)

    st.dataframe(
        merged[[
            "player",
            "stat",
            "best_line",
            "projection",
            "edge",
            "book"
        ]].head(25),
        use_container_width=True
    )
