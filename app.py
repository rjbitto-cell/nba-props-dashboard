import streamlit as st
import pandas as pd
import numpy as np
import requests

@st.cache_data
def load_player_data():
    return pd.read_csv("data/player_stats.csv")

@st.cache_data
def load_defense_data():
    return pd.read_csv("data/team_defense.csv")

@st.cache_data
def load_matchups():
    return pd.read_csv("data/matchups.csv")

st.set_page_config(page_title="NBA Props Dashboard", layout="wide")

st.title("🏀 NBA Props Dashboard")

# -----------------------------------
# LOAD DATA (API or fallback)
# -----------------------------------
@st.cache_data(ttl=60)
def load_props():
    API_KEY = st.secrets.get("ODDS_API_KEY", "")

    # If no API key → fallback data
    if not API_KEY:
        return pd.DataFrame({
            "player": ["LeBron James", "Stephen Curry", "Nikola Jokic"],
            "stat": ["Points", "Points", "Rebounds"],
            "line": [27.5, 29.5, 11.5],
            "odds": [-110, -105, -120]
        })

    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"

    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": "player_points"
    }

    res = requests.get(url, params=params).json()

    rows = []
    for game in res:
        for book in game['bookmakers']:
            for market in book['markets']:
                for o in market['outcomes']:
                    rows.append({
                        "player": o['description'],
                        "stat": market['key'],
                        "line": o.get('point', 0),
                        "odds": o['price']
                    })

    return pd.DataFrame(rows)

df = load_props()

# -----------------------------------
# SIMPLE PROJECTION MODEL (TEMP)
# -----------------------------------
from nba_api.stats.endpoints import playergamelog
from nba_api.stats.static import players
from scipy.stats import norm

@st.cache_data(ttl=3600)
def get_player_logs(player_name):
    try:
        player_id = players.find_players_by_full_name(player_name)[0]['id']
        logs = playergamelog.PlayerGameLog(player_id=player_id)
        df = logs.get_data_frames()[0]
        return df
    except:
        return None


from nba_api.stats.endpoints import playergamelog, leaguedashteamstats
from nba_api.stats.static import players
from scipy.stats import norm
import pandas as pd
import numpy as np

@st.cache_data(ttl=3600)
def get_player_logs(player_name):
    try:
        player_id = players.find_players_by_full_name(player_name)[0]['id']
        logs = playergamelog.PlayerGameLog(player_id=player_id)
        df = logs.get_data_frames()[0]
        return df
    except:
        return None


@st.cache_data(ttl=3600)
def get_team_defense():
    stats = leaguedashteamstats.LeagueDashTeamStats()
    df = stats.get_data_frames()[0]
    return df[['TEAM_NAME', 'DEF_RATING']]


def extract_opponent(matchup):
    try:
        return matchup.split("vs. ")[-1] if "vs." in matchup else matchup.split("@ ")[-1]
    except:
        return None


from scipy.stats import norm
import numpy as np

player_data = load_player_data()
defense_data = load_defense_data()
matchups = load_matchups()

def calculate_edge(row):
    try:
        # ------------------------
        # 🧠 PLAYER DATA
        # ------------------------
        pdata = player_data[player_data['player'] == row['player']]

        if pdata.empty:
            return row['line'], 0

        pdata = pdata.iloc[0]

        projection = (
            0.4 * pdata['last5_pts'] +
            0.4 * pdata['last10_pts'] +
            0.2 * pdata['avg_pts']
        )

        # ------------------------
        # 🔥 MATCHUP (REAL)
        # ------------------------
        match = matchups[matchups['player'] == row['player']]

        if not match.empty:
            opponent = match.iloc[0]['opponent']
        else:
            opponent = None

        # ------------------------
        # 🛡️ DEFENSE ADJUSTMENT
        # ------------------------
        def_row = defense_data[defense_data['team'] == opponent]

        if not def_row.empty:
            def_rating = def_row.iloc[0]['def_rating']
            league_avg = defense_data['def_rating'].mean()

            matchup_boost = league_avg / def_rating
            projection *= matchup_boost

        # ------------------------
        # 📊 VOLATILITY
        # ------------------------
        std = pdata['std_dev']

        # ------------------------
        # 💰 EDGE CALC
        # ------------------------
        prob = 1 - norm.cdf(row['line'], projection, std)

        odds = row.get('odds', -110)
        if odds > 0:
            implied = 100 / (odds + 100)
        else:
            implied = -odds / (-odds + 100)

        edge = prob - implied

        return projection, edge

    except:
        return row['line'], 0

df[['projection', 'edge']] = df.apply(
    lambda row: pd.Series(calculate_edge(row)),
    axis=1
)

df = df.sort_values("edge", ascending=False)

# -----------------------------------
# DISPLAY
# -----------------------------------
st.subheader("🔥 Best Bets")

st.dataframe(df, use_container_width=True)

# -----------------------------------
# PLAYER VIEW
# -----------------------------------
player = st.selectbox("Select Player", df["player"].unique())

row = df[df["player"] == player].iloc[0]

col1, col2, col3 = st.columns(3)

col1.metric("Projection", round(row["projection"], 2))
col2.metric("Line", row["line"])
col3.metric("Edge", f"{row['edge']:.2%}")
