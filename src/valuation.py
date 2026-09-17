# M4.1 - valuation multiples per company and per industry.
#
# Builds enterprise value and the two standard multiples:
#
#   EV       = market cap + debt - cash
#              what it would cost to buy the whole business outright: you pay for
#              the equity, inherit the debt, and get the cash on the balance sheet
#   EV/EBITDA  EV divided by trailing-twelve-month operating profit before D&A.
#              Preferred for cross-company comparison because it is neutral to how
#              a business is financed - a company with lots of debt and one with
#              none are directly comparable, which is not true of P/E
#   P/E        market cap divided by trailing-twelve-month net income
#
# Flow metrics (profit, revenue) are summed over the last four quarters. Stock
# metrics (debt, cash, share count) are taken at their most recent reported date.
# Mixing the two is the standard convention and is what "trailing twelve months"
# means in practice.
#
# Reads data/db/screener.db. Exposes `per_company` and `per_industry`.

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "db" / "screener.db"

FLOW_METRICS = ["operating_income", "d_and_a", "net_income", "revenue", "capex"]
STOCK_METRICS = ["debt", "cash", "shares_diluted"]
MIN_COMPANIES = 5

# ROW_NUMBER per company and metric, newest first, so the four most recent quarters
# of each flow metric and the single latest value of each stock metric can be picked
# out without assuming every company reports on the same calendar.
FACTS_QUERY = """
WITH filers AS (
    SELECT cik, MIN(sub_industry) AS sub_industry, MIN(ticker) AS ticker, MIN(name) AS name
    FROM companies
    GROUP BY cik
),
ranked AS (
    SELECT cik, metric, period_end, val,
           ROW_NUMBER() OVER (PARTITION BY cik, metric ORDER BY period_end DESC) AS recency
    FROM fundamentals
)
SELECT f.cik, f.ticker, f.name, f.sub_industry, r.metric, r.period_end, r.val, r.recency
FROM ranked r
JOIN filers f ON f.cik = r.cik
WHERE r.recency <= 8   -- 8 quarters: the last year, and the year before it
"""

connection = sqlite3.connect(DB_PATH)
facts = pd.read_sql_query(FACTS_QUERY, connection)
latest_prices = pd.read_sql_query(
    """
    SELECT p.ticker, p.close
    FROM prices p
    JOIN (SELECT ticker, MAX(date) AS date FROM prices GROUP BY ticker) last
      ON last.ticker = p.ticker AND last.date = p.date
    """,
    connection,
)
connection.close()

identity = facts[["cik", "ticker", "name", "sub_industry"]].drop_duplicates("cik")

# Trailing twelve months. Requiring all four quarters matters: three quarters summed
# would understate profit by roughly a quarter and make the company look expensive.
flows = facts[facts["metric"].isin(FLOW_METRICS)]


def summed_window(frame, first, last, suffix=""):
    """Sum a four-quarter window per company and metric, requiring all four."""
    window = frame[frame["recency"].between(first, last)]
    out = (
        window.groupby(["cik", "metric"])
        .agg(value=("val", "sum"), quarters=("val", "size"))
        .reset_index()
    )
    out = out[out["quarters"] == 4]
    return out.pivot(index="cik", columns="metric", values="value").add_suffix(suffix)


ttm = summed_window(flows, 1, 4)
# The four quarters before those, used only to derive a growth rate.
prior = summed_window(flows[flows["metric"] == "revenue"], 5, 8, suffix="_prev")

# Latest reported balance-sheet figures.
stocks = facts[(facts["metric"].isin(STOCK_METRICS)) & (facts["recency"] == 1)]
stocks = stocks.pivot(index="cik", columns="metric", values="val")

# reset_index puts cik back as a column: merge() discards the index, and cik is
# needed later for counting distinct companies per industry.
company = (
    identity.set_index("cik")
    .join(ttm, how="inner")
    .join(prior, how="left")
    .join(stocks, how="left")
    .reset_index()
)
company = company.merge(latest_prices, on="ticker", how="left")

# --- the multiples --------------------------------------------------------------

company["ebitda"] = company["operating_income"] + company["d_and_a"]
company["market_cap"] = company["shares_diluted"] * company["close"]
company["enterprise_value"] = (
    company["market_cap"] + company["debt"].fillna(0) - company["cash"].fillna(0)
)

# A multiple is only meaningful when the denominator is positive: a loss-making
# company has a negative P/E, which is not "cheap", it is undefined. Blanking these
# keeps them out of medians rather than dragging them down.
company["ev_ebitda"] = np.where(
    company["ebitda"] > 0, company["enterprise_value"] / company["ebitda"], np.nan
)
company["pe"] = np.where(
    company["net_income"] > 0, company["market_cap"] / company["net_income"], np.nan
)

# Margin is a per-company ratio, so it must be computed per company and then
# medianed - taking a median of EBITDA and dividing by a median of revenue would
# mix two different companies' numbers.
company["ebitda_margin"] = 100.0 * company["ebitda"] / company["revenue"]

per_company = company

per_industry = (
    per_company.groupby("sub_industry")
    .agg(
        companies=("cik", "nunique"),
        ev_ebitda=("ev_ebitda", "median"),
        pe=("pe", "median"),
        ebitda_margin=("ebitda_margin", "median"),
    )
)
per_industry = per_industry[per_industry["companies"] >= MIN_COMPANIES]

if __name__ == "__main__":
    pd.set_option("display.width", 140)
    print(f"{len(per_company)} companies valued, {len(per_industry)} industries\n")
    print("CHEAPEST industries by EV/EBITDA")
    print(per_industry.sort_values("ev_ebitda").head(12).round(1).to_string())
    print("\nMOST EXPENSIVE")
    print(per_industry.sort_values("ev_ebitda").tail(12).round(1).to_string())
