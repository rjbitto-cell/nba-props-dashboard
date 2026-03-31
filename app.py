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
# CLEAN NAME
# -------------------------
def clean_name(name):
    name = str(name).lower()
    name = re.sub(r"[^a-z\s]", "", name)
    return name.replace(" jr", "").replace(" sr", "").strip()

# -------------------------
# LOAD PLAYER DATA
# -------------------------
@st.cache_data
def load_players():
    df = pd.read_csv("data/player_stats.csv")
    df["clean_name"] = df["player"].apply(clean_name)
    return df

player_data = load_players()

# -------------------------
# LOAD TEAM DEFENSE
# -------------------------
@st.cache_data
def load_team_defense():
    df = pd.read_csv("data/team_defense.csv")
    df.columns = [c.lower() for c in df.columns]
    return df

team_def = load_team_defense()

# -------------------------
# BUILD DVP (REAL)
# -------------------------
def build_dvp(team_def):
    pts_col = next((c for c in team_def.columns if "pts" in c), None)
    reb_col = next((c for c in team_def.columns if "reb" in c), None)
    ast_col = next((c for c in team_def.columns if "ast" in c), None)
    team_col = next((c for c in team_def.columns if "team" in c), None)

    if not all([pts_col, reb_col, ast_col, team_col]):
        st.error("team_defense.csv missing required columns")
        return {}

    league_avg_pts = team_def[pts_col].mean()
    league_avg_reb = team_def[reb_col].mean()
    league_avg_ast = team_def[ast_col].mean()

    dvp = {}

    for _, row in team_def.iterrows():
        dvp[row[team_col]] = {
            "Points": row[pts_col] / league_avg_pts,
            "Rebounds": row[reb_col] / league_avg_reb,
            "Assists": row[ast_col] / league_avg_ast
        }

    return dvp

DVP = build_dvp(team_def)

# -------------------------
# INJURIES
# -------------------------
@st.cache_data(ttl=1800)
def load_injuries():
    try:
        url = "https://site.web.api.espn.com/apis/v2/sports/basketball/nba/injuries"
        data = requests.get(url, timeout=10).json()

        injury_map = {}

        for team in data.get("teams", []):
            abbr = team.get("team", {}).get("abbreviation")

            outs = [
                p.get("athlete", {}).get("displayName")
                for p in team.get("injuries", [])
                if "out" in str(p.get("status", "")).lower()
            ]

            if outs:
                injury_map[abbr] = {
                    "OUT": outs,
                    "BOOST": min(0.20, 0.05 * len(outs))
                }

        return injury_map if injury_map else {}

    except:
        return {}

injuries = load_injuries()

# -------------------------
# LOAD EVENTS (BUILD MATCHUPS)
# -------------------------
@st.cache_data(ttl=1800)
def load_matchups():
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/events"
    res = requests.get(url, params={"apiKey": ODDS_API_KEY}, timeout=10)

    matchups = {}

    if res.status_code != 200:
        return matchups

    for event in res.json()[:MAX_GAMES]:
        home = event.get("home_team")
        away = event.get("away_team")

        matchups[home] = away
        matchups[away] = home

    return matchups

MATCHUPS = load_matchups()

# -------------------------
# PROJECTION MODEL (UPDATED)
# -------------------------
def project(p, stat):
    try:
        team = p["team"]
        opponent = MATCHUPS.get(team)

        minutes = p["minutes"]
        trend = p["minutes_trend"]

        minute_factor = max(0.85, min(1.25, trend))
        usage_factor = (p["avg_pts"] + p["avg_ast"]) / max(minutes, 1)
        efficiency = 1 + ((p["fg_pct"] - 0.45) * 0.25)

        # Usage spike
        usage_spike = (p["last5_pts"] - p["avg_pts"]) / max(p["avg_pts"], 1)
        usage_boost = 1.08 if usage_spike > 0.10 else 1.04 if usage_spike > 0.05 else 1.0

        # Injury boost
        injury_boost = 1.0
        if team in injuries:
            injury_boost += injuries[team]["BOOST"]

        # TRUE DVP (opponent-based)
        dvp_boost = 1.0
        if opponent in DVP:
            dvp_boost = DVP[opponent].get(stat, 1.0)

        if stat == "Points":
            base = 0.5*p["last5_pts"] + 0.3*p["last10_pts"] + 0.2*p["avg_pts"]
            std = max(p["std_dev"], 1)
            proj = base * minute_factor * efficiency * usage_boost * injury_boost * dvp_boost

        elif stat == "Rebounds":
            base = p["avg_reb"]
            std = max(p["reb_std"], 1)
            proj = base * minute_factor * injury_boost * dvp_boost

        elif stat == "Assists":
            base = p["avg_ast"]
            std = max(p["ast_std"], 1)
            proj = base * usage_factor * usage_boost * injury_boost * dvp_boost

        else:
            return None, None

        return proj, std

    except:
        return None, None

# -------------------------
# BUILD PROJECTIONS
# -------------------------
rows = []
for _, p in player_data.iterrows():
    for stat in ["Points","Rebounds","Assists"]:
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
# LOAD ODDS
# -------------------------
@st.cache_data(ttl=1800)
def load_odds():
    rows = []

    events = requests.get(
        "https://api.the-odds-api.com/v4/sports/basketball_nba/events",
        params={"apiKey": ODDS_API_KEY},
        timeout=10
    ).json()

    for event in events[:MAX_GAMES]:
        event_id = event.get("id")

        res = requests.get(
            f"https://api.the-odds-api.com/v4/sports/basketball_nba/events/{event_id}/odds",
            params={
                "apiKey": ODDS_API_KEY,
                "regions": "us",
                "markets": "player_points,player_rebounds,player_assists"
            },
            timeout=10
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
                        "line": float(o["point"]),
                        "book": book["key"]
                    })

    return pd.DataFrame(rows)

# -------------------------
# BUTTON
# -------------------------
if st.button("🔄 Load Odds"):
    st.session_state.odds_data = load_odds()

odds_df = st.session_state.odds_data

# -------------------------
# MERGE + EDGE
# -------------------------
if not odds_df.empty:
    best = odds_df.sort_values("line").groupby(["clean_name","stat"]).first().reset_index()
    best = best.rename(columns={"line":"best_line"})

    merged = proj_df.merge(best, on=["clean_name","stat"])

    merged["edge"] = merged.apply(
        lambda r: (1 - norm.cdf(r["best_line"], r["projection"], r["std"])) - IMPLIED_PROB,
        axis=1
    )

    merged = merged[merged["edge"] > 0.005]
    merged = merged.sort_values("edge", ascending=False)

    st.write("Props found:", len(merged))

    st.dataframe(
        merged[["player","stat","best_line","projection","edge"]].head(25),
        use_container_width=True
    )
else:
    st.info("Click Load Odds")
