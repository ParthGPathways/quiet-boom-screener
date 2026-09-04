# M2 — load the raw files into SQLite
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "db" / "screener.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    ticker           TEXT PRIMARY KEY,
    cik              INTEGER NOT NULL,
    name             TEXT NOT NULL,
    sector           TEXT,
    sub_industry     TEXT,
    index_membership TEXT
);

CREATE INDEX IF NOT EXISTS idx_companies_cik ON companies(cik);

CREATE TABLE IF NOT EXISTS prices (
    ticker  TEXT NOT NULL,
    date    TEXT NOT NULL,
    open    REAL,
    high    REAL,
    low     REAL,
    close   REAL,
    volume  REAL,
    PRIMARY KEY (ticker, date),
    FOREIGN KEY (ticker) REFERENCES companies(ticker)
);

CREATE TABLE IF NOT EXISTS fundamentals (
    cik         INTEGER NOT NULL,
    period_end  TEXT NOT NULL,
    metric      TEXT NOT NULL,
    val         REAL,
    PRIMARY KEY (cik, period_end, metric)
);
"""

connection = sqlite3.connect(DB_PATH)
connection.executescript(SCHEMA)
connection.commit()

import pandas as pd

RAW_DIR = DB_PATH.parent.parent / "raw"

companies = pd.read_csv(RAW_DIR / "universe.csv")

connection.execute("DELETE FROM companies")
companies.to_sql("companies", connection, if_exists="append", index=False)
connection.commit()

count = connection.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
print("companies:", count)

print(connection.execute(
    "SELECT ticker, name, sector FROM companies LIMIT 3"
).fetchall())

prices = pd.read_parquet(RAW_DIR / "prices.parquet")
prices = prices.rename(columns={
    "Date": "date",
    "Ticker": "ticker",
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "volume",
})
prices["date"] = prices["date"].dt.strftime("%Y-%m-%d")

connection.execute("DELETE FROM prices")
prices.to_sql("prices", connection, if_exists="append", index=False, chunksize=50_000)
connection.commit()

print("prices:", connection.execute("SELECT COUNT(*) FROM prices").fetchone()[0])

fundamentals = pd.read_parquet(RAW_DIR / "fundamentals.parquet")
fundamentals = fundamentals.rename(columns={"end": "period_end"})
fundamentals["period_end"] = fundamentals["period_end"].dt.strftime("%Y-%m-%d")
fundamentals = fundamentals[["cik", "period_end", "metric", "val"]]
fundamentals = fundamentals.drop_duplicates(subset=["cik", "period_end", "metric"])

connection.execute("DELETE FROM fundamentals")
fundamentals.to_sql("fundamentals", connection, if_exists="append", index=False, chunksize=50_000)
connection.commit()

print("fundamentals:", connection.execute("SELECT COUNT(*) FROM fundamentals").fetchone()[0])


connection.close()

# M2 — load the raw files into SQLite
