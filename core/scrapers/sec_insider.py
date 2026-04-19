"""SEC EDGAR Form 4 insider filings scraper.

Pulls the free Atom feed for a given ticker. Parsing is regex-only so we
don't add a new dependency.

The feed gives filing metadata but not transaction volume; for the
latter we'd need to pull the .htm primary doc and parse the inline XBRL.
That's out of scope here — the agent gets filing ticker, insider name,
filing date, and a direct link, which is enough for "institutional
front-running" style signals.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

EDGAR_SEARCH_TEMPLATE: str = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=4"
    "&dateb=&owner=include&count=40&output=atom&CIK={ticker}"
)

# SEC requires a descriptive, contact-bearing User-Agent for programmatic access.
SEC_USER_AGENT: str = "Blank Research contact@certifiedrandom.studios"


def parse_form4_atom(xml_text: str, ticker: str) -> List[Dict[str, Any]]:
    """Parse SEC's Atom feed into simple dicts. Regex-only (no xml dep)."""
    entries: List[Dict[str, Any]] = []
    entry_blocks = re.findall(r"<entry>(.*?)</entry>", xml_text, flags=re.DOTALL)
    for block in entry_blocks:
        title_match = re.search(r"<title>(.*?)</title>", block, flags=re.DOTALL)
        link_match = re.search(r'<link[^>]*href="([^"]+)"', block)
        updated_match = re.search(r"<updated>(.*?)</updated>", block)
        summary_match = re.search(r"<summary[^>]*>(.*?)</summary>", block, flags=re.DOTALL)

        title = title_match.group(1).strip() if title_match else ""
        link = link_match.group(1).strip() if link_match else ""
        updated = updated_match.group(1).strip() if updated_match else ""
        summary = summary_match.group(1).strip() if summary_match else ""

        filing_date = _extract_filing_date(summary) or updated
        entries.append({
            "ticker": ticker.upper(),
            "title": title,
            "url": link,
            "filing_date": filing_date,
            "summary": summary,
        })
    return entries


def _extract_filing_date(summary: str) -> Optional[str]:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", summary)
    return match.group(1) if match else None


def fetch_form4(ticker: str, timeout: float = 10.0) -> List[Dict[str, Any]]:
    """Fetch + parse Form 4 filings for *ticker*. Empty list on failure."""
    url = EDGAR_SEARCH_TEMPLATE.format(ticker=ticker.upper())
    try:
        resp = requests.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=timeout)
        resp.raise_for_status()
    except Exception as e:
        logger.info("sec_insider: fetch failed for %s: %s", ticker, e)
        return []
    return parse_form4_atom(resp.text, ticker)
