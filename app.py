import streamlit as st
import requests
import pandas as pd
import os

st.set_page_config(page_title="Sharp NBA Props", layout="wide")

# =========================
# CONFIG
# =========================
API_KEY = os.getenv("ODDS_API_KEY")
SPORT = "basketball_nba"
REGIONS = "us"
MARKETS = "player_points,player_rebounds,player_assists"
BOOKS = ["betmgm","fanduel","draftkings","betrivers","caesars"]

# =========================
# PROJECTIONS (REALISTIC)
# =========================
player_stats = pd.read_csv("data/player_stats.csv")

def get_projection(player, stat):
    row = player_stats[player_stats["player"] == player]
    if row.empty:
        return None

    if stat == "player_points":
        return float(row["pts"].values[0])
    if stat == "player_rebounds":
        return float(row["trb"].values[0])
    if stat == "player_assists":
        return float(row["ast"].values[0])

    return None

# =========================
# FETCH EVENTS (CACHED)
# =========================
@st.cache_data(ttl=300)
def get_events():
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/events"
    r = requests.get(url, params={"apiKey": API_KEY})

    if r.status_code != 200:
        return []

    return r.json()

# =========================
# FETCH ODDS (CACHED)
# =========================
@st.cache_data(ttl=300)
def get_odds(event_id):
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/events/{event_id}/odds"

    r = requests.get(url, params={
        "apiKey": API_KEY,
        "regions": REGIONS,
        "markets": MARKETS,
        "oddsFormat": "american"
    })

    if r.status_code == 401:
        st.error("❌ API KEY INVALID (401)")
        return None

    if r.status_code == 429:
        st.warning("⚠️ Rate limited (429) — slow down API calls")
        return None

    if r.status_code != 200:
        return None

    return r.json()

# =========================
# UI
# =========================
st.title("🏀 Sharp NBA Props Tool")

if st.button("🚀 Find Sharp Props"):
    events = get_events()
    st.write(f"📅 Events: {len(events)}")

    sharp_props = []

    for event in events:
        odds = get_odds(event["id"])
        if not odds or "bookmakers" not in odds:
            continue

        results = {}

        for book in odds["bookmakers"]:
            if book["key"] not in BOOKS:
                continue

            for market in book["markets"]:
                stat = market["key"]

                for outcome in market["outcomes"]:
                    player = outcome["description"]
                    side = outcome["name"]
                    line = outcome.get("point")
                    price = outcome["price"]

                    if not player or line is None:
                        continue

                    results.setdefault(player, {}).setdefault(stat, {}).setdefault(book["key"], {})
                    results[player][stat][book["key"]][side] = {
                        "line": line,
                        "price": price
                    }

        # =========================
        # SHARP DETECTION
        # =========================
        for player, stats in results.items():
            for stat, books in stats.items():

                overs = []
                for b in books:
                    if "Over" in books[b]:
                        overs.append((b,
                                      books[b]["Over"]["line"],
                                      books[b]["Over"]["price"]))

                if len(overs) < 2:
                    continue

                lines = [o[1] for o in overs]
                min_line = min(lines)
                max_line = max(lines)

                projection = get_projection(player, stat)
                if projection is None:
                    continue

                edge = projection - min_line

                # 🎯 SHARP FILTERS
                if (max_line - min_line >= 1.0) or (edge >= 3):

                    best_book = [o[0] for o in overs if o[1] == min_line][0]

                    sharp_props.append({
                        "player": player,
                        "stat": stat,
                        "line": min_line,
                        "projection": round(projection, 2),
                        "edge": round(edge, 2),
                        "book": best_book,
                        "line_gap": round(max_line - min_line, 2)
                    })

    if sharp_props:
        df = pd.DataFrame(sharp_props).sort_values(by="edge", ascending=False)
        st.dataframe(df.head(25))
    else:
        st.warning("No sharp props found")
