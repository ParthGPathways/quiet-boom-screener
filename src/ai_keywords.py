# M3.2 (part 2) - how much does each industry TALK about AI in its filings?
#
# The correlation screen in quiet_filter.py measures what the market believes. This
# measures what companies say about themselves, which is independent evidence: a
# firm can be quietly re-rated by investors without changing its own language, and
# it can talk up AI without the market believing it.
#
# Method: fetch each company's most recent 10-K, isolate Item 1 (Business), and
# count AI terms per thousand words.
#
# Item 1 specifically, not the whole filing. Risk Factors discuss AI as a threat
# ("competitors may deploy artificial intelligence..."), which is close to the
# opposite of an AI growth narrative, and including it would score the worried
# alongside the enthusiastic.
#
# Per thousand words, not raw counts, because Item 1 lengths vary by an order of
# magnitude - 2,400 words for Apple against 13,500 for Coca-Cola.
#
# Companies whose Item 1 cannot be located are recorded as missing rather than
# falling back to the full document: a figure computed over a different section is
# not comparable, and a wrong number is worse than a gap.
#
# Reads data/raw/universe.csv. Writes data/raw/ai_keywords.parquet.
# Exposes `per_company` and `per_industry`.

import os
import re
import time
from pathlib import Path

import pandas as pd
import requests

HEADERS = {"User-Agent": os.environ.get("SEC_USER_AGENT", "p.goel10@lse.ac.uk")}

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
UNIVERSE_PATH = RAW_DIR / "universe.csv"
OUT_PATH = RAW_DIR / "ai_keywords.parquet"
CACHE_DIR = RAW_DIR / "tenk_cache"

# Multi-word phrases, counted case-insensitively. "AI" is handled separately below
# because lowercasing it collides with ordinary words.
AI_PHRASES = [
    "artificial intelligence",
    "machine learning",
    "generative ai",
    "large language model",
    "neural network",
    "deep learning",
    "genai",
    "gen ai",
]

# Item 1 and Item 1A appear many times in a 10-K - contents page, cross-references,
# the body. The body heading is the LAST occurrence, and the pair must be far enough
# apart to be a real section rather than two contents-page lines side by side.
MIN_SECTION_CHARS = 3000

REQUEST_PAUSE = 0.15  # SEC allows 10 requests/second; this stays well under


def to_text(html):
    """Strip tags and entities down to readable prose."""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"&[a-z#0-9]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def business_section(text):
    """Return Item 1 (Business), or None if its boundaries cannot be found."""
    starts = [m.end() for m in re.finditer(r"(?i)item\s*1\s*[\.\:\)]?\s*business", text)]
    ends = [m.start() for m in re.finditer(r"(?i)item\s*1a\s*[\.\:\)]?\s*risk", text)]
    for start in reversed(starts):
        for end in ends:
            if end - start >= MIN_SECTION_CHARS:
                return text[start:end]
    return None


def latest_10k_url(cik):
    """URL of a company's most recent 10-K primary document."""
    response = requests.get(
        f"https://data.sec.gov/submissions/CIK{cik:010d}.json", headers=HEADERS, timeout=30
    )
    response.raise_for_status()
    filings = response.json()["filings"]["recent"]
    for form, accession, document in zip(
        filings["form"], filings["accessionNumber"], filings["primaryDocument"]
    ):
        if form == "10-K" and document:
            return (
                f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                f"{accession.replace('-', '')}/{document}"
            ), accession
    return None, None


def count_ai_terms(section):
    """AI mentions in a block of text."""
    lowered = section.lower()
    phrases = sum(lowered.count(phrase) for phrase in AI_PHRASES)
    # Bare "AI" only as a standalone capitalised word, so that "said", "certain"
    # and similar do not contribute.
    bare = len(re.findall(r"\bAI\b", section))
    return phrases + bare


def measure_company(cik):
    """Words and AI mentions in one company's Item 1, or None if unavailable."""
    url, accession = latest_10k_url(cik)
    if url is None:
        return None
    time.sleep(REQUEST_PAUSE)
    response = requests.get(url, headers=HEADERS, timeout=60)
    response.raise_for_status()
    section = business_section(to_text(response.text))
    if section is None:
        return {"cik": cik, "accession": accession, "words": None, "ai_mentions": None}
    return {
        "cik": cik,
        "accession": accession,
        "words": len(section.split()),
        "ai_mentions": count_ai_terms(section),
    }


if __name__ == "__main__":
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    universe = pd.read_csv(UNIVERSE_PATH)

    rows, failures = [], []
    for position, (_, company) in enumerate(universe.iterrows(), start=1):
        cik = int(company["cik"])
        cached = CACHE_DIR / f"{cik}.json"

        if cached.exists():
            rows.append(pd.read_json(cached, typ="series").to_dict())
        else:
            try:
                measured = measure_company(cik)
                if measured is None:
                    failures.append((company["ticker"], "no 10-K on file"))
                else:
                    pd.Series(measured).to_json(cached)
                    rows.append(measured)
            except Exception as error:
                failures.append((company["ticker"], str(error)[:80]))
            time.sleep(REQUEST_PAUSE)

        if position % 50 == 0:
            print(f"{position}/{len(universe)}  ok={len(rows)}  failed={len(failures)}")

    measured = pd.DataFrame(rows).merge(
        universe[["cik", "ticker", "sub_industry"]], on="cik", how="left"
    )
    measured["ai_per_1k_words"] = (
        1000.0 * measured["ai_mentions"] / measured["words"]
    )

    temp_path = OUT_PATH.with_suffix(".parquet.tmp")
    measured.to_parquet(temp_path, index=False)
    temp_path.replace(OUT_PATH)

    usable = measured.dropna(subset=["ai_per_1k_words"])
    print(f"\n{len(measured)} companies fetched, {len(usable)} with a readable Item 1 "
          f"({100 * len(usable) / max(len(measured), 1):.0f}% coverage)")
    print(f"failures: {len(failures)}")
    print(f"wrote {OUT_PATH}")
