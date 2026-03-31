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
ODDS_API_KEY = st.secrets["ODDS_API_KEY"]

# -------------------------
# STATE
# -------------------------
if "odds_data" not in st.session_state:
    st.session_state.odds_data = pd.DataFrame()

# -------------------------
# CLEAN NAMES
# -------------------------
def clean_name(name):
    name = str(name).lower()
    name = re.sub(r"[^a-z\s]", "", name)
    return name.strip()

# -------------------------
# LOAD DATA
# -------------------------
@st.cache_data
def load_players():
    df = pd.read_csv("data/player_stats.csv")
    df["clean_name"] = df["player"].apply(clean_name)
    return df

@st.cache_data
def load_team_def():
    df = pd.read_csv("data/team_defense.csv")
    df.columns = [c.lower() for c in df.columns]
    return df

players = load_players()
team_def = load_team_def()

# -------------------------
# BUILD DVP
# -------------------------
def build_dvp(df):
    pts = [c for c in df.columns if "pts" in c][0]
    reb = [c for c in df.columns if "reb" in c][0]
    ast = [c for c in df.columns if "ast" in c][0]
    team = [c for c in df.columns if "team" in c][0]

    avg_pts = df[pts].mean()
    avg_reb = df[reb].mean()
    avg_ast = df[ast].mean()

    dvp = {}
    for _, r in df.iterrows():
        dvp[r[team]] = {
            "Points": r[pts] / avg_pts,
            "Rebounds": r[reb] / avg_reb,
            "Assists": r[ast] / avg_ast
        }
    return dvp

DVP = build_dvp(team_def)

# -------------------------
# MATCHUPS (AUTO)
# -------------------------
@st.cache_data(ttl=1800)
def load_matchups():
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/events"
    res = requests.get(url, params={"apiKey": ODDS_API_KEY}).json()

    m = {}
    for e in res[:MAX_GAMES]:
        m[e["home_team"]] = e["away_team"]
        m[e["away_team"]] = e["home_team"]
    return m

MATCHUPS = load_matchups()

# -------------------------
# PROJECTION MODEL (FIXED)
# -------------------------
def project(p, stat):
    try:
        team = p["team"]
        opp = MATCHUPS.get(team)

        # BASELINE (REGRESSION)
        if stat == "Points":
            base = 0.4*p["last5_pts"] + 0.3*p["last10_pts"] + 0.3*p["avg_pts"]
            std = max(p["std_dev"], 1)

        elif stat == "Rebounds":
            base = p["avg_reb"]
            std = max(p["reb_std"], 1)

        elif stat == "Assists":
            base = p["avg_ast"]
            std = max(p["ast_std"], 1)

        else:
            return None, None

        # MINUTES (CAPPED)
        minute_boost = max(0.9, min(1.1, p["minutes_trend"]))

        # USAGE (CAPPED)
        usage_spike = (p["last5_pts"] - p["avg_pts"]) / max(p["avg_pts"], 1)
        usage_boost = 1.05 if usage_spike > 0.08 else 1.0

        # DVP (CAPPED)
        dvp_boost = 1.0
        if opp in DVP:
            dvp_boost = max(0.9, min(1.1, DVP[opp].get(stat, 1.0)))

        # FINAL (CONTROLLED)
        proj = base * minute_boost * usage_boost * dvp_boost

        return proj, std

    except:
        return None, None

# -------------------------
# BUILD PROJECTIONS
# -------------------------
proj_rows = []
for _, p in players.iterrows():
    for stat in ["Points","Rebounds","Assists"]:
        proj, std = project(p, stat)
        if proj:
            proj_rows.append({
                "player": p["player"],
                "clean_name": p["clean_name"],
                "stat": stat,
                "projection": proj,
                "std": std
            })

proj_df = pd.DataFrame(proj_rows)

# -------------------------
# LOAD ODDS + TRACK HISTORY
# -------------------------
def load_odds():
    rows = []

    events = requests.get(
        "https://api.the-odds-api.com/v4/sports/basketball_nba/events",
        params={"apiKey": ODDS_API_KEY}
    ).json()

    for e in events[:MAX_GAMES]:
        event_id = e["id"]

        res = requests.get(
            f"https://api.the-odds-api.com/v4/sports/basketball_nba/events/{event_id}/odds",
            params={
                "apiKey": ODDS_API_KEY,
                "regions": "us",
                "markets": "player_points,player_rebounds,player_assists"
            }
        )

        if res.status_code != 200:
            continue

        for book in res.json().get("bookmakers", []):
            if book["key"] not in VALID_BOOKS:
                continue

            for market in book["markets"]:
                stat_map = {
                    "player_points":"Points",
                    "player_rebounds":"Rebounds",
                    "player_assists":"Assists"
                }

                stat = stat_map.get(market["key"])

                for o in market["outcomes"]:
                    if not o.get("point"):
                        continue

                    rows.append({
                        "player": o["description"],
                        "clean_name": clean_name(o["description"]),
                        "stat": stat,
                        "line": float(o["point"])
                    })

    return pd.DataFrame(rows)

# -------------------------
# BUTTON
# -------------------------
if st.button("🔄 Load Odds"):
    new_odds = load_odds()

    if not st.session_state.odds_data.empty:
        old = st.session_state.odds_data

        merged_move = new_odds.merge(
            old,
            on=["clean_name","stat"],
            how="left",
            suffixes=("", "_old")
        )

        merged_move["line_move"] = merged_move["line"] - merged_move["line_old"]

        st.session_state.odds_data = merged_move
    else:
        new_odds["line_move"] = 0
        st.session_state.odds_data = new_odds

odds_df = st.session_state.odds_data

# -------------------------
# FINAL MERGE
# -------------------------
if not odds_df.empty:

    best = odds_df.sort_values("line").groupby(["clean_name","stat"]).first().reset_index()

    merged = proj_df.merge(best, on=["clean_name","stat"])

    if "player_x" in merged.columns:
        merged["player"] = merged["player_x"]

    merged["edge"] = merged.apply(
        lambda r: (1 - norm.cdf(r["line"], r["projection"], r["std"])) - IMPLIED_PROB,
        axis=1
    )

    # STEAM SIGNAL
    merged["steam"] = merged["line_move"].apply(
        lambda x: "🔥 OVER STEAM" if x > 0.5 else "❄️ UNDER STEAM" if x < -0.5 else ""
    )

    merged = merged.sort_values(["edge","line_move"], ascending=False)

    st.dataframe(
        merged[["player","stat","line","projection","edge","line_move","steam"]].head(25),
        use_container_width=True
    )

else:
    st.info("Click Load Odds")
