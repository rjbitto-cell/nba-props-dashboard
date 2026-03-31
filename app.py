import streamlit as st
import pandas as pd
import requests
import time

st.set_page_config(page_title="NBA Sharp Props Tool", layout="wide")

# ==============================
# CONFIG
# ==============================
API_KEY = st.secrets["ODDS_API_KEY"]
REGIONS = "us"
MARKETS = ["player_points", "player_rebounds", "player_assists"]
BOOKS = ["draftkings", "fanduel", "betmgm", "caesars", "betrivers"]

# ==============================
# HELPERS
# ==============================
def clean_name(name):
    return str(name).lower().replace(".", "").strip()

# ==============================
# LOAD DATA
# ==============================
@st.cache_data
def load_players():
    df = pd.read_csv("data/player_stats.csv")
    df["clean_name"] = df["player"].apply(clean_name)
    return df

@st.cache_data
def load_team_def():
    df = pd.read_csv("data/team_defense.csv")
    return df

def build_dvp(team_def):
    league_pts = team_def["pts_allowed"].mean()
    league_reb = team_def["reb_allowed"].mean()
    league_ast = team_def["ast_allowed"].mean()

    dvp = {}
    for _, r in team_def.iterrows():
        dvp[r["team"]] = {
            "pts": r["pts_allowed"] / league_pts,
            "reb": r["reb_allowed"] / league_reb,
            "ast": r["ast_allowed"] / league_ast
        }
    return dvp

# ==============================
# PROJECTION MODEL (FIXED)
# ==============================
def project(row, stat, dvp=None, injury=0):
    mpg = row["minutes"]
    val = row[f"avg_{stat}"]

    per_min = val / mpg if mpg > 0 else 0
    exp_min = min(max(mpg, 20), 36)

    proj = per_min * exp_min

    # regression
    league_avg = {"pts": 15, "reb": 5, "ast": 4}
    proj = proj * 0.7 + league_avg[stat] * 0.3

    # DvP
    if dvp and row.get("opponent") in dvp:
        proj *= dvp[row["opponent"]][stat]

    # injury boost
    proj *= (1 + injury)

    return round(proj, 2)

# ==============================
# ODDS API (ON DEMAND)
# ==============================
def fetch_props():
    url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
    params = {
        "apiKey": API_KEY,
        "regions": REGIONS,
        "markets": ",".join(MARKETS),
        "oddsFormat": "american"
    }

    res = requests.get(url, params=params)

    if res.status_code != 200:
        st.error(f"Odds API Error: {res.status_code}")
        return pd.DataFrame()

    data = res.json()
    rows = []

    for game in data:
        home = game["home_team"]
        away = game["away_team"]

        for book in game.get("bookmakers", []):
            if book["key"] not in BOOKS:
                continue

            for market in book.get("markets", []):
                stat_map = {
                    "player_points": "pts",
                    "player_rebounds": "reb",
                    "player_assists": "ast"
                }

                stat = stat_map.get(market["key"])
                if not stat:
                    continue

                for o in market["outcomes"]:
                    rows.append({
                        "player": o["description"],
                        "clean_name": clean_name(o["description"]),
                        "stat": stat,
                        "line": o.get("point"),
                        "price": o["price"],
                        "book": book["key"],
                        "opponent": away if o["description"] in home else home
                    })

    return pd.DataFrame(rows)

# ==============================
# INJURY BOOST (SIMPLE + SAFE)
# ==============================
def injury_boost(player):
    boosts = {
        "austin reaves": 0.10,
        "payton pritchard": 0.12,
        "jaime jaquez jr": 0.10
    }
    return boosts.get(player, 0)

# ==============================
# MAIN
# ==============================
st.title("🏀 NBA Sharp Props Tool")

if "data" not in st.session_state:
    st.session_state["data"] = None

if st.button("🚀 Fetch Latest Props"):
    st.session_state["data"] = fetch_props()

props = st.session_state["data"]

if props is None or props.empty:
    st.warning("Click button to load props")
    st.stop()

players = load_players()
team_def = load_team_def()
dvp = build_dvp(team_def)

# ==============================
# BEST LINE PER PLAYER
# ==============================
best = (
    props.sort_values("line")
    .groupby(["clean_name", "stat"], as_index=False)
    .first()
)

# ==============================
# MERGE
# ==============================
merged = best.merge(players, on="clean_name", how="inner")

# ==============================
# PROJECTIONS
# ==============================
merged["projection"] = merged.apply(
    lambda r: project(
        r,
        r["stat"],
        dvp,
        injury_boost(r["clean_name"])
    ),
    axis=1
)

# ==============================
# EDGE + CONFIDENCE
# ==============================
merged["edge"] = (merged["projection"] - merged["line"]) / merged["line"]
merged["confidence"] = merged["minutes"] / 36

# ==============================
# FILTER (SHARP)
# ==============================
sharp = merged[
    (merged["edge"] > 0.08) &
    (merged["confidence"] > 0.65)
]

# ==============================
# DISPLAY
# ==============================
st.subheader("🔥 Sharp Bets")

if sharp.empty:
    st.write("No sharp bets right now")
else:
    st.dataframe(
        sharp[[
            "player",
            "stat",
            "line",
            "projection",
            "edge",
            "book"
        ]].sort_values("edge", ascending=False),
        use_container_width=True
    )

# ==============================
# ALL PROPS
# ==============================
st.subheader("📊 All Props")

st.dataframe(
    merged[[
        "player",
        "stat",
        "line",
        "projection",
        "edge",
        "book"
    ]].sort_values("edge", ascending=False).head(50),
    use_container_width=True
)
