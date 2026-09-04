# M1.2 — pull daily prices for every ticker in the universe
import pandas as pd
from pathlib import Path

UNIVERSE_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "universe.csv"
PRICES_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "prices.parquet"


universe = pd.read_csv(UNIVERSE_PATH)
tickers = universe["ticker"].tolist()

print(len(tickers))
print(tickers[:10])

import yfinance as yf
START = "2015-01-01"
def download_long(ticker_list):
    df = yf.download(ticker_list, start=START, auto_adjust=True, progress=False)
    return df.stack(future_stack=True).reset_index()

import time

CHUNK_SIZE = 50

frames = []
for i in range(0, len(tickers), CHUNK_SIZE):

    chunk = tickers[i:i + CHUNK_SIZE]
    print(f"downloading {i + 1}-{i + len(chunk)}")
    frames.append(download_long(chunk))
    time.sleep(1)

prices = pd.concat(frames, ignore_index=True)
prices = prices.dropna(subset=["Close"])
print(prices.shape)
print(prices["Ticker"].nunique())

prices.to_parquet(PRICES_PATH, index=False)
print(f"wrote {len(prices):,} rows to {PRICES_PATH}")


