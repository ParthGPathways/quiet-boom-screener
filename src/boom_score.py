# M3.1 - score industries on growth acceleration, margin expansion and capex cycle.
#
# The question this answers: which industries are growing faster than they normally
# do, with the growth spread across the industry rather than concentrated in a few
# acquisitive names, and with margins and investment confirming it?
#
# Single-year growth is not enough. An acquisition steps revenue up ~45% in one
# year and looks identical to a boom, so every measure here compares a RECENT
# window against the same industry's own BASELINE, and is taken as a median across
# companies rather than an aggregate (which the largest company would dominate).
#
#   acceleration     median revenue growth, recent minus baseline (percentage points)
#   margin_change    median operating margin, recent minus baseline (percentage points)
#   capex_change     median capex as a share of revenue, recent minus baseline
#   breadth          share of companies growing at all during the recent window
#
# SQL's job here is only to produce clean per-company-per-year facts; the scoring
# is pandas, because three medians in SQL would need the ROW_NUMBER trick three times.
#
# Reads data/db/screener.db. Prints a ranked table.

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "db" / "screener.db"

RECENT_FROM, RECENT_TO = 2024, 2025

# Two baselines, because the measures are different kinds of quantity.
#
# Growth is a RATE and mean-reverts, so the right question is "is this industry
# growing faster than it normally does", which needs a long history.
#
# Margin and capex intensity are LEVELS that can drift one way for years. Against a
# long baseline, an industry that improved margins from 2017 to 2022 and has been
# flat (or falling) since still reads as "expanding" - Oil & Gas Storage scored
# +11.5 points of margin expansion while its margins were actually declining from a
# 2023 peak. A short adjacent window asks "has this changed lately" instead.
RATE_BASELINE_FROM, RATE_BASELINE_TO = 2017, 2023
LEVEL_BASELINE_FROM, LEVEL_BASELINE_TO = 2021, 2023
MIN_COMPANIES = 5
MIN_BREADTH = 0.70   # at least 70% of an industry's companies must be growing

# One row per company per calendar year, with the three metrics side by side.
# COUNT(CASE WHEN ...) counts only the rows matching that condition, so a metric
# with fewer than 4 quarters can be rejected per metric rather than per company.
FACTS_QUERY = """
WITH filers AS (
    -- one row per filing entity: dual-class tickers share a cik
    SELECT cik, MIN(sub_industry) AS sub_industry
    FROM companies
    GROUP BY cik
)
-- SUM(CASE WHEN ...) turns the long fundamentals table (one row per metric) into
-- wide columns (one column per metric). Rows that don't match a condition
-- contribute nothing, so each SUM only sees its own metric.
SELECT f.cik,
       f.sub_industry,
       CAST(substr(fu.period_end, 1, 4) AS INTEGER) AS year,
       SUM(CASE WHEN fu.metric = 'revenue'          THEN fu.val END) AS revenue,
       SUM(CASE WHEN fu.metric = 'operating_income' THEN fu.val END) AS operating_income,
       SUM(CASE WHEN fu.metric = 'capex'            THEN fu.val END) AS capex,
       COUNT(CASE WHEN fu.metric = 'revenue'          THEN 1 END) AS revenue_q,
       COUNT(CASE WHEN fu.metric = 'operating_income' THEN 1 END) AS operating_income_q,
       COUNT(CASE WHEN fu.metric = 'capex'            THEN 1 END) AS capex_q
FROM fundamentals fu
JOIN filers f ON f.cik = fu.cik
WHERE fu.metric IN ('revenue', 'operating_income', 'capex')
GROUP BY f.cik, f.sub_industry, year
"""

connection = sqlite3.connect(DB_PATH)
facts = pd.read_sql_query(FACTS_QUERY, connection)
connection.close()

# A metric is only usable for a year if all four quarters are present. Blanking the
# incomplete ones (rather than dropping the row) keeps a company whose revenue is
# complete but whose capex is not.
for metric in ["revenue", "operating_income", "capex"]:
    facts.loc[facts[f"{metric}_q"] != 4, metric] = np.nan

# --- per-company measures -------------------------------------------------------

facts = facts.sort_values(["cik", "year"])

# Year-on-year revenue growth. prev_year guards the case where a company is missing
# a year: the row above is then two years back, and the growth would be overstated.
facts["prev_revenue"] = facts.groupby("cik")["revenue"].shift()
facts["prev_year"] = facts.groupby("cik")["year"].shift()
consecutive = facts["prev_year"] == facts["year"] - 1
facts["growth"] = np.where(
    consecutive & facts["prev_revenue"].gt(0),
    100.0 * (facts["revenue"] - facts["prev_revenue"]) / facts["prev_revenue"],
    np.nan,
)

# Levels, not changes, so these need no lag.
facts["margin"] = 100.0 * facts["operating_income"] / facts["revenue"]
facts["capex_intensity"] = 100.0 * facts["capex"] / facts["revenue"]

# --- industry aggregation -------------------------------------------------------

recent = facts["year"].between(RECENT_FROM, RECENT_TO)
rate_baseline = facts["year"].between(RATE_BASELINE_FROM, RATE_BASELINE_TO)
level_baseline = facts["year"].between(LEVEL_BASELINE_FROM, LEVEL_BASELINE_TO)

MEASURES = ["growth", "margin", "capex_intensity"]


def median_by_industry(mask, suffix):
    """Median of each measure per sub-industry, over the rows selected by mask."""
    out = facts[mask].groupby("sub_industry")[MEASURES].median()
    return out.add_suffix(suffix)


scores = median_by_industry(recent, "_recent")
rate_base = median_by_industry(rate_baseline, "_rate_base")
level_base = median_by_industry(level_baseline, "_level_base")
scores = scores.join(rate_base, how="inner").join(level_base, how="inner")

# Each measure against the baseline appropriate to its kind.
scores["acceleration"] = scores["growth_recent"] - scores["growth_rate_base"]
scores["margin_change"] = scores["margin_recent"] - scores["margin_level_base"]
scores["capex_change"] = (
    scores["capex_intensity_recent"] - scores["capex_intensity_level_base"]
)

# Breadth: how much of the industry is participating, not just the middle company.
# Computed only over companies that HAVE a growth figure. NaN > 0 evaluates to False
# in pandas, so including blanks would silently count missing data as "not growing".
measurable = facts[recent].dropna(subset=["growth"])
scores["breadth"] = measurable.groupby("sub_industry")["growth"].apply(lambda s: s.gt(0).mean())
scores["companies"] = measurable.groupby("sub_industry")["cik"].nunique()

scores = scores[scores["companies"] >= MIN_COMPANIES]
scores = scores[scores["breadth"] >= MIN_BREADTH]   # the trust gate, applied before ranking
scores = scores.dropna(subset=["acceleration"])

# --- combining the measures into one score --------------------------------------
#
# The four measures are in incompatible units: percentage points of revenue growth,
# percentage points of operating margin, percentage points of capex intensity, and a
# fraction between 0 and 1. Adding them raw would let acceleration dominate purely
# because its numbers are larger, making the weighting an accident rather than a
# choice. A z-score restates each measure as "standard deviations from the average
# industry", after which they share a scale and the weights below are the only thing
# deciding how much each one counts.

# Breadth is deliberately NOT scored here. It answers "can this signal be trusted",
# not "is this a boom": an industry where every company grows at its usual rate has
# perfect breadth and is not accelerating at all. Scoring it additively let steady
# industries outrank accelerating ones, so it is applied as a threshold instead.
WEIGHTS = {
    "acceleration": 1.0,   # the core signal: growing faster than this industry normally does
    "margin_change": 0.5,  # widening margins suggest pricing power, not just volume
    "capex_change": 0.5,   # the industry itself investing behind the growth
}

Z_CLIP = 3.0  # cap extreme values at 3 sd so one freak industry cannot set the ranking


def zscore(series):
    """Standard deviations from the mean of all industries, with outliers capped."""
    return ((series - series.mean()) / series.std()).clip(-Z_CLIP, Z_CLIP)


for measure in WEIGHTS:
    # Missing measures become 0 = "average", not 0 = "bad". REITs report no capex
    # under the tags we collect and banks no operating income; neither should be
    # penalised for a metric that does not apply to them.
    scores[f"z_{measure}"] = zscore(scores[measure]).fillna(0.0)

scores["boom_score"] = sum(
    weight * scores[f"z_{measure}"] for measure, weight in WEIGHTS.items()
)

scores = scores.sort_values("boom_score", ascending=False)

# --- output ---------------------------------------------------------------------

# Show the score alongside its ingredients: a single number nobody can audit is
# worth less than a ranked number whose components are visible.
show = scores[["companies", "boom_score", "acceleration", "breadth",
               "margin_change", "capex_change", "growth_recent"]].round(2)
show.columns = ["n", "score", "accel", "breadth", "margin_chg", "capex_chg", "growth"]

pd.set_option("display.width", 140)
print(show.head(25).to_string())
print(f"\n{len(scores)} industries scored")
