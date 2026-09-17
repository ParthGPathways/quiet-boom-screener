# M5.3 - rebuild everything with one command.
#
#   python src/rebuild.py            regenerate the site from the existing database
#   python src/rebuild.py --data     also reload the database from the raw files
#   python src/rebuild.py --fetch    also re-download everything first (slow)
#
# The default is deliberately the fast path. Downloading takes ~15 minutes and the
# underlying filings change a few times a quarter, so the common case is wanting the
# analysis and the site rebuilt, not the data refetched.
#
# Steps run in dependency order: each one's output is the next one's input.

import argparse
import subprocess
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent

# (script, description, tier) - tier 2 needs --fetch, tier 1 needs --data, 0 always
STEPS = [
    ("build_universe.py",     "scrape S&P 500 + 400 constituents, attach SEC CIKs", 2),
    ("fetch_prices.py",       "download 10 years of daily prices",                  2),
    ("fetch_fundamentals.py", "download quarterly fundamentals from EDGAR",         2),
    ("build_database.py",     "load the raw files into SQLite",                     1),
    ("build_site.py",         "run the screens and render the dashboard",           0),
]


def main():
    parser = argparse.ArgumentParser(description="Rebuild the Quiet Boom Screener.")
    parser.add_argument("--data", action="store_true",
                        help="reload the database from the raw files")
    parser.add_argument("--fetch", action="store_true",
                        help="re-download all source data first (implies --data)")
    args = parser.parse_args()

    # --fetch is useless without reloading the database afterwards.
    max_tier = 2 if args.fetch else 1 if args.data else 0
    steps = [s for s in STEPS if s[2] <= max_tier]

    print(f"running {len(steps)} step(s)\n")
    started = time.time()
    for index, (script, description, _) in enumerate(steps, start=1):
        print(f"[{index}/{len(steps)}] {script} - {description}")
        step_started = time.time()
        # check=True stops the whole rebuild if any step fails, rather than
        # carrying on and rendering a site from half-updated data.
        result = subprocess.run([sys.executable, str(SRC / script)], cwd=SRC)
        if result.returncode != 0:
            print(f"\nFAILED at {script} (exit {result.returncode}). Nothing further run.")
            return result.returncode
        print(f"        done in {time.time() - step_started:.0f}s\n")

    print(f"rebuilt in {time.time() - started:.0f}s")
    print(f"open {SRC.parent / 'site' / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
