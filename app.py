import streamlit as st
import pandas as pd
import requests
import time

st.set_page_config(page_title="NBA Sharp Props Tool", layout="wide")

# ==============================
# CONFIG
# ==============================
API_KEY = st.secrets["ODDS_API_KEY"]

# ==============================
# HELPERS
# ==============================
def clean_name(name):
    return str(name).lower().replace(".", "").replace("'", "").strip()

# ==============================
# LOAD DATA
# ==============================
@st.cache_data
def load_players():
    df = pd.read_csv("data/player_stats.csv")

    df = df.rename(columns={
        "Player": "player",
        "Team": "team",
        "MP": "minutes",
        "PTS": "avg_pts",
        "TRB": "avg_reb",
        "AST": "avg_ast"
    })

    df["clean_name"] = df["player"].apply(clean_name)
    df["team"] = df["team"].str.upper().str.replace("PHO", "PHX")

    return df

@st.cache_data
def load_team_def():
    df = pd.read_csv("data/team_defense.csv")
    df["team"] = df["team"].str.upper()
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

    # regression (fix inflated projections)
    league_avg = {"pts": 15, "reb": 5, "ast": 4}
    proj = proj * 0.7 + league_avg[stat] * 0.3

    # DvP
    if dvp and row.get("opponent") in dvp:
        proj *= dvp[row["opponent"]][stat]

    # injury
    proj *= (1 + injury)

    return round(proj, 2)

# ==============================
# WORKING ODDS FETCH (MATCHES COLAB)
# ==============================
def fetch_props():
    rows = []

    events_url = "https://api.the-odds-api.com/v4/sports/basketball_nba/events"

    res = requests.get(events_url, params={
        "apiKey": API_KEY,
        "dateFormat": "iso"
    })

    if res.status_code != 200:
        st.error(f"Events error: {res.status_code}")
        return pd.DataFrame()

    events = res.json()
    st.write(f"📅 Events: {len(events)}")

    for event in events:
        event_id = event["id"]
        home = event["home_team"]
        away = event["away_team"]

        odds_url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/events/{event_id}/odds"

        odds_res = requests.get(odds_url, params={
            "apiKey": API_KEY,
            "regions": "us",
            "markets": "player_points,player_rebounds,player_assists",
            "oddsFormat": "american",
            "dateFormat": "iso"
        })

        if odds_res.status_code != 200:
            continue

        data = odds_res.json()

        for book in data.get("bookmakers", []):
            for market in book.get("markets", []):

                key = market.get("key", "")

                if "player_points" in key:
                    stat = "pts"
                elif "player_rebounds" in key:
                    stat = "reb"
                elif "player_assists" in key:
                    stat = "ast"
                else:
                    continue

                for outcome in market.get("outcomes", []):
                    rows.append({
                        "player": outcome.get("description"),
                        "clean_name": clean_name(outcome.get("description")),
                        "stat": stat,
                        "line": outcome.get("point"),
                        "price": outcome.get("price"),
                        "book": book.get("key"),
                        "home_team": home,
                        "away_team": away
                    })

        time.sleep(0.2)

    df = pd.DataFrame(rows)

    st.write(f"📊 Props pulled: {len(df)}")

    return df

# ==============================
# INJURY BOOST (TEMP)
# ==============================
def injury_boost(player):
    boosts = {
        "austin reaves": 0.10,
        "payton pritchard": 0.12
    }
    return boosts.get(player, 0)

# ==============================
# APP
# ==============================
st.title("🏀 NBA Sharp Props Tool")

if "props" not in st.session_state:
    st.session_state["props"] = None

if st.button("🚀 Fetch Props"):
    st.session_state["props"] = fetch_props()

props = st.session_state["props"]

if props is None or props.empty:
    st.warning("Click fetch to load props")
    st.stop()

# ==============================
# LOAD DATA
# ==============================
players = load_players()
team_def = load_team_def()
dvp = build_dvp(team_def)

# ==============================
# BEST LINE
# ==============================
best = (
    props.sort_values("line")
    .groupby(["clean_name", "stat"], as_index=False)
    .first()
)

# ==============================
# MERGE (SAFE)
# ==============================
merged = best.merge(players, on="clean_name", how="left")

# ==============================
# OPPONENT FIX
# ==============================
def get_opponent(row):
    if pd.isna(row["team"]):
        return None
    if row["team"] == row["home_team"]:
        return row["away_team"]
    return row["home_team"]

merged["opponent"] = merged.apply(get_opponent, axis=1)

# ==============================
# PROJECTIONS
# ==============================
merged["projection"] = merged.apply(
    lambda r: project(
        r,
        r["stat"],
        dvp,
        injury_boost(r["clean_name"])
    ) if pd.notna(r.get("minutes")) else None,
    axis=1
)

# ==============================
# EDGE
# ==============================
merged["edge"] = (merged["projection"] - merged["line"]) / merged["line"]

# ==============================
# SHARP FILTER
# ==============================
sharp = merged[
    (merged["edge"] > 0.08) &
    (merged["minutes"] > 24)
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
