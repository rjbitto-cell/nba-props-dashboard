import streamlit as st
import pandas as pd
import numpy as np
from scipy.stats import norm
from nba_api.stats.endpoints import playergamelog, commonteamroster, leaguedashplayerstats
from nba_api.stats.static import players, teams
import datetime

st.set_page_config(page_title="NBA Props Dashboard (Live)", layout="wide")
st.title("🏀 NBA Props Dashboard (Live)")

# -------------------------
# CONFIG
# -------------------------
POSITION_LIST = ["PG", "SG", "SF", "PF", "C"]
EDGE_MULTIPLIER = 1.15
IMPLIED_PROB = 0.524  # baseline implied probability for -110 odds

# -------------------------
# HELPER FUNCTIONS
# -------------------------
def get_player_id(name):
    """Get NBA API player ID"""
    p = players.find_players_by_full_name(name)
    return p[0]['id'] if p else None

def get_recent_games(player_id, season='2025-26', last_n=10):
    """Fetch last N games for player"""
    gl = playergamelog.PlayerGameLog(player_id=player_id, season=season).get_data_frames()[0]
    return gl.head(last_n)

def get_season_avg(player_id, season='2025-26'):
    """Get season averages for a player"""
    gl = playergamelog.PlayerGameLog(player_id=player_id, season=season).get_data_frames()[0]
    if gl.empty:
        return None
    return gl.mean(numeric_only=True)

def get_team_defense():
    """Simplified team defense vs position (mock example)"""
    # In a real version, pull advanced stats from nba_api / team box scores
    return pd.DataFrame({
        "team": ["LAL","GSW","BKN","MIA"],
        "position": ["PG","SG","SF","PF"],
        "def_rating": [105, 102, 108, 103]
    })

def get_injury_list():
    """Simplified injuries (for example purposes)"""
    return {"LeBron James": True, "Stephen Curry": False}  # True = out

def normalize_name(name):
    return str(name).lower().replace(".", "").strip()

# -------------------------
# LOAD DATA
# -------------------------
st.subheader("Fetching live player data...")
all_players = players.get_active_players()

team_defense = get_team_defense()
injuries = get_injury_list()

# -------------------------
# BUILD PROJECTION + EDGE
# -------------------------
rows = []
for p in all_players:
    try:
        player_id = p['id']
        name = p['full_name']
        clean_name = normalize_name(name)

        # -------------------------
        # FETCH STATS
        # -------------------------
        last5 = get_recent_games(player_id, last_n=5)
        last10 = get_recent_games(player_id, last_n=10)
        season_avg = get_season_avg(player_id)

        if last5.empty or season_avg is None:
            continue

        minutes = season_avg['MIN'] if season_avg['MIN'] > 0 else 25
        points_avg = (0.4*last5['PTS'].mean() + 0.4*last10['PTS'].mean() + 0.2*season_avg['PTS'])
        rebounds_avg = (0.4*last5['REB'].mean() + 0.4*last10['REB'].mean() + 0.2*season_avg['REB'])
        assists_avg = (0.4*last5['AST'].mean() + 0.4*last10['AST'].mean() + 0.2*season_avg['AST'])

        # minutes trend spike
        minutes_trend = last5['MIN'].mean() / max(season_avg['MIN'],1)

        # adjust for injuries (simplified)
        injury_adj = 1.0
        if injuries.get(name, False):
            injury_adj = 0  # player out → projection zero
        else:
            # could boost teammates if a teammate is out, simplified here
            injury_adj = 1.0

        # DvP adjustment vs opponent/position
        # simplified: pick a random position and match to team_defense table
        opponent_def = team_defense.sample(1).iloc[0]
        def_rating = opponent_def['def_rating']
        league_avg_def = team_defense['def_rating'].mean()
        dvp_adj = league_avg_def / def_rating

        # -------------------------
        # FINAL PROJECTIONS
        # -------------------------
        proj_points = points_avg * minutes_trend * dvp_adj * injury_adj * EDGE_MULTIPLIER
        proj_rebounds = rebounds_avg * minutes_trend * dvp_adj * injury_adj * EDGE_MULTIPLIER
        proj_assists = assists_avg * minutes_trend * dvp_adj * injury_adj * EDGE_MULTIPLIER

        # -------------------------
        # USE PRIZEPICKS LINE (example placeholder)
        # -------------------------
        line_points = proj_points * 0.95  # placeholder line, replace with real feed
        line_rebounds = proj_rebounds * 0.95
        line_assists = proj_assists * 0.95

        # -------------------------
        # EDGE CALCULATION
        # -------------------------
        std_pts = max(last10['PTS'].std(), 1)
        prob_pts = 1 - norm.cdf(line_points, proj_points, std_pts)
        edge_pts = prob_pts - IMPLIED_PROB

        std_reb = max(last10['REB'].std(), 1)
        prob_reb = 1 - norm.cdf(line_rebounds, proj_rebounds, std_reb)
        edge_reb = prob_reb - IMPLIED_PROB

        std_ast = max(last10['AST'].std(), 1)
        prob_ast = 1 - norm.cdf(line_assists, proj_assists, std_ast)
        edge_ast = prob_ast - IMPLIED_PROB

        # append rows
        rows.append({"player": name, "stat": "Points", "projection": proj_points, "line": line_points, "edge": edge_pts})
        rows.append({"player": name, "stat": "Rebounds", "projection": proj_rebounds, "line": line_rebounds, "edge": edge_reb})
        rows.append({"player": name, "stat": "Assists", "projection": proj_assists, "line": line_assists, "edge": edge_ast})

    except:
        continue

# -------------------------
# BUILD DATAFRAME
# -------------------------
df = pd.DataFrame(rows)
df = df.sort_values(by="edge", ascending=False)

# -------------------------
# UI
# -------------------------
st.subheader("🔥 Top 25 Edge Bets")
st.dataframe(df.head(25), use_container_width=True)

player = st.selectbox("Select Player", df["player"].unique())
row = df[df["player"] == player].iloc[0]

st.metric("Projection", round(row["projection"],2))
st.metric("Line", round(row["line"],2))
st.metric("Edge", f"{round(row['edge']*100,2)}%")
