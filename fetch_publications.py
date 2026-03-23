"""
fetch_publications.py — GitHub Action script to scrape Google Scholar
and generate data/publications.json

Run by: .github/workflows/update-publications.yml on a schedule.

WHY A PYTHON SCRIPT IN A GITHUB ACTION?
  Google Scholar has no public API. The `scholarly` library mimics a browser
  to scrape it. Running this server-side (in a GitHub Action) avoids browser
  CORS restrictions and rate-limit issues. The output is committed as a static
  JSON file, which the browser then fetches as a fast, cached resource.

  This is a common "JAMstack" pattern:
  (JavaScript + APIs + Markup, pre-built at deploy time)

Install locally to test:
  pip install scholarly
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

try:
    from scholarly import scholarly, ProxyGenerator
except ImportError:
    print("scholarly not installed. Run: pip install scholarly")
    sys.exit(1)


# ============================================================================
# CONFIGURATION — Set these via GitHub Actions secrets/variables
# ============================================================================

# Set this as a GitHub Actions variable (Settings > Variables > Actions):
# Name: GOOGLE_SCHOLAR_ID
# Value: the ID from your Scholar URL: ?user=XXXXXXXX
SCHOLAR_ID = os.environ.get("GOOGLE_SCHOLAR_ID", "")

# Optional: ScraperAPI key for better reliability (free tier available at scraperapi.com)
# Set as a GitHub Actions secret: SCRAPER_API_KEY
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "")

# Output path — relative to repo root, served as a static file
OUTPUT_FILE = Path("data/publications.json")


# ============================================================================
# PROXY SETUP
# Using a proxy reduces the chance of Google Scholar rate-limiting the scraper.
# ScraperAPI has a free tier (1000 req/month) which is plenty for this use case.
# ============================================================================

def setup_proxy():
    """Configure scholarly to use a proxy if available."""
    if SCRAPER_API_KEY:
        pg = ProxyGenerator()
        success = pg.ScraperAPI(SCRAPER_API_KEY)
        if success:
            scholarly.use_proxy(pg)
            print("Proxy configured via ScraperAPI.")
        else:
            print("Warning: ProxyGenerator setup failed. Proceeding without proxy.")
    else:
        print("No SCRAPER_API_KEY set. Fetching directly (may be rate-limited).")


# ============================================================================
# SCHOLAR SCRAPING
# ============================================================================

def fetch_scholar_publications(scholar_id: str) -> list[dict]:
    """
    Fetches all publications from a Google Scholar profile.

    Returns a list of normalized publication dicts that match the format
    expected by script.js — this is the "contract" between the Python
    backend and the JavaScript frontend.
    """
    if not scholar_id:
        print("No GOOGLE_SCHOLAR_ID set. Skipping Scholar fetch.")
        return []

    print(f"Fetching Scholar profile: {scholar_id}")
    author = scholarly.search_author_id(scholar_id)

    # scholarly.fill() fetches the full profile including publication list.
    # sections=['publications'] limits what's fetched to reduce API calls.
    author = scholarly.fill(author, sections=["publications"])

    publications = []
    pub_list = author.get("publications", [])
    print(f"Found {len(pub_list)} publications. Fetching details...")

    for i, pub_summary in enumerate(pub_list):
        try:
            # Fetch full details for each publication (title, authors, venue, year, DOI)
            pub = scholarly.fill(pub_summary)
            bib = pub.get("bib", {})

            # Normalize to our internal format — same fields as the ORCID normalizer
            entry = {
                "title":   bib.get("title", "Untitled"),
                "year":    str(bib.get("pub_year", "")) or None,
                "venue":   bib.get("venue") or bib.get("journal") or bib.get("booktitle"),
                "authors": _parse_authors(bib.get("author", "")),
                "doi":     pub.get("pub_url", "").split("doi.org/")[-1] if "doi.org" in pub.get("pub_url", "") else None,
                "url":     pub.get("pub_url"),
                "pubType": _infer_type(bib),
                # Citation count is Scholar-specific and not in ORCID data
                "citations": pub.get("num_citations", 0),
                "_source": "google_scholar",
            }
            publications.append(entry)
            print(f"  [{i+1}/{len(pub_list)}] {entry['title'][:60]}...")

        except Exception as e:
            print(f"  Warning: Could not fetch details for publication {i+1}: {e}")
            continue

    return publications


def _parse_authors(author_string: str) -> list[str]:
    """
    Parse Scholar's author string (comma or 'and'-separated) into a list.
    e.g. "Alice Smith, Bob Jones and Carol White" -> ["Alice Smith", "Bob Jones", "Carol White"]
    """
    if not author_string:
        return []
    # Replace ' and ' with comma, then split
    normalized = author_string.replace(" and ", ", ")
    return [a.strip() for a in normalized.split(",") if a.strip()]


def _infer_type(bib: dict) -> str:
    """Infer publication type from Scholar bib fields."""
    if bib.get("journal"):
        return "journal-article"
    if bib.get("booktitle"):
        return "conference-paper"
    if "arXiv" in bib.get("venue", "") or "arxiv" in bib.get("url", "").lower():
        return "preprint"
    return "other"


# ============================================================================
# OUTPUT
# ============================================================================

def save_publications(publications: list[dict], output_path: Path):
    """Write publications to a JSON file with metadata."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output = {
        # ISO 8601 timestamp so the website can show "last updated"
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
        "count": len(publications),
        "publications": publications,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        # indent=2 for human-readable JSON; separators default is fine
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(publications)} publications to {output_path}")


def main():
    setup_proxy()

    publications = fetch_scholar_publications(SCHOLAR_ID)

    if not publications:
        print("No publications fetched. Check your GOOGLE_SCHOLAR_ID.")
        # Still write an empty file so the website doesn't fail on fetch
        save_publications([], OUTPUT_FILE)
        return

    save_publications(publications, OUTPUT_FILE)
    print("Done.")


if __name__ == "__main__":
    main()
