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
def calculate_edge(row):
    projection = row['line'] + np.random.uniform(-3, 5)
    edge = (projection - row['line']) / row['line']
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
