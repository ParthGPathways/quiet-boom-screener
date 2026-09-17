# M2 - load the three raw files into a SQLite database.

# Creates the schema, then loads universe.csv, prices.parquet and
# fundamentals.parquet into it. Safe to re-run: each table is emptied and
# refilled, which keeps the constraints below intact (unlike if_exists='replace',
# which would silently drop the table and rebuild it without them).

# Output: data/db/screener.db

# M2 — load the raw files into SQLite
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "db" / "screener.db"

# Primary keys here are not decoration - they are enforced. The fundamentals key
# is what physically prevents the dual-class duplicate rows from being stored.

# Note fundamentals has no FOREIGN KEY on cik: a foreign key must point at a
# unique column, and cik is not unique in companies (GOOG and GOOGL share one).
# The index below stands in for it so joins stay fast.
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

# data/db/ is not in version control, so create it before SQLite tries to open a
# file inside it.
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

connection = sqlite3.connect(DB_PATH)                                   # creates the file if it does not exist
connection.executescript(SCHEMA)                                        # executescript runs several statements at once
connection.commit()

import pandas as pd

RAW_DIR = DB_PATH.parent.parent / "raw"

# companies: 903 rows, loaded as-is (CSV headers already match the schema).
companies = pd.read_csv(RAW_DIR / "universe.csv")

connection.execute("DELETE FROM companies")                             # empty the table but keep its rules
companies.to_sql("companies", connection, if_exists="append", index=False) # append, never replace
connection.commit()

count = connection.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
print("companies:", count)

print(connection.execute(
    "SELECT ticker, name, sector FROM companies LIMIT 3"
).fetchall())

# prices: ~2.5m rows. Two adjustments needed - yfinance capitalises its column
# names, and SQLite has no date type, so dates are stored as YYYY-MM-DD text
# (which sorts correctly precisely because the format runs largest unit first).
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
prices["date"] = prices["date"].dt.strftime("%Y-%m-%d")                 # drop the meaningless midnight timestamp

connection.execute("DELETE FROM prices")
prices.to_sql("prices", connection, if_exists="append", index=False, chunksize=50_000) # chunked: 2.5m rows in one statement is too big
connection.commit()

print("prices:", connection.execute("SELECT COUNT(*) FROM prices").fetchone()[0])

# fundamentals: ~205k rows. The ticker column is dropped here on purpose -
# revenue is a fact about the filing entity, not about a share class, so Alphabet
# must appear once rather than twice.
fundamentals = pd.read_parquet(RAW_DIR / "fundamentals.parquet")
fundamentals = fundamentals.rename(columns={"end": "period_end"})
fundamentals["period_end"] = fundamentals["period_end"].dt.strftime("%Y-%m-%d")
fundamentals = fundamentals[["cik", "period_end", "metric", "val"]]
fundamentals = fundamentals.drop_duplicates(subset=["cik", "period_end", "metric"]) # the subset IS the primary key

# Some derived quarters are arithmetic residuals: a restated annual figure minus
# an un-restated 9-month figure. Drop them rather than store a wrong number.
# Metrics that cannot legitimately be negative, and where a value far below the
# year's own average is an arithmetic residual rather than a real figure. Operating
# income and net income are excluded because losses are real.
NON_NEGATIVE = ["revenue", "capex", "d_and_a", "shares_diluted"]

# Stricter still: these cannot be zero either. A quarter with no capex is possible;
# a company with no shares is not. Zeros here survive the rule above because when
# every quarter of a year is zero the year average is zero too, and nothing is
# "below 2% of zero".
STRICTLY_POSITIVE = ["shares_diluted"]

# Some filers tag share counts in thousands or millions rather than actual shares:
# McDonald's reports 711 (meaning 711 million), Nutanix 287,481 (meaning 287
# million). The mis-scaling is persistent per company, so an earlier quarter is no
# help, and it makes market capitalisation wrong by a factor of 1,000 or 1,000,000.
#
# The scale could be guessed - multiply until the number looks sensible - but that
# invents data. Dropping costs 4 companies out of ~880 and every industry figure
# here is a median, so the loss is negligible against the risk of a silently wrong
# market cap.
#
# 1,000,000 is comfortably clear of both sides: the mis-scaled values are all under
# 300,000, while the smallest genuine count in the universe is NVR at 2.8 million
# (a real company that has never split its stock).
MIN_SHARES = 1_000_000

year = fundamentals["period_end"].str.slice(0, 4)
year_avg = fundamentals.groupby(["cik", "metric", year])["val"].transform("mean") # transform keeps one value per row, not per group

is_flow = fundamentals["metric"].isin(NON_NEGATIVE)
bad = is_flow & ((fundamentals["val"] < 0) | (fundamentals["val"] < year_avg * 0.02))
bad = bad | (fundamentals["metric"].isin(STRICTLY_POSITIVE) & (fundamentals["val"] <= 0))
bad = bad | (fundamentals["metric"].eq("shares_diluted") & (fundamentals["val"] < MIN_SHARES)) # negative is impossible; <2% is the residual cliff

bad_quarters = set(zip(
    fundamentals.loc[bad & fundamentals["metric"].eq("revenue"), "cik"],
    fundamentals.loc[bad & fundamentals["metric"].eq("revenue"), "period_end"],
))
in_bad_quarter = pd.Series(
    [(c, p) in bad_quarters for c, p in zip(fundamentals["cik"], fundamentals["period_end"])],
    index=fundamentals.index,
)
bad_oi = fundamentals["metric"].eq("operating_income") & in_bad_quarter # losses are real, so judge it by revenue instead

print(f"dropping {int((bad | bad_oi).sum()):,} implausible rows")
fundamentals = fundamentals[~(bad | bad_oi)]                            # ~ means not: keep everything else


connection.execute("DELETE FROM fundamentals")
fundamentals.to_sql("fundamentals", connection, if_exists="append", index=False, chunksize=50_000)
connection.commit()

print("fundamentals:", connection.execute("SELECT COUNT(*) FROM fundamentals").fetchone()[0])


connection.close()                                                      # flush and release the database file
