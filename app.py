import streamlit as st
import pandas as pd
import requests
from scipy.stats import norm

st.set_page_config(page_title="NBA Sharp Props Tool", layout="wide")
st.title("🏀 NBA Sharp Props Tool")

IMPLIED_PROB = 0.524

# -------------------------
# LOAD API KEY
# -------------------------
try:
    ODDS_API_KEY = st.secrets["ODDS_API_KEY"]
except:
    st.error("❌ Missing ODDS_API_KEY in Streamlit secrets")
    st.stop()

# -------------------------
# LOAD PLAYER DATA
# -------------------------
@st.cache_data
def load_data():
    try:
        df = pd.read_csv("data/player_stats.csv")
        if df.empty:
            raise ValueError("Empty CSV")
        return df
    except:
        st.warning("Using fallback data")
        return pd.DataFrame({
            "player": ["LeBron James", "Stephen Curry"],
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
                "player": p["player"].strip(),
                "stat": stat,
                "projection": proj,
                "std": std
            })

proj_df = pd.DataFrame(rows)

# -------------------------
# ODDS API (EVENT-BASED FIX)
# -------------------------
@st.cache_data(ttl=300)
def load_odds():
    try:
        sport = "basketball_nba"

        # STEP 1: EVENTS
        events_url = f"https://api.the-odds-api.com/v4/sports/{sport}/events"
        events_res = requests.get(events_url, params={"apiKey": ODDS_API_KEY}, timeout=10)

        if events_res.status_code != 200:
            st.error(f"Events API failed: {events_res.status_code}")
            return pd.DataFrame(columns=["player","stat","line","book"])

        events = events_res.json()
        rows = []

        # STEP 2: LOOP EVENTS
        for event in events:
            event_id = event.get("id")
            if not event_id:
                continue

            props_url = f"https://api.the-odds-api.com/v4/sports/{sport}/events/{event_id}/odds"

            params = {
                "apiKey": ODDS_API_KEY,
                "regions": "us",
                "markets": "player_points,player_rebounds,player_assists",
                "oddsFormat": "american"
            }

            res = requests.get(props_url, params=params, timeout=10)

            if res.status_code != 200:
                continue

            data = res.json()

            if not isinstance(data, dict):
                continue

            for book in data.get("bookmakers", []):
                book_name = book.get("key")

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
                            "player": player.strip(),
                            "stat": stat,
                            "line": float(line),
                            "book": book_name
                        })

        df = pd.DataFrame(rows)

        if df.empty:
            st.warning("No props found")
            return pd.DataFrame(columns=["player","stat","line","book"])

        return df

    except Exception as e:
        st.error(f"Odds loading failed: {e}")
        return pd.DataFrame(columns=["player","stat","line","book"])

odds_df = load_odds()

# -------------------------
# BEST LINE
# -------------------------
def get_best_lines(df):
    if df.empty:
        return pd.DataFrame(columns=["player","stat","best_line","book"])

    best = (
        df.sort_values("line")
        .groupby(["player","stat"], as_index=False)
        .first()
        .rename(columns={"line": "best_line"})
    )

    return best

best_df = get_best_lines(odds_df)

# -------------------------
# MERGE
# -------------------------
if not proj_df.empty and not best_df.empty:
    merged = proj_df.merge(best_df, on=["player", "stat"], how="inner")
else:
    merged = pd.DataFrame()

# -------------------------
# EDGE CALCULATION
# -------------------------
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
st.subheader("🔥 Best Bets")

if merged.empty:
    st.warning("No matching odds + projections yet")
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
