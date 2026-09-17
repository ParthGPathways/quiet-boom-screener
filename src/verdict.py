# M4.3 - the cheap-vs-growth verdict per industry.
#
# This is where the two halves of the project meet. M3 found industries growing
# faster than they normally do without an AI story attached. M4 worked out what the
# market is paying for them. The question left is whether the growth is priced in.
#
#   quiet_boom  from rank_industries: accelerating, broad-based, and not moving
#               with the AI trade
#   valuation   two independent views, because neither is reliable alone:
#                 EV/EBITDA   what the market pays per unit of operating profit,
#                             low = cheap. Meaningless for banks and insurers,
#                             whose debt is inventory rather than financing.
#                 dcf_upside  implied enterprise value over market enterprise
#                             value, above 1.0 = the cash flows justify more than
#                             the market is paying. Biased towards low-beta
#                             defensives, which get a low discount rate.
#
# The verdict combines the growth signal with the cheaper of the two value signals
# expressed as z-scores, so an industry has to be both growing unusually fast AND
# not already expensive to rank highly.
#
# Reads data/db/screener.db via the modules below. Prints the final table.

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dcf
import rank_industries
import valuation

Z_CLIP = 3.0
MIN_COMPANIES = 5
VALUE_WEIGHT = 1.0  # how much cheapness counts relative to the growth signal


def zscore(series):
    """Standard deviations from the mean of all industries, with outliers capped."""
    return ((series - series.mean()) / series.std()).clip(-Z_CLIP, Z_CLIP)


# Industry-level DCF upside: median company, as everywhere else in this project.
dcf_ok = dcf.dcf.dropna(subset=["upside"])
dcf_industry = (
    dcf_ok.groupby("sub_industry")
    .agg(dcf_companies=("cik", "nunique"), dcf_upside=("upside", "median"))
)
dcf_industry = dcf_industry[dcf_industry["dcf_companies"] >= MIN_COMPANIES]

combined = (
    rank_industries.combined
    .join(valuation.per_industry[["ev_ebitda", "pe", "ebitda_margin"]], how="left")
    .join(dcf_industry[["dcf_upside"]], how="left")
)

# EV/EBITDA does not apply to financials. A bank's debt is its raw material, not its
# financing, so adding it to enterprise value inflates the multiple - Regional Banks
# came out at 40x against a P/E of 12. Blanking it here means financials are scored
# on the DCF alone rather than penalised for a metric that does not describe them.
connection = __import__("sqlite3").connect(valuation.DB_PATH)
financial_industries = set(pd.read_sql_query(
    "SELECT DISTINCT sub_industry FROM companies WHERE sector = 'Financials'",
    connection,
)["sub_industry"])
connection.close()

is_financial = combined.index.isin(financial_industries)
combined.loc[is_financial, "ev_ebitda"] = pd.NA

# Cheap on multiples means a LOW EV/EBITDA, so the z-score is negated to make
# "higher is better" true for every component of the final score.
combined["z_multiple"] = -zscore(combined["ev_ebitda"].astype(float))
combined["z_dcf"] = zscore(combined["dcf_upside"])

# Average whichever value signals exist. An industry with only one of the two is
# scored on that one rather than dropped, but banks - where EV/EBITDA is nonsense -
# end up resting entirely on the DCF, which is the honest outcome.
combined["z_value"] = combined[["z_multiple", "z_dcf"]].mean(axis=1)

combined["verdict_score"] = (
    combined["quiet_boom"] + VALUE_WEIGHT * combined["z_value"].fillna(0.0)
)
combined = combined.sort_values("verdict_score", ascending=False)

show = combined[[
    "companies", "verdict_score", "quiet_boom", "z_value",
    "acceleration", "ai_correlation", "ev_ebitda", "dcf_upside", "breadth",
]].round(2)
show.columns = ["n", "verdict", "quiet_boom", "value", "accel", "ai_corr",
                "ev_ebitda", "dcf_up", "breadth"]

if __name__ == "__main__":
    pd.set_option("display.width", 170)
    print(f"{len(combined)} industries with both a growth signal and a price\n")
    print("QUIET BOOM, AND NOT YET PRICED IN")
    print(show.head(12).to_string())
    print("\nGROWING, BUT EXPENSIVE OR ALREADY AN AI TRADE")
    print(show.tail(6).to_string())
