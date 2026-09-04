# M1.3 — pull quarterly fundamentals from SEC EDGAR companyfacts
import requests
import pandas as pd

HEADERS = {"User-Agent": "p.goel10@lse.ac.uk"}

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


def fetch_company_facts(cik):
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    return response.json()


# Income statement items: the discrete quarter is reported directly.
def extract_quarterly(us_gaap, tags):
    records = []
    for tag in tags:
        if tag in us_gaap:
            records.extend(us_gaap[tag]["units"]["USD"])

    if not records:
        return None

    df = pd.DataFrame(records)
    df["start"] = pd.to_datetime(df["start"])
    df["end"] = pd.to_datetime(df["end"])
    df["days"] = (df["end"] - df["start"]).dt.days

    df = df[(df["days"] >= 80) & (df["days"] <= 100)]
    df = df.sort_values("filed").drop_duplicates(subset="end", keep="last")

    return df[["end", "val"]]


# Cash flow items: reported year-to-date, so difference consecutive periods.
def extract_ytd_quarterly(us_gaap, tags):
    records = []
    for tag in tags:
        if tag in us_gaap:
            records.extend(us_gaap[tag]["units"]["USD"])

    if not records:
        return None

    df = pd.DataFrame(records)
    df["start"] = pd.to_datetime(df["start"])
    df["end"] = pd.to_datetime(df["end"])

    df = df.sort_values("filed").drop_duplicates(subset=["start", "end"], keep="last")
    df = df.sort_values(["start", "end"])

    df["val"] = df.groupby("start")["val"].diff().fillna(df["val"])

    prev_end = df.groupby("start")["end"].shift()
    quarter_start = prev_end.fillna(df["start"])
    df["days"] = (df["end"] - quarter_start).dt.days
    df = df[(df["days"] >= 80) & (df["days"] <= 100)]

    df = df.sort_values("filed").drop_duplicates(subset="end", keep="last")
    return df[["end", "val"]]


# Balance sheet items: a snapshot on one date, no period to filter.
def extract_instant(us_gaap, tags):
    records = None
    for tag in tags:
        if tag in us_gaap:
            records = us_gaap[tag]["units"]["USD"]
            break

    if records is None:
        return None

    df = pd.DataFrame(records)
    df["end"] = pd.to_datetime(df["end"])
    df = df.sort_values("filed").drop_duplicates(subset="end", keep="last")
    return df[["end", "val"]]


METRICS = [
    ("revenue",          REVENUE_TAGS,          extract_quarterly),
    ("operating_income", OPERATING_INCOME_TAGS, extract_quarterly),
    ("d_and_a",          DA_TAGS,               extract_ytd_quarterly),
    ("capex",            CAPEX_TAGS,            extract_ytd_quarterly),
    ("debt",             DEBT_TAGS,             extract_instant),
]


def build_company_frame(cik):
    facts = fetch_company_facts(cik)
    us_gaap = facts.get("facts", {}).get("us-gaap", {})

    frames = []
    for name, tags, extractor in METRICS:
        df = extractor(us_gaap, tags)
        if df is None or df.empty:
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

universe = pd.read_csv(UNIVERSE_PATH)

frames = []
failures = []

for i, (_, row) in enumerate(universe.iterrows(), start=1):

    try:
        df = build_company_frame(int(row["cik"]))
        if df is not None:
            df["ticker"] = row["ticker"]
            frames.append(df)
        else:
            failures.append((row["ticker"], "no usable tags"))
    except Exception as error:
        failures.append((row["ticker"], str(error)))

    if i % 50 == 0:
        print(f"{i}/{len(universe)}  ok={len(frames)}  failed={len(failures)}")


    time.sleep(0.1)

fundamentals = pd.concat(frames, ignore_index=True)

FUNDAMENTALS_PATH = UNIVERSE_PATH.parent / "fundamentals.parquet"
fundamentals.to_parquet(FUNDAMENTALS_PATH, index=False)

print(f"{len(frames)} companies, {len(fundamentals):,} rows -> {FUNDAMENTALS_PATH}")
print("failures:", len(failures))
print(failures[:10])

