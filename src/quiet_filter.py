# M3.2 (part 1) - measure how much each industry moves with the AI trade.
#
# The boom score finds industries growing faster than they normally do. It cannot
# tell whether the market has already attached an AI story to them - and utilities,
# construction and electrical equipment all rank highly for reasons that may be
# entirely about data centres.
#
# The market answers this itself. If investors think an industry is an AI play, its
# shares move when the AI trade moves. So:
#
#   ai_factor   = average return of a hand-picked AI basket
#                 MINUS the average return of the whole universe
#   correlation = each company's daily return against that factor
#
# Subtracting the market return is the important part. Almost everything correlates
# with the AI basket's raw return, because almost everything correlates with the
# market. The difference isolates the part that is specifically the AI trade.
#
# Reads data/db/screener.db. Prints industries ranked from quietest to loudest.

import sqlite3
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "db" / "screener.db"

# The window over which "the AI trade" is a meaningful thing to measure.
FROM_DATE = "2024-01-01"

# Minimum trading days before a company's correlation is trusted.
MIN_DAYS = 200

# Hand-picked names whose share prices are unambiguously driven by the AI narrative:
# the chip makers and their equipment suppliers, the hyperscalers, and the hardware
# and power kit that data centres are built from. Chosen by narrative, not by sector,
# so that the screen is not merely rediscovering GICS classifications.
AI_BASKET = [
    "NVDA", "AVGO", "AMD", "MU", "MRVL",          # chips
    "AMAT", "LRCX", "KLAC",                        # chip equipment
    "MSFT", "GOOGL", "META", "ORCL", "PLTR",       # hyperscalers and AI software
    "ANET", "CIEN", "COHR",                        # networking and optics
    "DELL", "SMCI", "VRT",                         # servers and data centre power
]

connection = sqlite3.connect(DB_PATH)
prices = pd.read_sql_query(
    "SELECT ticker, date, close FROM prices WHERE date >= ? ORDER BY ticker, date",
    connection,
    params=(FROM_DATE,),
)
industries = pd.read_sql_query(
    "SELECT ticker, sub_industry, cik FROM companies", connection
)
connection.close()

# One column per ticker, one row per trading day, values = daily percentage return.
wide = prices.pivot(index="date", columns="ticker", values="close").sort_index()
returns = wide.pct_change()

# Drop any ticker without enough history to give a stable correlation.
usable = returns.columns[returns.notna().sum() >= MIN_DAYS]
returns = returns[usable]

present = [t for t in AI_BASKET if t in returns.columns]
missing = sorted(set(AI_BASKET) - set(present))
if missing:
    print(f"note: AI basket names absent from the price data: {missing}")

# Equal weighting, not market-cap weighting: otherwise the factor would be Nvidia.
basket_return = returns[present].mean(axis=1)
market_return = returns.mean(axis=1)
ai_factor = basket_return - market_return

# corrwith aligns on the shared dates and ignores missing values pairwise.
correlation = returns.corrwith(ai_factor).rename("ai_correlation")

# One row per company, then the median company per industry. Median again, for the
# same reason as the boom score: one extreme name should not define an industry.
per_company = industries.merge(
    correlation, left_on="ticker", right_index=True, how="inner"
)
per_industry = (
    per_company.groupby("sub_industry")
    .agg(companies=("ticker", "nunique"), ai_correlation=("ai_correlation", "median"))
    .sort_values("ai_correlation")
)
per_industry = per_industry[per_industry["companies"] >= 5]

# Printing happens only when this file is run directly, so that
# rank_industries.py can import `per_industry` quietly.
if __name__ == "__main__":
    pd.set_option("display.width", 120)
    print(f"\nAI factor built from {len(present)} names, {len(returns)} trading days "
          f"from {FROM_DATE}\n")
    print("QUIETEST industries (move least with the AI trade)")
    print(per_industry.head(12).round(3).to_string())
    print("\nLOUDEST industries (move most with the AI trade)")
    print(per_industry.tail(12).round(3).to_string())
