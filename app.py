import streamlit as st
import pandas as pd
import numpy as np
import requests

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


def calculate_edge(row):
    logs = get_player_logs(row['player'])

    if logs is None or len(logs) < 5:
        return row['line'], 0

    # Convert to numeric
    logs['PTS'] = pd.to_numeric(logs['PTS'])

    # Features
    last5 = logs.head(5)['PTS'].mean()
    last10 = logs.head(10)['PTS'].mean()
    std = logs['PTS'].std()

    usage = logs['FGA'].mean() + 0.44 * logs['FTA'].mean()

    # Projection formula (weighted)
    projection = (
        0.5 * last5 +
        0.3 * last10 +
        0.2 * (usage / 2)
    )

    # Probability of hitting OVER
    prob = 1 - norm.cdf(row['line'], projection, std)

    # Convert odds to implied probability
    odds = row.get('odds', -110)
    if odds > 0:
        implied = 100 / (odds + 100)
    else:
        implied = -odds / (-odds + 100)

    edge = prob - implied

    return projection, edge

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
