# M1.2 - pull daily price history for every company in the universe.

# Reads the tickers written by build_universe.py, downloads ~10 years of daily
# adjusted prices from Yahoo Finance in batches, and writes one long-format table
# to data/raw/prices.parquet (one row per ticker per trading day).

# M1.2 — pull daily prices for every ticker in the universe
import pandas as pd
from pathlib import Path

UNIVERSE_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "universe.csv"
PRICES_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "prices.parquet"


universe = pd.read_csv(UNIVERSE_PATH)                             # the handoff from build_universe.py
tickers = universe["ticker"].tolist()

print(len(tickers))
print(tickers[:10])

# auto_adjust=True corrects prices for splits and dividends. Without it Apple's
# 2020 4-for-1 split reads as a 75% crash rather than a share count change.

# The .stack() call converts Yahoo's wide layout (one column per ticker-field pair)
# into long format: one row per date per ticker. That is the shape SQL wants.
import yfinance as yf
START = "2015-01-01"                                              # enough history to span more than one cycle
def download_long(ticker_list):
    df = yf.download(ticker_list, start=START, auto_adjust=True, progress=False)
    return df.stack(future_stack=True).reset_index()

import time

# Yahoo is an undocumented endpoint. Batching keeps any single failure cheap and
# the one-second pause keeps request volume low enough not to be throttled.
CHUNK_SIZE = 50

frames = []
for i in range(0, len(tickers), CHUNK_SIZE):

    chunk = tickers[i:i + CHUNK_SIZE]                             # 50 tickers at a time; the last chunk is short
    print(f"downloading {i + 1}-{i + len(chunk)}")
    frames.append(download_long(chunk))
    time.sleep(1)                                                 # be polite to a free service

# Stack the batches, then drop rows where a company had no price yet: yfinance
# lines every ticker up against a shared calendar and leaves blanks pre-IPO.
prices = pd.concat(frames, ignore_index=True)
prices = prices.dropna(subset=["Close"])                          # ~149k placeholder rows removed
print(prices.shape)
print(prices["Ticker"].nunique())

prices.to_parquet(PRICES_PATH, index=False)                       # parquet keeps dtypes and is ~3x smaller than CSV
print(f"wrote {len(prices):,} rows to {PRICES_PATH}")


