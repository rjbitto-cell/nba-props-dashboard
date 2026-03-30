import pandas as pd
import time
from nba_api.stats.endpoints import (
    leaguedashplayerstats,
    playergamelog,
    scoreboardv2
)

print("🚀 Updating NBA data pipeline...")

# -------------------------
# GET TODAY'S MATCHUPS
# -------------------------
print("📅 Fetching today's games...")

games = scoreboardv2.ScoreboardV2().get_data_frames()[0]

matchup_map = {}

for _, game in games.iterrows():
    home = game["HOME_TEAM_ABBREVIATION"]
    away = game["VISITOR_TEAM_ABBREVIATION"]

    matchup_map[home] = away
    matchup_map[away] = home

# -------------------------
# GET PLAYER STATS
# -------------------------
print("📊 Fetching player stats...")

season_df = leaguedashplayerstats.LeagueDashPlayerStats(
    season='2025-26',
    per_mode_detailed='PerGame'
).get_data_frames()[0]

players = []
matchups = []

# -------------------------
# SIMPLE INJURY LIST (MANUAL FOR NOW)
# -------------------------
# 👉 You can update this daily if needed
injured_players = [
    # Example:
    # "LeBron James",
]

# -------------------------
# PROCESS PLAYERS
# -------------------------
print("⚙️ Processing players...")

for _, p in season_df.head(40).iterrows():  # keep fast
    try:
        player_id = p["PLAYER_ID"]
        name = p["PLAYER_NAME"]
        team = p["TEAM_ABBREVIATION"]

        print(f"Processing {name}...")

        # -------------------------
        # GAME LOGS
        # -------------------------
        gamelog = playergamelog.PlayerGameLog(
            player_id=player_id,
            season='2025-26'
        ).get_data_frames()[0]

        last5 = gamelog.head(5)
        last10 = gamelog.head(10)

        last5_pts = last5["PTS"].mean() if not last5.empty else p["PTS"]
        last10_pts = last10["PTS"].mean() if not last10.empty else p["PTS"]

        # -------------------------
        # MATCHUP
        # -------------------------
        opponent = matchup_map.get(team, None)

        if opponent:
            matchups.append({
                "player": name,
                "opponent": opponent
            })

        # -------------------------
        # INJURY BOOST (simple)
        # -------------------------
        usage_boost = 1.0

        # if teammate injured → boost (basic logic)
        if name not in injured_players:
            # simulate: if ANY teammate injured → small boost
            usage_boost = 1.05

        # -------------------------
        # BUILD PLAYER ROW
        # -------------------------
        players.append({
            "player": name,
            "team": team,
            "position": "SG",
            "minutes": p["MIN"],
            "minutes_trend": 1.0,
            "avg_pts": p["PTS"] * usage_boost,
            "avg_reb": p["REB"],
            "avg_ast": p["AST"],
            "last5_pts": round(last5_pts * usage_boost, 1),
            "last10_pts": round(last10_pts * usage_boost, 1),
            "fg_pct": p["FG_PCT"],
            "std_dev": max(p["PTS"] * 0.25, 1),
            "reb_std": max(p["REB"] * 0.3, 1),
            "ast_std": max(p["AST"] * 0.3, 1),
        })

        time.sleep(0.6)

    except Exception as e:
        print(f"Skipping {name}: {e}")
        continue

# -------------------------
# SAVE FILES
# -------------------------
print("💾 Saving CSV files...")

player_df = pd.DataFrame(players)
matchup_df = pd.DataFrame(matchups)

# fallback if no games today
if matchup_df.empty:
    matchup_df = pd.DataFrame({
        "player": player_df["player"],
        "opponent": "UNK"
    })

player_df.to_csv("data/player_stats.csv", index=False)
matchup_df.to_csv("data/matchups.csv", index=False)

print("✅ player_stats.csv updated")
print("✅ matchups.csv updated")
print("🎯 Pipeline complete")
