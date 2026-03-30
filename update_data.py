import pandas as pd
from nba_api.stats.endpoints import leaguedashplayerstats

df = leaguedashplayerstats.LeagueDashPlayerStats(
    season='2025-26',
    per_mode_detailed='PerGame'
).get_data_frames()[0]

players = []

for _, p in df.iterrows():
    players.append({
        "player": p["PLAYER_NAME"],
        "team": p["TEAM_ABBREVIATION"],
        "position": "SG",
        "minutes": p["MIN"],
        "minutes_trend": 1.0,
        "avg_pts": p["PTS"],
        "avg_reb": p["REB"],
        "avg_ast": p["AST"],
        "last5_pts": p["PTS"],
        "last10_pts": p["PTS"],
        "fg_pct": p["FG_PCT"],
        "std_dev": max(p["PTS"] * 0.25, 1),
        "reb_std": max(p["REB"] * 0.3, 1),
        "ast_std": max(p["AST"] * 0.3, 1),
    })

pd.DataFrame(players).to_csv("data/player_stats.csv", index=False)
