import streamlit as st
import pandas as pd
import requests
import time

st.set_page_config(page_title="NBA Sharp Props Tool", layout="wide")

# ==============================
# CONFIG
# ==============================
API_KEY = st.secrets["ODDS_API_KEY"]
REGIONS = "us"
ODDS_FORMAT = "american"
TARGET_BOOKS = ["betmgm", "caesars", "fanduel", "draftkings", "betrivers"]

# ==============================
# HELPERS
# ==============================
def clean_name(name):
    return str(name).lower().replace(".", "").replace("'", "").strip()

# ==============================
# FETCH PROPS (MATCHES YOUR COLAB)
# ==============================
def fetch_props():
    sport = "basketball_nba"
    markets = ["player_points", "player_rebounds", "player_assists"]

    events_url = f"https://api.the-odds-api.com/v4/sports/{sport}/events"
    res = requests.get(events_url, params={"apiKey": API_KEY})
    events = res.json()

    st.write(f"📅 Events: {len(events)}")

    rows = []

    for event in events:
        event_id = event["id"]
        home = event["home_team"]
        away = event["away_team"]

        for market in markets:

            odds_url = f"https://api.the-odds-api.com/v4/sports/{sport}/events/{event_id}/odds"

            params = {
                "apiKey": API_KEY,
                "regions": REGIONS,
                "markets": market,
                "oddsFormat": ODDS_FORMAT
            }

            res = requests.get(odds_url, params=params)

            if res.status_code != 200:
                continue

            data = res.json()

            if "bookmakers" not in data:
                continue

            for book in data["bookmakers"]:
                b_name = book["key"]

                if b_name not in TARGET_BOOKS:
                    continue

                for mkt in book["markets"]:
                    for outcome in mkt["outcomes"]:

                        if outcome["name"] != "Over":
                            continue

                        rows.append({
                            "player": outcome["description"],
                            "clean_name": clean_name(outcome["description"]),
                            "stat": market.replace("player_", ""),
                            "line": outcome.get("point"),
                            "price": outcome.get("price"),
                            "book": b_name,
                            "home_team": home,
                            "away_team": away
                        })

            time.sleep(0.1)

    df = pd.DataFrame(rows)
    st.write(f"📊 Props pulled: {len(df)}")
    return df

# ==============================
# LOAD PLAYER DATA
# ==============================
@st.cache_data
def load_players():
    df = pd.read_csv("data/player_stats.csv")

    df = df.rename(columns={
        "Player": "player",
        "Team": "team",
        "MP": "minutes",
        "PTS": "avg_points",
        "TRB": "avg_rebounds",
        "AST": "avg_assists"
    })

    df["clean_name"] = df["player"].apply(clean_name)
    df["team"] = df["team"].str.upper()

    return df

# ==============================
# PROJECTION MODEL (FIXED + SAFE)
# ==============================
def project(row):
    if pd.isna(row.get("minutes")):
        return None

    stat = row["stat"]
    avg_col = f"avg_{stat}"

    if avg_col not in row:
        return None

    base = row[avg_col]
    mpg = row["minutes"]

    if mpg == 0:
        return None

    per_min = base / mpg
    proj = per_min * min(max(mpg, 24), 36)

    # regression (fix high projections)
    league_avg = {
        "points": 15,
        "rebounds": 5,
        "assists": 4
    }

    proj = proj * 0.7 + league_avg[stat] * 0.3

    return round(proj, 2)

# ==============================
# SHARP ENGINE (KEY PART)
# ==============================
def find_sharp_edges(props, players):
    merged = props.merge(players, on="clean_name", how="left")

    merged["projection"] = merged.apply(project, axis=1)

    sharp_rows = []

    grouped = merged.groupby(["clean_name", "stat"])

    for (player, stat), group in grouped:

        if len(group) < 2:
            continue

        group = group.dropna(subset=["line", "projection"])

        if len(group) < 2:
            continue

        min_line = group["line"].min()
        max_line = group["line"].max()

        # 🔥 LINE SNIPE CONDITION
        if (max_line - min_line) >= 1:

            best_row = group[group["line"] == min_line].iloc[0]

            projection = best_row["projection"]

            # 🔥 PROJECTION CONFIRMATION
            if projection > min_line:

                sharp_rows.append({
                    "player": best_row["player"],
                    "stat": stat,
                    "line": min_line,
                    "projection": projection,
                    "edge": round(max_line - min_line, 2),
                    "book": best_row["book"],
                    "type": "LINE + MODEL CONFIRMED"
                })

    return pd.DataFrame(sharp_rows)

# ==============================
# APP
# ==============================
st.title("🏀 NBA Sharp Props Tool")

if "props" not in st.session_state:
    st.session_state["props"] = None

if st.button("🚀 Fetch Props"):
    st.session_state["props"] = fetch_props()

props = st.session_state["props"]

if props is None or props.empty:
    st.warning("Click fetch to load props")
    st.stop()

players = load_players()

# ==============================
# SHARP RESULTS
# ==============================
sharp = find_sharp_edges(props, players)

st.subheader("🔥 Sharp Bets (Line + Model)")

if sharp.empty:
    st.write("No sharp bets right now")
else:
    st.dataframe(
        sharp.sort_values("edge", ascending=False),
        use_container_width=True
    )

# ==============================
# DEBUG VIEW (OPTIONAL)
# ==============================
with st.expander("📊 Raw Props (debug)"):
    st.dataframe(props.head(100))
