# M3.3 - the ranked "quiet boom" table.
#
# Joins the two screens:
#
#   boom_score     (3.1) how much faster an industry is growing than it normally
#                        does, confirmed by margin expansion and capex, and gated on
#                        the growth being broad-based rather than a few acquisitions
#   ai_correlation (3.2) how closely its shares move with the AI trade, after the
#                        market's own movement is subtracted out
#
# A quiet boom is high on the first and low on the second. Both are z-scored so they
# share a scale, then the AI term is SUBTRACTED: correlating with the AI trade counts
# against an industry here, because the premise of the project is finding growth the
# market has not already attached a story to.
#
# Importing boom_score and quiet_filter re-runs both computations; neither prints
# unless run directly.
#
# Reads data/db/screener.db (via those two modules). Prints the ranked table.

import sys
from pathlib import Path

import pandas as pd

# Allow this to be run from anywhere, not just from inside src/.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import boom_score
import quiet_filter

Z_CLIP = 3.0
AI_WEIGHT = 1.0      # how much a loud AI narrative counts against an industry
MIN_ACCELERATION = 0.0  # an industry must actually be accelerating to qualify
MIN_READABLE = 5     # industries needing this many readable Item 1 sections to score

# Written by ai_keywords.py, which is slow (it fetches 903 annual reports) and so is
# run as a separate step. Its absence is tolerated: the ranking then rests on the
# market-correlation screen alone.
KEYWORDS_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "ai_keywords.parquet"


def zscore(series):
    """Standard deviations from the mean of all industries, with outliers capped."""
    return ((series - series.mean()) / series.std()).clip(-Z_CLIP, Z_CLIP)


boom = boom_score.scores
quiet = quiet_filter.per_industry

# Inner join: an industry needs both a boom score and a correlation to be ranked.
# The two screens apply different minimum-company rules, so some drop out here.
combined = boom.join(quiet[["ai_correlation"]], how="inner")

# Second, independent measure of loudness: how much the industry's own filings talk
# about AI. The two disagree often enough to be worth having both - the market can
# price an AI story a company never tells (industrial "picks and shovels" names), and
# a company can tell one the market does not buy (IT consultancies).
if KEYWORDS_PATH.exists():
    keywords = pd.read_parquet(KEYWORDS_PATH).dropna(subset=["ai_per_1k_words"])
    talk = (
        keywords.groupby("sub_industry")
        .agg(readable=("cik", "nunique"), ai_talk=("ai_per_1k_words", "median"))
    )
    talk = talk[talk["readable"] >= MIN_READABLE]
    combined = combined.join(talk[["ai_talk"]], how="left")
else:
    combined["ai_talk"] = pd.NA

# Being quiet is a filter on real growth, not a merit in itself. Without this gate,
# subtracting the AI z-score lets a decelerating but unfashionable industry rank
# high purely for being ignored - Packaged Foods & Meats placed 10th on accel -3.4.
combined = combined[combined["acceleration"] > MIN_ACCELERATION]

combined["z_boom"] = zscore(combined["boom_score"])
combined["z_ai_correlation"] = zscore(combined["ai_correlation"])
combined["z_ai_talk"] = zscore(combined["ai_talk"].astype(float))

# Average the two loudness measures where both exist, and fall back to whichever is
# available otherwise. An industry with no readable filings is not treated as quiet.
combined["z_ai"] = combined[["z_ai_correlation", "z_ai_talk"]].mean(axis=1)

combined["quiet_boom"] = combined["z_boom"] - AI_WEIGHT * combined["z_ai"]

combined = combined.sort_values("quiet_boom", ascending=False)

show = combined[["companies", "quiet_boom", "boom_score", "ai_correlation",
                 "ai_talk", "acceleration", "breadth", "capex_change"]].round(2)
show.columns = ["n", "quiet_boom", "boom", "ai_corr", "ai_talk", "accel",
                "breadth", "capex_chg"]

if __name__ == "__main__":
    pd.set_option("display.width", 160)
    print(f"{len(combined)} industries ranked\n")
    print("TOP - growing faster than usual, and NOT priced as an AI story")
    print(show.head(15).to_string())
    print("\nBOTTOM - either not accelerating, or already a loud AI trade")
    print(show.tail(10).to_string())
