# SEC_EDGAR_Filings_downloader

## What this does

A small Python script that downloads SEC filings and their exhibits directly
from EDGAR, the SEC's public filing database, for any company and any form
type.

I built this to pull Frontline plc's 20-F annual report and 6-K interim
filings for an investment analysis. It generalizes to any company and any
form type though (10-K, 10-Q, 8-K, and so on).

**Why this is more than a simple "download the latest filing" script:**
company filings, especially 6-Ks for foreign private issuers, are structured
awkwardly. The main filing document is often close to empty, and the real
financial statements sit in an exhibit attached to it (commonly labeled
EX-1 or EX-99). A script that only grabs the primary document misses the
data entirely. This one reads each filing's own index page, finds every
document SEC has labeled inside it, and pulls the exhibits you actually
want alongside the main filing.

**What it does, step by step:**

1. Looks up a company's CIK (SEC's internal company ID) by name, or uses one
   you supply directly.
2. Pulls the company's full filing history from SEC's submissions API,
   including older filings that live in paginated archive files rather than
   the main "recent filings" list.
3. Filters to the form types and date range you specify.
4. For each matching filing, reads its index page to find every document
   inside it and downloads the primary document plus any exhibits matching
   a type filter you set (for example EX-1 for press releases).
5. Saves everything into one folder per form type, and writes a manifest
   CSV logging every filing found, whether it downloaded successfully, and
   where each file landed.

Uses only the free, public data.sec.gov and www.sec.gov endpoints. No API
key or signup required, just a descriptive User-Agent header identifying
who is making the request, which SEC asks for.

**Requirements:** `pip install requests beautifulsoup4`

**Usage:** edit the CONFIG block at the top of the file (company, CIK, form
types, date range, which exhibits to keep), then run:

```
python sec_filing_downloader.py
