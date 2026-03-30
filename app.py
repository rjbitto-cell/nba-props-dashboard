import streamlit as st
import pandas as pd
import numpy as np
import requests
from scipy.stats import norm

st.set_page_config(page_title="NBA Props Dashboard", layout="wide")
st.title("🏀 NBA Props Dashboard")

# -------------------------
# LOAD STATIC DATA
# -------------------------
@st.cache_data
def load_player_data():
    return pd.read_csv("data/player_stats.csv")

@st.cache_data
def load_defense_data():
    return pd.read_csv("data/team_defense.csv")

@st.cache_data
def load_matchups():
    return pd.read_csv("data/matchups.csv")

player_data = load_player_data()
defense_data = load_defense_data()
matchups = load_matchups()

# -------------------------
# LOAD PROPS (REAL API)
# -------------------------
@st.cache_data(ttl=300)
def load_props():
    try:
        API_KEY = st.secrets.get("ODDS_API_KEY", "")

        if not API_KEY:
            st.warning("No API key — using sample data")
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

        res = requests.get(url, params=params, timeout=10).json()

        rows = []

        for game in res:
            for book in game.get("bookmakers", []):
                for market in book.get("markets", []):
                    if market.get("key") != "player_points":
                        continue

                    for o in market.get("outcomes", []):
                        rows.append({
                            "player": o.get("description"),
                            "line": o.get("point"),
                            "odds": o.get("price"),
                            "stat": "Points"
                        })

        df = pd.DataFrame(rows)

        if df.empty:
            st.warning("No props returned from API")

        return df

    except:
        st.error("API failed — using fallback")
        return pd.DataFrame()

df = load_props()

# -------------------------
# EDGE MODEL
# -------------------------
def calculate_edge(row):
    try:
        pdata = player_data[player_data['player'] == row['player']]

        if pdata.empty:
            return row['line'], 0

        pdata = pdata.iloc[0]

        # Base projection
        base = (
            0.4 * pdata['last5_pts'] +
            0.4 * pdata['last10_pts'] +
            0.2 * pdata['avg_pts']
        )

        # Minutes model
        minutes = pdata['minutes']
        trend = pdata['minutes_trend']
        adj_minutes = minutes * trend

        ppm = base / minutes
        projection = ppm * adj_minutes

        # Matchup
        match = matchups[matchups['player'] == row['player']]
        opponent = match.iloc[0]['opponent'] if not match.empty else None

        # DvP
        def_row = defense_data[
            (defense_data['team'] == opponent) &
            (defense_data['position'] == pdata['position'])
        ]

        if not def_row.empty:
            def_rating = def_row.iloc[0]['def_rating']
            league_avg = defense_data['def_rating'].mean()
            projection *= (league_avg / def_rating)

        # Variance
        std = pdata['std_dev']

        # Edge
        edge_multiplier = 1.15
        adj_projection = projection * edge_multiplier

        prob = 1 - norm.cdf(row['line'], adj_projection, std)

        odds = row.get('odds', -110)
        implied = (100 / (odds + 100)) if odds > 0 else (-odds / (-odds + 100))

        edge = prob - implied

        return projection, edge

    except:
        return row['line'], 0

# -------------------------
# APPLY MODEL
# -------------------------
if not df.empty:
    df[['projection', 'edge']] = df.apply(
        lambda row: pd.Series(calculate_edge(row)), axis=1
    )

    df = df.sort_values(by='edge', ascending=False)

# -------------------------
# UI
# -------------------------
st.subheader("🔥 Best Bets")

if not df.empty:
    st.dataframe(df.head(15), use_container_width=True)

    player = st.selectbox("Select Player", df['player'].unique())
    row = df[df['player'] == player].iloc[0]

    st.metric("Projection", round(row['projection'], 2))
    st.metric("Line", row['line'])
    st.metric("Edge", f"{round(row['edge']*100,2)}%")

else:
    st.warning("No data available")
