import streamlit as st
import pandas as pd
import requests
from scipy.stats import norm

st.set_page_config(page_title="NBA Sharp Props Tool", layout="wide")
st.title("🏀 NBA Sharp Props Tool")

IMPLIED_PROB = 0.524

# -------------------------
# LOAD API KEY SECURELY
# -------------------------
try:
    ODDS_API_KEY = st.secrets["ODDS_API_KEY"]
except:
    st.error("❌ Missing ODDS_API_KEY in Streamlit secrets")
    st.stop()

# -------------------------
# LOAD DATA (SAFE)
# -------------------------
@st.cache_data
def load_data():
    try:
        player_data = pd.read_csv("data/player_stats.csv")
        defense_data = pd.read_csv("data/team_defense.csv")
        matchups = pd.read_csv("data/matchups.csv")

        if player_data.empty:
            raise ValueError("Empty player data")

        return player_data, defense_data, matchups

    except Exception as e:
        st.warning(f"Using fallback data: {e}")

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

        return player_data, pd.DataFrame(), pd.DataFrame()

player_data, defense_data, matchups = load_data()

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
                "stat": stat,
                "projection": proj,
                "std": std
            })

proj_df = pd.DataFrame(rows)

# -------------------------
# ODDS API
# -------------------------
@st.cache_data(ttl=300)
def load_odds():
    try:
        url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"

        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "us",
            "markets": "player_points,player_rebounds,player_assists",
            "oddsFormat": "american"
        }

        res = requests.get(url, params=params, timeout=10)
        data = res.json()

        rows = []

        for game in data:
            for book in game.get("bookmakers", []):
                book_name = book["key"]

                for market in book.get("markets", []):
                    stat_map = {
                        "player_points": "Points",
                        "player_rebounds": "Rebounds",
                        "player_assists": "Assists"
                    }

                    stat = stat_map.get(market["key"])
                    if not stat:
                        continue

                    for o in market["outcomes"]:
                        player = o.get("description")
                        line = o.get("point")

                        if not player or line is None:
                            continue

                        rows.append({
                            "player": player,
                            "stat": stat,
                            "line": float(line),
                            "book": book_name
                        })

        df = pd.DataFrame(rows)

        if df.empty:
            st.warning("No odds data returned")
            return df

        return df

    except Exception as e:
        st.error(f"Odds API failed: {e}")
        return pd.DataFrame()

odds_df = load_odds()

# -------------------------
# BEST LINE SELECTION
# -------------------------
def get_best_lines(df):
    if df.empty:
        return df

    best = df.sort_values("line").groupby(["player", "stat"]).first().reset_index()
    best = best.rename(columns={"line": "best_line"})
    return best

best_df = get_best_lines(odds_df)

# -------------------------
# MERGE + EDGE
# -------------------------
merged = proj_df.merge(best_df, on=["player", "stat"], how="inner")

def calculate_edge(row):
    try:
        prob = 1 - norm.cdf(row["best_line"], row["projection"], row["std"])
        return prob - IMPLIED_PROB
    except:
        return None

if not merged.empty:
    merged["edge"] = merged.apply(calculate_edge, axis=1)

# -------------------------
# DISPLAY
# -------------------------
st.subheader("🔥 Best Bets (Auto Odds)")

if merged.empty:
    st.warning("No matching odds or projections found")
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
