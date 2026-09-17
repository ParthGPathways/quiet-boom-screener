# Quiet Boom Screener — Roadmap

**The question:** Which US industries are growing fast *without* an AI narrative attached —
and is the market underpricing that growth?

**Universe:** S&P 500 + S&P 400 midcaps (~900 companies)
**Stack:** Python (pandas) · SQLite (SQL) · HTML (generated dashboard)
**Goal:** CV-ready artifact for 2027 summer internship applications (started Aug 2026)

---

## Milestones

Each milestone is independently CV-mentionable — the project has value even mid-build.

### M1 — Data pipeline (Python)
- [x] 1.1 Build the universe: scrape S&P 500 + 400 constituent lists → `data/raw/universe.csv`
- [x] 1.2 Pull daily prices for all tickers via yfinance → parquet/CSV
- [x] 1.3 Pull quarterly fundamentals (revenue, EBITDA, capex, debt) from SEC EDGAR companyfacts
  - known gaps: 20 banks/financials use different revenue tags; GOOG/GOOGL, FOX/FOXA, NWS/NWSA duplicate one CIK; OZK 404s
- **Concepts:** DataFrames, loops/functions, APIs & JSON, rate limiting

### M2 — Database (SQL)
- [x] 2.1 Design schema: companies / prices / fundamentals / industries → `data/db/screener.db`
- [x] 2.2 Load all raw data into SQLite from Python
- [x] 2.3 Core queries: revenue growth by industry, margin trends (GROUP BY, JOINs, window functions)
  - note: join fundamentals via a one-row-per-CIK CTE (dual-class tickers fan out otherwise)
  - note: `HAVING quarters = 4` excludes partial years; TTM would be the upgrade
- **Concepts:** relational schema design, SQL joins/aggregation/window functions

### M3 — The screens (Python + SQL)
- [x] 3.1 Boom score: growth acceleration, margin expansion, capex cycle by industry
  - `src/boom_score.py`; median company (not aggregate), sub-industries with >=5 companies
  - breadth (>=70% of companies growing) is a gate, not a scored component
  - rates compared to a long baseline (2017-23), levels to a short one (2021-23)
- [x] 3.2 Quiet filter: correlation vs AI basket (`src/quiet_filter.py`)
  - AI factor = 19-name equal-weighted basket MINUS equal-weighted universe, so market beta is removed
  - 10-K keyword screen not built: the correlation screen already separated loud from quiet cleanly
- [x] 3.3 Ranked "quiet boom" industry table (`src/rank_industries.py`)
  - quiet_boom = z(boom_score) - z(ai_correlation), gated on acceleration > 0
  - 19 industries qualify; utilities lead on capex, insurance on premium-cycle growth
- **Concepts:** feature construction, z-scores/ranking, text screening, return correlation

### M4 — Valuation models (finance core)
- [ ] 4.1 Comps: EV/EBITDA, P/E vs growth within surviving industries
- [ ] 4.2 Simplified DCF per company (FCF projection, WACC, terminal value)
- [ ] 4.3 Cheap-vs-growth verdict per industry
- **Concepts:** enterprise value, multiples, DCF mechanics, WACC

### M5 — HTML dashboard
- [ ] 5.1 Industry league table + growth-vs-valuation "quiet boom quadrant" scatter
- [ ] 5.2 Per-industry drill-down pages with charts
- [ ] 5.3 One-command rebuild: data refresh → site regenerates
- **Concepts:** HTML/CSS basics, templating (Jinja2), charts

---

## How sessions run (mentor mode, fast variant)
1. Claude explains the concept — concise but interview-defensible
2. You write the code against a spec (escalating hints: nudge → pseudocode → near-solution)
3. Claude reviews, you fix, milestone box gets ticked

Scaffolding (folders, venv, config) is Claude's job. Analytical code is yours.

## Project layout
```
Test Project 2/
  data/raw/       ← CSVs & JSON as downloaded
  data/db/        ← screener.db (SQLite)
  src/            ← your Python scripts (one per pipeline step)
  site/           ← generated HTML output
  .venv/          ← Python environment (activate: source .venv/bin/activate)
```
