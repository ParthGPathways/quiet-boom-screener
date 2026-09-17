# M5 - generate the HTML dashboard from the finished screens.
#
# Renders three things into site/:
#
#   index.html            the industry league table, plus a growth-vs-valuation
#                         scatter whose quadrants are the whole thesis: top-left is
#                         accelerating and cheap, bottom-right is expensive and not
#                         growing
#   industry/<slug>.html  one page per industry, listing its companies with the
#                         figures behind the industry-level numbers
#
# Importing verdict.py re-runs the entire pipeline (boom score, quiet filter,
# valuation, DCF), so this single script regenerates the site from the database.
#
# Reads data/db/screener.db via verdict.py. Writes site/.

import re
import sys
from pathlib import Path

import pandas as pd
from jinja2 import Environment

sys.path.insert(0, str(Path(__file__).resolve().parent))

import boom_score
import dcf
import verdict

SITE_DIR = Path(__file__).resolve().parent.parent / "site"
INDUSTRY_DIR = SITE_DIR / "industry"


def slugify(name):
    """Turn an industry name into a safe filename: 'Gas Utilities' -> gas-utilities."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


table = verdict.combined.copy()
table["slug"] = [slugify(name) for name in table.index]

# Companies behind each industry, for the drill-down pages.
companies = dcf.dcf.copy()
companies["ev_ebitda"] = companies["ev_ebitda"].round(1)
companies["upside"] = companies["upside"].round(2)
companies["market_cap_bn"] = (companies["market_cap"] / 1e9).round(1)
companies["revenue_bn"] = (companies["revenue"] / 1e9).round(1)

# --- templates ------------------------------------------------------------------
# Kept inline rather than in separate files: the site is two templates, and one
# self-contained script is easier to hand to someone than a directory of fragments.

STYLE = """
:root { --ink:#16181d; --muted:#6b7280; --line:#e5e7eb; --bg:#ffffff;
        --good:#0f766e; --bad:#b91c1c; --accent:#1d4ed8; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
       font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif; }
.wrap { max-width:1100px; margin:0 auto; padding:40px 24px 80px; }
h1 { font-size:28px; margin:0 0 6px; letter-spacing:-0.02em; }
h2 { font-size:19px; margin:44px 0 12px; letter-spacing:-0.01em; }
.sub { color:var(--muted); margin:0 0 28px; }
table { border-collapse:collapse; width:100%; font-size:14px; }
th, td { padding:8px 10px; border-bottom:1px solid var(--line); text-align:right;
         white-space:nowrap; }
th:first-child, td:first-child { text-align:left; white-space:normal; }
th { font-weight:600; color:var(--muted); font-size:12px; text-transform:uppercase;
     letter-spacing:0.04em; border-bottom:1.5px solid var(--ink); }
tbody tr:hover { background:#f9fafb; }
.pos { color:var(--good); } .neg { color:var(--bad); }
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }
.scroll { overflow-x:auto; }
.note { color:var(--muted); font-size:13px; margin-top:10px; }
.back { display:inline-block; margin-bottom:18px; font-size:14px; }
figure { margin:0; }
"""


def signed(value, digits=2):
    """Render a number with a class so positive and negative read differently."""
    if pd.isna(value):
        return '<td class="muted">&mdash;</td>'
    cls = "pos" if value > 0 else "neg" if value < 0 else ""
    return f'<td class="{cls}">{value:+.{digits}f}</td>'


def plain(value, digits=1):
    return "<td>&mdash;</td>" if pd.isna(value) else f"<td>{value:.{digits}f}</td>"


INDEX_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Quiet Boom Screener</title><style>{{ style }}</style></head>
<body><div class="wrap">
<h1>Quiet Boom Screener</h1>
<p class="sub">US industries growing faster than they normally do, without an AI
narrative attached &mdash; and whether the market has noticed.
{{ n_industries }} industries from {{ n_companies }} S&amp;P 500 and 400 companies.</p>

<h2>Growth vs valuation</h2>
<figure>{{ scatter }}</figure>
<p class="note">Horizontal: revenue growth acceleration, in percentage points above
the industry's own long-run rate. Vertical: EV/EBITDA. Bubble size is company count.
Blue = moves against the AI trade, grey = moves with it. The top-left quadrant is
the thesis: accelerating and still cheap.</p>

<h2>League table</h2>
<div class="scroll"><table>
<thead><tr>
<th>Industry</th><th>n</th><th>Verdict</th><th>Quiet boom</th><th>Accel</th>
<th>AI corr</th><th>EV/EBITDA</th><th>DCF</th><th>Breadth</th>
</tr></thead>
<tbody>{{ rows }}</tbody>
</table></div>
<p class="note">Verdict combines the growth signal with cheapness. Accel is
percentage points of revenue growth above the industry's long-run rate. AI corr is
correlation with an AI basket after market movement is removed &mdash; lower is
quieter. EV/EBITDA is blank for financials, where it does not apply.</p>
</div></body></html>"""

INDUSTRY_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ name }} &mdash; Quiet Boom Screener</title><style>{{ style }}</style></head>
<body><div class="wrap">
<a class="back" href="../index.html">&larr; All industries</a>
<h1>{{ name }}</h1>
<p class="sub">{{ n }} companies &middot; verdict {{ verdict }} &middot;
acceleration {{ accel }} pts &middot; AI correlation {{ ai_corr }}</p>
<h2>Companies</h2>
<div class="scroll"><table>
<thead><tr><th>Company</th><th>Ticker</th><th>Mkt cap $bn</th><th>Revenue $bn</th>
<th>EV/EBITDA</th><th>DCF upside</th><th>Beta</th><th>WACC</th></tr></thead>
<tbody>{{ rows }}</tbody>
</table></div>
<p class="note">DCF upside above 1.00 means the discounted cash flows imply a higher
enterprise value than the market is paying. Blank where free cash flow is negative
or inputs are missing.</p>
</div></body></html>"""


# --- scatter --------------------------------------------------------------------
# Drawn as inline SVG rather than with a charting library: no network dependency,
# no build step, and the file opens correctly from disk years from now.

def nice_ticks(low, high, target=6):
    """Round tick positions covering [low, high], roughly `target` of them."""
    span = high - low
    if span <= 0:
        return [low]
    raw = span / target
    magnitude = 10 ** int(pd.np.floor(pd.np.log10(raw))) if hasattr(pd, "np") else None
    import math
    magnitude = 10 ** math.floor(math.log10(raw))
    for multiple in (1, 2, 2.5, 5, 10):
        step = magnitude * multiple
        if span / step <= target:
            break
    first = math.ceil(low / step) * step
    ticks, value = [], first
    while value <= high + 1e-9:
        ticks.append(round(value, 6))
        value += step
    return ticks


def build_scatter(frame, width=980, height=520, pad_left=70, pad=58):
    """Scatter of growth acceleration against EV/EBITDA.

    Bubbles are numbered by league-table rank rather than labelled with names: at
    19 industries the names collide badly, and the table beneath the chart already
    carries them, so the number is a key into it.
    """
    points = frame.dropna(subset=["acceleration", "ev_ebitda"]).copy()
    if points.empty:
        return "<p class='note'>No industries have both a growth signal and a multiple.</p>"
    points["rank"] = [list(frame.index).index(name) + 1 for name in points.index]

    x_min, x_max = points["acceleration"].min(), points["acceleration"].max()
    y_min, y_max = points["ev_ebitda"].min(), points["ev_ebitda"].max()
    x_pad = (x_max - x_min) * 0.12 or 1
    y_pad = (y_max - y_min) * 0.12 or 1
    x_min, x_max = x_min - x_pad, x_max + x_pad
    y_min, y_max = y_min - y_pad, y_max + y_pad

    def sx(v):
        return pad_left + (v - x_min) / (x_max - x_min) * (width - pad_left - pad)

    def sy(v):  # inverted: a cheaper multiple sits higher on the page
        return height - pad - (v - y_min) / (y_max - y_min) * (height - 2 * pad)

    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
           f'aria-label="Growth acceleration against EV/EBITDA by industry" '
           f'style="max-width:{width}px">',
           f'<rect width="{width}" height="{height}" fill="#fff"/>']

    # Dividers at the MEDIAN of each axis. A line at zero acceleration would sit off
    # the chart entirely, because every industry here is already gated to positive.
    mid_x = points["acceleration"].median()
    mid_y = points["ev_ebitda"].median()
    out.append(f'<line x1="{sx(mid_x):.1f}" y1="{pad}" x2="{sx(mid_x):.1f}" '
               f'y2="{height-pad}" stroke="#d1d5db" stroke-dasharray="4 4"/>')
    out.append(f'<line x1="{pad_left}" y1="{sy(mid_y):.1f}" x2="{width-pad}" '
               f'y2="{sy(mid_y):.1f}" stroke="#d1d5db" stroke-dasharray="4 4"/>')
    out.append(f'<text x="{pad_left+8}" y="{pad+14}" font-size="11" fill="#9ca3af">'
               f'cheaper &amp; faster growing</text>')

    for tick in nice_ticks(x_min, x_max):
        out.append(f'<line x1="{sx(tick):.1f}" y1="{height-pad}" x2="{sx(tick):.1f}" '
                   f'y2="{height-pad+5}" stroke="#9ca3af"/>')
        out.append(f'<text x="{sx(tick):.1f}" y="{height-pad+19}" font-size="11" '
                   f'fill="#6b7280" text-anchor="middle">{tick:+g}</text>')
    for tick in nice_ticks(y_min, y_max):
        out.append(f'<line x1="{pad_left-5}" y1="{sy(tick):.1f}" x2="{pad_left}" '
                   f'y2="{sy(tick):.1f}" stroke="#9ca3af"/>')
        out.append(f'<text x="{pad_left-10}" y="{sy(tick)+4:.1f}" font-size="11" '
                   f'fill="#6b7280" text-anchor="end">{tick:g}x</text>')

    out.append(f'<line x1="{pad_left}" y1="{height-pad}" x2="{width-pad}" '
               f'y2="{height-pad}" stroke="#16181d"/>')
    out.append(f'<line x1="{pad_left}" y1="{pad}" x2="{pad_left}" y2="{height-pad}" '
               f'stroke="#16181d"/>')
    out.append(f'<text x="{(pad_left+width-pad)/2:.0f}" y="{height-14}" font-size="12" '
               f'fill="#6b7280" text-anchor="middle">growth acceleration '
               f'(percentage points above the industry\'s own long-run rate)</text>')
    out.append(f'<text transform="translate(18,{height/2:.0f}) rotate(-90)" font-size="12" '
               f'fill="#6b7280" text-anchor="middle">EV / EBITDA '
               f'(cheaper is higher)</text>')

    biggest = points["companies"].max()
    for name, row in points.sort_values("companies", ascending=False).iterrows():
        radius = max(11, 9 + 12 * (row["companies"] / biggest) ** 0.5)
        quiet = pd.notna(row["ai_correlation"]) and row["ai_correlation"] < 0
        fill, edge = ("#1d4ed8", "#1e40af") if quiet else ("#9ca3af", "#6b7280")
        cx, cy = sx(row["acceleration"]), sy(row["ev_ebitda"])
        out.append(
            f'<g><circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius:.1f}" fill="{fill}" '
            f'fill-opacity="0.55" stroke="{edge}"/>'
            f'<text x="{cx:.1f}" y="{cy+4:.1f}" font-size="11.5" font-weight="600" '
            f'fill="#111827" text-anchor="middle">{int(row["rank"])}</text>'
            f'<title>{int(row["rank"])}. {name}\n'
            f'acceleration {row["acceleration"]:+.1f} pts\n'
            f'EV/EBITDA {row["ev_ebitda"]:.1f}x\n'
            f'AI correlation {row["ai_correlation"]:+.2f}\n'
            f'{int(row["companies"])} companies</title></g>'
        )

    # Legend for the colour, which is otherwise unexplained inside the image.
    out.append(f'<g transform="translate({width-pad-215},{pad-14})">'
               f'<circle cx="8" cy="0" r="7" fill="#1d4ed8" fill-opacity="0.55" stroke="#1e40af"/>'
               f'<text x="22" y="4" font-size="11.5" fill="#374151">moves against the AI trade</text>'
               f'<circle cx="8" cy="20" r="7" fill="#9ca3af" fill-opacity="0.55" stroke="#6b7280"/>'
               f'<text x="22" y="24" font-size="11.5" fill="#374151">moves with it</text></g>')

    out.append("</svg>")
    return "".join(out)


# --- render ---------------------------------------------------------------------

environment = Environment(autoescape=False)
SITE_DIR.mkdir(exist_ok=True)
INDUSTRY_DIR.mkdir(exist_ok=True)

index_rows = []
for name, row in table.iterrows():
    index_rows.append(
        f'<tr><td><a href="industry/{row["slug"]}.html">{name}</a></td>'
        f'<td>{int(row["companies"])}</td>'
        + signed(row["verdict_score"])
        + signed(row["quiet_boom"])
        + signed(row["acceleration"], 1)
        + signed(row["ai_correlation"])
        + plain(row["ev_ebitda"])
        + plain(row["dcf_upside"], 2)
        + plain(row["breadth"], 2)
        + "</tr>"
    )

(SITE_DIR / "index.html").write_text(
    environment.from_string(INDEX_TEMPLATE).render(
        style=STYLE,
        scatter=build_scatter(table),
        rows="".join(index_rows),
        n_industries=len(table),
        n_companies=len(dcf.dcf),
    )
)

for name, row in table.iterrows():
    members = companies[companies["sub_industry"] == name].sort_values(
        "market_cap_bn", ascending=False
    )
    company_rows = []
    for _, member in members.iterrows():
        company_rows.append(
            f'<tr><td>{member["name"]}</td><td>{member["ticker"]}</td>'
            + plain(member["market_cap_bn"])
            + plain(member["revenue_bn"])
            + plain(member["ev_ebitda"])
            + plain(member["upside"], 2)
            + plain(member["beta"], 2)
            + plain(member["wacc"] * 100, 1)
            + "</tr>"
        )
    (INDUSTRY_DIR / f"{row['slug']}.html").write_text(
        environment.from_string(INDUSTRY_TEMPLATE).render(
            style=STYLE,
            name=name,
            n=int(row["companies"]),
            verdict=f'{row["verdict_score"]:+.2f}',
            accel=f'{row["acceleration"]:+.1f}',
            ai_corr=f'{row["ai_correlation"]:+.2f}',
            rows="".join(company_rows),
        )
    )

print(f"wrote {SITE_DIR/'index.html'} and {len(table)} industry pages")


# --- README results block -------------------------------------------------------
# The README is the front page of the repo, so it should show the actual output
# rather than describe it. Both the chart and the table are regenerated here, which
# keeps them from going stale the moment anything upstream changes.

DOCS_DIR = SITE_DIR.parent / "docs"
README_PATH = SITE_DIR.parent / "README.md"
START_MARKER = "<!-- RESULTS:START -->"
END_MARKER = "<!-- RESULTS:END -->"

DOCS_DIR.mkdir(exist_ok=True)
(DOCS_DIR / "scatter.svg").write_text(build_scatter(table, width=980, height=440))


def markdown_cell(value, digits=2, sign=False):
    if pd.isna(value):
        return "—"
    return f"{value:+.{digits}f}" if sign else f"{value:.{digits}f}"


lines = [
    "| # | Industry | n | Verdict | Accel | AI corr | EV/EBITDA | Breadth |",
    "|---|---|---|---|---|---|---|---|",
]
for position, (name, row) in enumerate(table.head(10).iterrows(), start=1):
    lines.append(
        f'| {position} | {name} | {int(row["companies"])} '
        f'| {markdown_cell(row["verdict_score"], 2, sign=True)} '
        f'| {markdown_cell(row["acceleration"], 1, sign=True)} '
        f'| {markdown_cell(row["ai_correlation"], 2, sign=True)} '
        f'| {markdown_cell(row["ev_ebitda"], 1)} '
        f'| {markdown_cell(row["breadth"], 2)} |'
    )

bottom = table.tail(3)
loud = ", ".join(
    f'{name} ({row["ai_correlation"]:+.2f})' for name, row in bottom.iterrows()
)

# --- the funnel ----------------------------------------------------------------
# "Top 10 of 19 qualifying industries" does not tell a reader that 127 industries
# and several hundred companies were filtered out on the way. Counted here from the
# data rather than written down, so the figures cannot drift from the code.

_connection = __import__("sqlite3").connect(boom_score.DB_PATH)
_universe = pd.read_sql_query("SELECT cik, sub_industry FROM companies", _connection)
_tickers = pd.read_sql_query("SELECT COUNT(*) AS n FROM companies", _connection)["n"][0]
_connection.close()

_recent = boom_score.facts[
    boom_score.facts["year"].between(boom_score.RECENT_FROM, boom_score.RECENT_TO)
]
_measurable = _recent.dropna(subset=["growth"])
_big_enough = (_measurable.groupby("sub_industry")["cik"].nunique() >= boom_score.MIN_COMPANIES).sum()

_qualifying = set(table.index)
_rejected = _universe[~_universe["sub_industry"].isin(_qualifying)]

funnel_rows = [
    ("Tickers in the universe (S&P 500 + 400)", _tickers),
    ("Distinct filers (dual-class tickers share one CIK)", _universe["cik"].nunique()),
    ("Sub-industries", _universe["sub_industry"].nunique()),
    (f"... with at least {boom_score.MIN_COMPANIES} companies that have a usable growth figure", int(_big_enough)),
    (f"... and at least {boom_score.MIN_BREADTH:.0%} of those companies growing", len(boom_score.scores)),
    ("... and accelerating, with a price correlation available", len(table)),
]
funnel_md = "\n".join(
    f"| {label} | {value} |" for label, value in funnel_rows
)

plotted = table.dropna(subset=["acceleration", "ev_ebitda"])
absent = [
    f"{list(table.index).index(name) + 1}. {name}"
    for name in table.index if name not in plotted.index
]
missing_note = (
    f"{len(absent)} of {len(table)} industries are absent from the chart because "
    f"EV/EBITDA does not apply to financials: " + ", ".join(absent) + "."
) if absent else "All qualifying industries are plotted."

results_block = f"""{START_MARKER}
<!-- Generated by src/build_site.py - edits here are overwritten on rebuild. -->

![Growth acceleration against EV/EBITDA](docs/scatter.svg)

*Numbers are league-table ranks. Horizontal: revenue growth acceleration, percentage
points above the industry's own long-run rate. Vertical: EV/EBITDA, inverted so
cheaper sits higher. Bubble size is company count. Dashed lines mark the medians, so
the top-right quadrant is the thesis: growing faster than most, and cheaper than most.*

*{missing_note}*

### How {len(table)} industries were selected

| stage | count |
|---|---|
{funnel_md}

{_universe["sub_industry"].nunique() - len(table)} sub-industries were rejected, holding
{_rejected["cik"].nunique()} companies. The screen is a filter, not a description of
the whole market: an industry has to be large enough to generalise from, broadly
growing rather than carried by one name, and accelerating against its own history.

### Top {min(10, len(table))} of {len(table)} qualifying industries

{chr(10).join(lines)}

*Accel is percentage points of revenue growth above the industry's long-run rate.
AI corr is correlation with an AI basket after market movement is removed — lower is
quieter. EV/EBITDA is blank for financials, where it does not apply. Breadth is the
share of companies actually growing.*

Rejected at the loud end — genuinely accelerating, but the market already knows:
{loud}.
{END_MARKER}"""

if README_PATH.exists():
    readme = README_PATH.read_text()
    if START_MARKER in readme and END_MARKER in readme:
        before = readme.split(START_MARKER)[0]
        after = readme.split(END_MARKER)[1]
        README_PATH.write_text(before + results_block + after)
        print(f"updated results block in {README_PATH.name}")
    else:
        print(f"note: {README_PATH.name} has no RESULTS markers; block not inserted")
