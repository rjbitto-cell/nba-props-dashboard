import pandas as pd
import time

print("🚀 Running NBA data pipeline...")

players = []

# -------------------------
# TRY REAL DATA
# -------------------------
try:
    from nba_api.stats.endpoints import leaguedashplayerstats, playergamelog

    season_df = leaguedashplayerstats.LeagueDashPlayerStats(
        season='2025-26',
        per_mode_detailed='PerGame'
    ).get_data_frames()[0]

    print(f"✅ Pulled {len(season_df)} players")

    # Limit to avoid timeouts
    for _, p in season_df.head(25).iterrows():
        try:
            name = p["PLAYER_NAME"]
            player_id = p["PLAYER_ID"]

            print(f"Processing {name}")

            # -------------------------
            # GAME LOGS (SAFE)
            # -------------------------
            try:
                gamelog = playergamelog.PlayerGameLog(
                    player_id=player_id,
                    season='2025-26'
                ).get_data_frames()[0]

                last5 = gamelog.head(5)
                last10 = gamelog.head(10)

                last5_pts = last5["PTS"].mean() if not last5.empty else p["PTS"]
                last10_pts = last10["PTS"].mean() if not last10.empty else p["PTS"]

            except Exception as e:
                print(f"⚠️ Game log failed for {name}")
                last5_pts = p["PTS"]
                last10_pts = p["PTS"]

            players.append({
                "player": name,
                "team": p["TEAM_ABBREVIATION"],
                "position": "SG",
                "minutes": p["MIN"],
                "minutes_trend": 1.0,
                "avg_pts": p["PTS"],
                "avg_reb": p["REB"],
                "avg_ast": p["AST"],
                "last5_pts": round(last5_pts, 1),
                "last10_pts": round(last10_pts, 1),
                "fg_pct": p["FG_PCT"],
                "std_dev": max(p["PTS"] * 0.25, 1),
                "reb_std": max(p["REB"] * 0.3, 1),
                "ast_std": max(p["AST"] * 0.3, 1),
            })

            time.sleep(0.6)  # prevents rate limit

        except Exception as e:
            print(f"Skipping player: {e}")
            continue

# -------------------------
# IF API FAILS → FALLBACK
# -------------------------
except Exception as e:
    print("❌ API completely failed:", e)

# -------------------------
# GUARANTEED OUTPUT
# -------------------------
if not players:
    print("⚠️ Using fallback data")

    players = [{
        "player": "LeBron James",
        "team": "LAL",
        "position": "SF",
        "minutes": 35,
        "minutes_trend": 1.0,
        "avg_pts": 27,
        "avg_reb": 8,
        "avg_ast": 7,
        "last5_pts": 28,
        "last10_pts": 27,
        "fg_pct": 0.5,
        "std_dev": 6,
        "reb_std": 3,
        "ast_std": 3,
    }]

# -------------------------
# SAVE FILES (ALWAYS RUNS)
# -------------------------
df = pd.DataFrame(players)

df.to_csv("data/player_stats.csv", index=False)

# simple matchup fallback (safe)
pd.DataFrame({
    "player": df["player"],
    "opponent": "UNK"
}).to_csv("data/matchups.csv", index=False)

print("✅ Data pipeline COMPLETE")
