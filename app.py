import streamlit as st
import pandas as pd

st.set_page_config(page_title="NBA Props Dashboard", layout="wide")

st.title("🏀 NBA Props Dashboard")

# Sample data (we'll replace with real data later)
data = {
    "player": ["LeBron James", "Stephen Curry", "Nikola Jokic"],
    "stat": ["Points", "Points", "Rebounds"],
    "line": [27.5, 29.5, 11.5],
    "projection": [29.8, 31.2, 12.7],
    "edge": [0.08, 0.06, 0.07]
}

df = pd.DataFrame(data)

st.subheader("🔥 Best Bets")

st.dataframe(df, use_container_width=True)

player = st.selectbox("Select Player", df["player"])

row = df[df["player"] == player].iloc[0]

st.metric("Projection", row["projection"])
st.metric("Line", row["line"])
st.metric("Edge", f"{row['edge']:.2%}")
