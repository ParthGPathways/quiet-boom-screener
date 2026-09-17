# M4.2 - a simplified discounted cash flow valuation per company.
#
# A DCF says a business is worth the cash it will produce, discounted back to today
# because money now is worth more than money later. Three pieces:
#
#   1. FREE CASH FLOW today
#        operating profit, taxed, plus D&A back (it is an accounting charge, not
#        cash out), minus capex (which is cash out but not an expense).
#        This is UNLEVERED free cash flow - before interest - so it belongs to
#        lenders and shareholders together, and is therefore compared to enterprise
#        value rather than market cap.
#
#   2. A FORECAST, five years out
#        Growth starts at the company's own recent rate and fades towards the
#        terminal rate, because no business outgrows the economy forever. The fade
#        matters more than the starting point: without it, a fast grower's value
#        runs away with itself.
#
#   3. A TERMINAL VALUE
#        Everything after year five, as a perpetuity: FCF * (1+g) / (WACC - g).
#        Usually the majority of the answer, which is why the terminal growth rate
#        is the single most sensitive assumption in the whole model.
#
# Discounted at WACC - the blended return lenders and shareholders require, weighted
# by how much of the business each funds. Cost of equity comes from CAPM, using a
# beta measured from this project's own price data rather than a vendor's.
#
# The output is an implied enterprise value, compared against the market's actual
# enterprise value. It is a rough model: treat a 20% gap as noise and look at
# large, consistent divergences instead.
#
# Reads data/db/screener.db via valuation.py. Exposes `dcf`.

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import valuation

# --- assumptions ----------------------------------------------------------------
# Every one of these is a judgement. They are gathered here so a reader can argue
# with them without reading the code.

RISK_FREE = 0.042          # ~10-year US Treasury yield
EQUITY_RISK_PREMIUM = 0.05 # long-run excess return of equities over the risk-free rate
COST_OF_DEBT = 0.055       # representative investment-grade borrowing rate
TAX_RATE = 0.21            # US federal corporate rate
FORECAST_YEARS = 5
TERMINAL_GROWTH = 0.025    # roughly long-run nominal GDP; must stay below WACC
MAX_START_GROWTH = 0.25    # cap: nobody compounds at 40% for five years
MIN_WACC_SPREAD = 0.03     # WACC must exceed terminal growth by at least this much

BETA_FROM = "2024-01-01"
MIN_BETA_DAYS = 200

company = valuation.per_company.copy()

# --- beta, from our own price data ----------------------------------------------
# Beta is how much a share moves for a given move in the market. Regressing one
# against the other reduces to covariance / variance for a single factor.

connection = __import__("sqlite3").connect(valuation.DB_PATH)
prices = pd.read_sql_query(
    "SELECT ticker, date, close FROM prices WHERE date >= ? ORDER BY ticker, date",
    connection, params=(BETA_FROM,),
)
connection.close()

returns = prices.pivot(index="date", columns="ticker", values="close").sort_index().pct_change()
returns = returns[returns.columns[returns.notna().sum() >= MIN_BETA_DAYS]]
market = returns.mean(axis=1)  # equal-weighted universe as the market proxy

covariance = returns.apply(lambda col: col.cov(market))
beta = (covariance / market.var()).rename("beta")

company = company.merge(beta, left_on="ticker", right_index=True, how="left")
company["beta"] = company["beta"].fillna(1.0)  # no price history -> assume market risk

# --- WACC -----------------------------------------------------------------------

company["cost_of_equity"] = RISK_FREE + company["beta"] * EQUITY_RISK_PREMIUM

equity = company["market_cap"]
debt = company["debt"].fillna(0.0)
total_capital = equity + debt

company["wacc"] = (
    (equity / total_capital) * company["cost_of_equity"]
    + (debt / total_capital) * COST_OF_DEBT * (1 - TAX_RATE)
)
# A WACC at or below terminal growth makes the perpetuity infinite or negative, so
# floor it. This binds only for very low-beta, heavily indebted companies.
company["wacc"] = company["wacc"].clip(lower=TERMINAL_GROWTH + MIN_WACC_SPREAD)

# --- free cash flow -------------------------------------------------------------

company["fcf"] = (
    company["operating_income"] * (1 - TAX_RATE)
    + company["d_and_a"]
    - company["capex"]
)

# Starting growth: the company's own trailing-twelve-month revenue growth, from the
# last four quarters against the four before them. Revenue growth stands in for cash
# flow growth, which is far too noisy year to year to extrapolate from.
company["start_growth"] = company["revenue"] / company["revenue_prev"] - 1.0


def discounted_value(fcf, start_growth, wacc):
    """Present value of five fading years of FCF plus a terminal perpetuity."""
    if not np.isfinite(fcf) or fcf <= 0 or not np.isfinite(wacc):
        return np.nan
    growth = MAX_START_GROWTH if not np.isfinite(start_growth) else min(start_growth, MAX_START_GROWTH)
    growth = max(growth, TERMINAL_GROWTH)

    value = 0.0
    cash = fcf
    for year in range(1, FORECAST_YEARS + 1):
        # Fade linearly from the starting rate to the terminal rate.
        weight = (FORECAST_YEARS - year) / (FORECAST_YEARS - 1)
        rate = TERMINAL_GROWTH + (growth - TERMINAL_GROWTH) * weight
        cash *= 1 + rate
        value += cash / (1 + wacc) ** year

    terminal = cash * (1 + TERMINAL_GROWTH) / (wacc - TERMINAL_GROWTH)
    return value + terminal / (1 + wacc) ** FORECAST_YEARS


company["implied_ev"] = [
    discounted_value(f, g, w)
    for f, g, w in zip(company["fcf"], company["start_growth"], company["wacc"])
]

# Above 1.0 = the DCF says it is worth more than the market is paying.
company["upside"] = company["implied_ev"] / company["enterprise_value"]

dcf = company

if __name__ == "__main__":
    pd.set_option("display.width", 150)
    ok = dcf.dropna(subset=["upside", "ev_ebitda"])
    print(f"{len(ok)} companies valued by DCF\n")
    per_industry = (
        ok.groupby("sub_industry")
        .agg(companies=("cik", "nunique"), median_upside=("upside", "median"),
             median_wacc=("wacc", "median"), median_beta=("beta", "median"))
    )
    per_industry = per_industry[per_industry["companies"] >= 5]
    print("MOST UNDERVALUED by DCF (implied EV / market EV)")
    print(per_industry.sort_values("median_upside", ascending=False).head(12).round(2).to_string())
