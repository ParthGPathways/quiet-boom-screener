# M1.1 - build the company universe.

# Scrapes the S&P 500 and S&P 400 constituent lists from Wikipedia, then attaches
# each company's SEC CIK (the SEC's permanent id for a filer) from the SEC's own
# ticker->CIK map. Output: data/raw/universe.csv, one row per company.

import os

import pandas as pd
import requests
from io import StringIO
from pathlib import Path

# The SEC's authoritative ticker -> CIK mapping for every company that files with them.
# The SEC's fair-access policy asks callers to identify themselves with a contact
# address, and throttles or blocks requests that do not. Override with:
#     export SEC_USER_AGENT="your.name@example.com"
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "p.goel10@lse.ac.uk")

CIK_URL = "https://www.sec.gov/files/company_tickers.json"

# Downloads that mapping as a DataFrame with columns cik_str / ticker / title.
# The SEC's fair-access policy asks callers to identify themselves by email.
def fetch_cik_map():
    response = requests.get(CIK_URL, headers={"User-Agent": SEC_USER_AGENT})
    response.raise_for_status()                                   # stop here if the SEC refused the request
    return pd.DataFrame(response.json().values())                 # the JSON is keyed by row number; keep only the values


# Wikipedia maintains both constituent lists; they are the practical free source.
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
SP400_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "universe.csv"


# Fetches a webpage and returns every HTML table on it as a list of DataFrames
def fetch_tables(url):
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()  # crash loudly if the site refuses (403, 404...)
    return pd.read_html(StringIO(response.text))

# [0] = the first table on the page, which is the constituents list
sp500 = fetch_tables(SP500_URL)[0]                                # [0] = the constituents table
sp500["index_membership"] = "SP500"                               # tag every row before the two frames are merged

sp400 = fetch_tables(SP400_URL)[0]
sp400["index_membership"] = "SP400"                               # otherwise this distinction is lost forever

# Rename Wikipedia's column headings to our own schema, so that a change on their
# side only ever requires editing this dictionary. Both indexes must end up with
# identical columns or they cannot be stacked together below.
sp500 = sp500.rename(columns={
    "Symbol": "ticker",
    "Security": "name",
    "GICS Sector": "sector",
    "GICS Sub-Industry": "sub_industry",
})
sp400 = sp400.rename(columns={
    "Symbol": "ticker",
    "Security": "name",
    "GICS Sector": "sector",
    "GICS Sub-Industry": "sub_industry",
})
sp500 = sp500[["ticker", "name", "sector", "sub_industry", "index_membership"]] # keep only our columns, in our order
sp400 = sp400[["ticker", "name", "sector", "sub_industry", "index_membership"]]

# Assemble the final table: stack the two indexes, normalise tickers, attach CIKs.
cik_map = fetch_cik_map()
universe = pd.concat([sp500, sp400], ignore_index=True)           # 503 + 400 = 903 rows
cik_map = cik_map.rename(columns={"cik_str": "cik"})[["ticker", "cik"]] # trim the SEC map to just the join key and the value
# Wikipedia writes share classes as BRK.B; the SEC and Yahoo both write BRK-B.
# This must happen BEFORE the merge below, which matches on exact text.
universe["ticker"] = universe["ticker"].str.replace(".", "-", regex=False)
universe = universe.merge(cik_map, on="ticker", how="left")       # left join: keep all 903 rows even if a CIK is missing
# Fail loudly rather than write a damaged file: every company must have a CIK,
# and the row count must match the two indexes' published sizes.
assert universe["cik"].isna().sum() == 0, "some tickers have no CIK"
assert len(universe) == 903, f"expected 903 rows, got {len(universe)}"

# data/ is not in version control, so the directory may not exist on a fresh clone.
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
universe.to_csv(OUT_PATH, index=False)                            # index=False: don't write pandas' row numbers as a column
print(f"wrote {len(universe)} rows to {OUT_PATH}")
