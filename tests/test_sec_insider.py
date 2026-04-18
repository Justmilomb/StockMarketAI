"""Offline parsing test — sample atom feed fixture."""
from __future__ import annotations

from core.scrapers.sec_insider import parse_form4_atom

SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>4 - ELON MUSK (0001494730) - CIK 0001318605</title>
    <link href="https://www.sec.gov/Archives/edgar/data/1318605/000149473024000001/0001494730-24-000001-index.htm"/>
    <updated>2026-04-10T00:00:00-04:00</updated>
    <summary type="html">&lt;b&gt;Filing Date&lt;/b&gt;: 2026-04-10</summary>
    <category term="4" label="form type" />
  </entry>
  <entry>
    <title>4 - JANE DOE (0002) - CIK 0001318605</title>
    <link href="https://www.sec.gov/Archives/edgar/data/foo.htm"/>
    <updated>2026-04-09T00:00:00-04:00</updated>
    <summary type="html">Filing Date: 2026-04-09</summary>
  </entry>
</feed>"""


def test_parse_form4_atom_extracts_entries():
    out = parse_form4_atom(SAMPLE, ticker="TSLA")
    assert len(out) == 2
    assert out[0]["ticker"] == "TSLA"
    assert "MUSK" in out[0]["title"].upper()
    assert out[0]["filing_date"] == "2026-04-10"
    assert out[0]["url"].startswith("https://www.sec.gov/")


def test_parse_form4_atom_empty_input():
    assert parse_form4_atom("", ticker="TSLA") == []
