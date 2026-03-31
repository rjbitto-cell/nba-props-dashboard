import streamlit as st
import pandas as pd
import requests
import time

st.title("🏀 NBA Props Debug Tool")

API_KEY = st.secrets["ODDS_API_KEY"]

# ==============================
# HELPERS
# ==============================
def clean_name(name):
    return str(name).lower().replace(".", "").strip()

# ==============================
# FETCH PROPS (DEBUG SAFE)
# ==============================
def fetch_props():
    events_url = "https://api.the-odds-api.com/v4/sports/basketball_nba/events"

    events_res = requests.get(events_url, params={"apiKey": API_KEY})

    if events_res.status_code != 200:
        st.error(f"Events error: {events_res.status_code}")
        return pd.DataFrame()

    events = events_res.json()
    st.write(f"📅 Events found: {len(events)}")

    rows = []

    for event in events:
        event_id = event["id"]

        odds_url = f"https://api.the-odds-api.com/v4/sports/basketball_nba/events/{event_id}/odds"

        params = {
            "apiKey": API_KEY,
            "regions": "us",
            "markets": "player_points,player_rebounds,player_assists"
        }

        res = requests.get(odds_url, params=params)

        if res.status_code != 200:
            continue

        data = res.json()

        for book in data.get("bookmakers", []):
            for market in book.get("markets", []):

                stat_map = {
                    "player_points": "pts",
                    "player_rebounds": "reb",
                    "player_assists": "ast"
                }

                stat = stat_map.get(market["key"])
                if not stat:
                    continue

                for o in market.get("outcomes", []):
                    rows.append({
                        "player": o.get("description"),
                        "clean_name": clean_name(o.get("description")),
                        "stat": stat,
                        "line": o.get("point"),
                        "book": book["key"]
                    })

        time.sleep(0.2)

    df = pd.DataFrame(rows)
    st.write(f"📊 Props pulled: {len(df)}")
    return df

# ==============================
# LOAD PLAYERS
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

    return df

# ==============================
# RUN APP
# ==============================
if st.button("🚀 Fetch Props"):
    props = fetch_props()

    if props.empty:
        st.error("❌ No props returned from API")
        st.stop()

    st.subheader("📊 RAW PROPS (API WORKING CHECK)")
    st.dataframe(props.head(50))

    players = load_players()

    # 🔥 KEY FIX: LEFT JOIN (DO NOT LOSE DATA)
    merged = props.merge(players, on="clean_name", how="left")

    st.write(f"After merge: {len(merged)} rows")

    # show unmatched players
    missing = merged[merged["team"].isna()]
    st.write(f"❌ Unmatched players: {len(missing)}")

    st.subheader("🧪 SAMPLE MERGED DATA")
    st.dataframe(merged.head(50))
