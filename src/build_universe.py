import pandas as pd
import requests
from io import StringIO
from pathlib import Path

CIK_URL = "https://www.sec.gov/files/company_tickers.json"

def fetch_cik_map():
    response = requests.get(CIK_URL, headers={"User-Agent": "p.goel10@lse.ac.uk"})
    response.raise_for_status()
    return pd.DataFrame(response.json().values())


SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
SP400_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "universe.csv"


# Fetches a webpage and returns every HTML table on it as a list of DataFrames
def fetch_tables(url):
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()  # crash loudly if the site refuses (403, 404...)
    return pd.read_html(StringIO(response.text))

# [0] = the first table on the page, which is the constituents list
sp500 = fetch_tables(SP500_URL)[0]
sp500["index_membership"] = "SP500"

sp400 = fetch_tables(SP400_URL)[0]
sp400["index_membership"] = "SP400"

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
sp500 = sp500[["ticker", "name", "sector", "sub_industry", "index_membership"]]
sp400 = sp400[["ticker", "name", "sector", "sub_industry", "index_membership"]]

cik_map = fetch_cik_map()
universe = pd.concat([sp500, sp400], ignore_index=True)
cik_map = cik_map.rename(columns={"cik_str": "cik"})[["ticker", "cik"]]
universe["ticker"] = universe["ticker"].str.replace(".", "-", regex=False)
universe = universe.merge(cik_map, on="ticker", how="left")
assert universe["cik"].isna().sum() == 0, "some tickers have no CIK"
assert len(universe) == 903, f"expected 903 rows, got {len(universe)}"

universe.to_csv(OUT_PATH, index=False)
print(f"wrote {len(universe)} rows to {OUT_PATH}")
