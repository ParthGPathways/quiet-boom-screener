# M1.3 - pull quarterly fundamentals from SEC EDGAR companyfacts.

# EDGAR returns deeply nested JSON containing ~500 accounting tags per company.
# Those tags come in three shapes, each needing its own cleaning rule, which is
# what the three extract_* functions below are for:

#   income statement  discrete quarters, but 6/9/12-month figures sit in the same
#                     series, and old quarters get restated in later filings
#   cash flow         reported year-to-date, so quarters must be differenced out
#   balance sheet     a snapshot on a single date, with no period at all

# Output: data/raw/fundamentals.parquet, one row per company/quarter/metric.

# M1.3 — pull quarterly fundamentals from SEC EDGAR companyfacts
import os

import requests
import pandas as pd

# The SEC's fair-access policy asks callers to identify themselves with a contact
# address, and throttles or blocks requests that do not. Override with:
#     export SEC_USER_AGENT="your.name@example.com"
HEADERS = {"User-Agent": os.environ.get("SEC_USER_AGENT", "p.goel10@lse.ac.uk")}

# Which GAAP tags to look for, per metric.
# Aliases (same concept, renamed over time) -> merged together.
# Alternatives (genuinely different measures)  -> first match wins.
REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
]

OPERATING_INCOME_TAGS = [
    "OperatingIncomeLoss",
]

DA_TAGS = [
    "DepreciationDepletionAndAmortization",
    "DepreciationAndAmortization",
    "DepreciationAmortizationAndAccretionNet",
]

CAPEX_TAGS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
]

DEBT_TAGS = [
    "LongTermDebt",
    "LongTermDebtNoncurrent",
]

# Diluted rather than basic: valuation should assume options and convertibles are
# exercised. Reported in the "shares" unit, not USD, and as a weighted average over
# a period - so it must never be differenced the way cash flow items are.
SHARES_TAGS = [
    "WeightedAverageNumberOfDilutedSharesOutstanding",
]

CASH_TAGS = [
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
]

# Profit after interest and tax, which is what P/E is built on. Operating income
# (collected above) sits higher up the income statement and drives EV/EBITDA instead.
NET_INCOME_TAGS = [
    "NetIncomeLoss",
    "ProfitLoss",
]


# EDGAR requires the CIK zero-padded to 10 digits: CIK0000320193, not CIK320193.
# timeout=30 matters - without it a stalled connection hangs the run forever, and
# a hang is not an exception, so the try/except in the loop below cannot catch it.
def fetch_company_facts(cik):
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.json()


# Income statement items: the discrete quarter is reported directly.
def extract_quarterly(us_gaap, tags, unit="USD"):
    records = []
    for tag in tags:
        if tag in us_gaap:
            records.extend(us_gaap[tag]["units"].get(unit, []))              # extend, not append: merge every alias tag

    if not records:
        return None

    df = pd.DataFrame(records)
    df["start"] = pd.to_datetime(df["start"])
    df["end"] = pd.to_datetime(df["end"])
    df["days"] = (df["end"] - df["start"]).dt.days

    # 80-100 days rather than exactly 90: a 53-week fiscal year gives a 97-day quarter.
    df = df[(df["days"] >= 80) & (df["days"] <= 100)]
    df = df.sort_values("filed").drop_duplicates(subset="end", keep="last") # restatements: keep the newest filing

    return df[["end", "val"]]


# Cash flow items: reported year-to-date, so difference consecutive periods.
def extract_ytd_quarterly(us_gaap, tags, unit="USD"):
    records = []
    for tag in tags:
        if tag in us_gaap:
            records.extend(us_gaap[tag]["units"].get(unit, []))              # extend, not append: merge every alias tag

    if not records:
        return None

    df = pd.DataFrame(records)
    df["start"] = pd.to_datetime(df["start"])
    df["end"] = pd.to_datetime(df["end"])

    df = df.sort_values("filed").drop_duplicates(subset=["start", "end"], keep="last")
    df = df.sort_values(["start", "end"])

    # Every year-to-date period within one fiscal year shares the same start date, so
    # grouping on it and differencing turns cumulative totals into discrete quarters.
    # The first row of each group has nothing above it, and its YTD figure IS Q1.
    df["val"] = df.groupby("start")["val"].diff().fillna(df["val"])

    # A derived quarter runs from the previous row's end to this row's end. Measuring
    # that span catches groups where earlier quarters are missing from EDGAR entirely,
    # which would otherwise leave a full year masquerading as a quarter.
    prev_end = df.groupby("start")["end"].shift()
    quarter_start = prev_end.fillna(df["start"])
    df["days"] = (df["end"] - quarter_start).dt.days
    # 80-100 days rather than exactly 90: a 53-week fiscal year gives a 97-day quarter.
    df = df[(df["days"] >= 80) & (df["days"] <= 100)]

    df = df.sort_values("filed").drop_duplicates(subset="end", keep="last") # restatements: keep the newest filing
    return df[["end", "val"]]


# Balance sheet items: a snapshot on one date, no period to filter.
def extract_instant(us_gaap, tags, unit="USD"):
    records = None
    for tag in tags:
        if tag in us_gaap:
            records = us_gaap[tag]["units"].get(unit)
            if records:
                break                                                     # first match wins: these tags measure different things

    if records is None:
        return None

    df = pd.DataFrame(records)
    df["end"] = pd.to_datetime(df["end"])
    df = df.sort_values("filed").drop_duplicates(subset="end", keep="last") # restatements: keep the newest filing
    return df[["end", "val"]]


# Which extraction rule each metric uses. Storing the function itself (no brackets)
# makes the choice data rather than code - switching a metric is a one-word edit.
METRICS = [
    ("revenue",          REVENUE_TAGS,          extract_ytd_quarterly, "USD"),
    ("operating_income", OPERATING_INCOME_TAGS, extract_ytd_quarterly, "USD"),
    ("d_and_a",          DA_TAGS,               extract_ytd_quarterly, "USD"),
    ("capex",            CAPEX_TAGS,            extract_ytd_quarterly, "USD"),
    ("net_income",       NET_INCOME_TAGS,       extract_ytd_quarterly, "USD"),
    ("debt",             DEBT_TAGS,             extract_instant,       "USD"),
    # Share counts are a level, so extract_quarterly (which takes the reported
    # figure) rather than extract_ytd_quarterly (which would subtract one quarter's
    # share count from another's and produce nonsense).
    ("shares_diluted",   SHARES_TAGS,           extract_quarterly,     "shares"),
    ("cash",             CASH_TAGS,             extract_instant,       "USD"),
]


# Everything above handles one metric. This runs all five for one company and
# returns them stacked in long format, or None if it filed nothing usable.
def build_company_frame(cik):
    facts = fetch_company_facts(cik)
    us_gaap = facts.get("facts", {}).get("us-gaap", {})

    frames = []
    for name, tags, extractor, unit in METRICS:
        df = extractor(us_gaap, tags, unit)
        if df is None or df.empty:                                    # company doesn't use any of these tags
            continue
        df = df.copy()
        df["metric"] = name
        df["cik"] = cik
        frames.append(df)

    if not frames:
        return None

    return pd.concat(frames, ignore_index=True)[["cik", "end", "metric", "val"]]


import time
from pathlib import Path

UNIVERSE_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "universe.csv"

# Run the whole universe. Each company is wrapped in try/except so that one bad
# filing costs one company rather than the entire 13-minute run.
universe = pd.read_csv(UNIVERSE_PATH)

# Each company's result is written to its own small parquet as it arrives, and
# re-runs skip anything already cached, so an interruption costs seconds rather
# than the whole 13-minute run.
#
# The cache is keyed by CIK only, so it does NOT know about changes to METRICS:
# after adding or changing a metric, delete this directory to force a full refetch.
CACHE_DIR = UNIVERSE_PATH.parent / "fundamentals_cache"
# parents=True: on a fresh clone data/raw/ does not exist either.
CACHE_DIR.mkdir(parents=True, exist_ok=True)

frames = []
failures = []

for i, (_, row) in enumerate(universe.iterrows(), start=1):

    cached = CACHE_DIR / f"{int(row['cik'])}.parquet"
    if cached.exists():
        frames.append(pd.read_parquet(cached))
        continue

    try:
        df = build_company_frame(int(row["cik"]))
        if df is not None:
            df["ticker"] = row["ticker"]
            df.to_parquet(cached, index=False)
            frames.append(df)
        else:
            failures.append((row["ticker"], "no usable tags"))
    except Exception as error:                                        # record the failure and carry on
        failures.append((row["ticker"], str(error)))

    if i % 50 == 0:
        print(f"{i}/{len(universe)}  ok={len(frames)}  failed={len(failures)}") # heartbeat, so a stall is visible


    time.sleep(0.1)                                                   # SEC allows 10 requests/second

fundamentals = pd.concat(frames, ignore_index=True)

# Write under a temporary name and rename into place. A rename is atomic, so a
# reader sees either the old complete file or the new complete file, never a
# half-written one.
FUNDAMENTALS_PATH = UNIVERSE_PATH.parent / "fundamentals.parquet"
temp_path = FUNDAMENTALS_PATH.with_suffix(".parquet.tmp")
fundamentals.to_parquet(temp_path, index=False)
temp_path.replace(FUNDAMENTALS_PATH)

print(f"{len(frames)} companies, {len(fundamentals):,} rows -> {FUNDAMENTALS_PATH}")
print("failures:", len(failures))
print(failures[:10])

