"""
Generic SEC EDGAR filing downloader.

Downloads any form type(s) (e.g. 20-F, 6-K, 10-K, 10-Q, 8-K...) for any
company, from any start date, into a local folder — one subfolder per
form type.

Uses the free, public data.sec.gov / www.sec.gov endpoints. No API key,
no signup. SEC only requires a descriptive User-Agent header (name +
email) identifying who's making the request, and asks that you stay
under ~10 requests/second.

Also downloads exhibits (e.g. EX-1 press releases, EX-99 exhibits) attached
to each filing — see the EXHIBIT_TYPES setting below.

Requires: pip install requests beautifulsoup4

Docs: https://www.sec.gov/os/webmaster-faq#developers

------------------------------------------------------------------------
USAGE
------------------------------------------------------------------------

1. Edit the CONFIG block below (or import and call find_cik() /
   download_filings() directly from your own script).

2. Run:
       python sec_filing_downloader.py

3. Files land in:  <OUTPUT_DIR>/<FORM_TYPE>/<date>_<original_filename>

------------------------------------------------------------------------
FINDING A CIK
------------------------------------------------------------------------
Every company on EDGAR has a CIK (Central Index Key). You can:
  a) Use find_cik("company name") below — it queries SEC's own search
     and returns the best match(es), OR
  b) Look it up manually: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=YOUR+COMPANY&type=10-K
  c) Use the ticker lookup file SEC publishes: https://www.sec.gov/files/company_tickers.json
"""

import requests
import json
import time
import re
from pathlib import Path
from typing import List, Dict, Optional
from bs4 import BeautifulSoup

# ==========================================================================
# CONFIG — edit these for each run
# ==========================================================================

USER_AGENT = "Name username@email.com"   # REQUIRED by SEC — use your own name+email

COMPANY_NAME = "Frontline"          # used only if CIK is unknown (see find_cik)
CIK = "0000913290"                  # Frontline plc — set to None to auto-lookup by COMPANY_NAME
FORM_TYPES = ["6-K", "6-K/A"]       # e.g. ["10-K"], ["10-Q"], ["20-F", "6-K"], ["8-K"]
START_DATE = "2024-01-01"           # YYYY-MM-DD, inclusive
END_DATE = None                     # YYYY-MM-DD, or None for "up to latest"
OUTPUT_DIR = "./sec_downloads"      # local folder (cloud workspace or your machine)

# Which documents to pull from each filing, by SEC's own "Type" label on the
# filing index page. The main filing itself (6-K, 10-K, etc.) is always
# included automatically. Add exhibit type prefixes you want here — matching
# is prefix-based, so "EX-1" also catches "EX-1.1", "EX-1A", etc.
#   Examples of common types: EX-1 (press release, often), EX-99 / EX-99.1
#   (press releases / other exhibits), EX-2 (agreements), EX-10 (material
#   contracts), EX-21 (subsidiaries), EX-23 (auditor consents)
# Set to None to download EVERY document/exhibit in the filing (images too).
EXHIBIT_TYPES = ["EX-1"]            # e.g. ["EX-1", "EX-99"], or None for "all documents"

# ==========================================================================


HEADERS = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}


def find_cik(company_name: str, limit: int = 5) -> List[Dict]:
    """
    Look up CIK(s) for a company by name using SEC's full-text company search.
    Returns a list of {cik, name, ticker} candidates — inspect and pick the
    right one (names can collide, e.g. "Frontline plc" vs "Frontline Ltd").
    """
    url = "https://www.sec.gov/cgi-bin/browse-edgar"
    params = {
        "action": "getcompany",
        "company": company_name,
        "type": "10-K",     # dummy filter just to get the company list back
        "dateb": "",
        "owner": "include",
        "count": limit,
        "output": "atom",
    }
    resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    # Lightweight XML scrape — avoids adding an XML dependency
    import re
    text = resp.text
    ciks = re.findall(r"<cik>(\d+)</cik>", text)
    names = re.findall(r"<conformed-name>(.*?)</conformed-name>", text)

    results = []
    for cik, name in zip(ciks, names):
        results.append({"cik": cik.zfill(10), "name": name})
    return results


def get_submissions(cik: str) -> Dict:
    """Fetch the full filing history JSON for a company."""
    cik_padded = cik.zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def list_filings(cik: str, form_types: List[str], start_date: str,
                  end_date: Optional[str] = None) -> List[Dict]:
    """
    Return matching filings (metadata + direct document URL + index page URL)
    for a company, filtered by form type and date range. Walks older
    paginated submission files too, not just the 'recent' window.
    """
    cik_padded = cik.zfill(10)
    cik_int = int(cik)
    data = get_submissions(cik)

    def extract(block: Dict) -> List[Dict]:
        out = []
        n = len(block["form"])
        for i in range(n):
            form = block["form"][i]
            filing_date = block["filingDate"][i]
            if form not in form_types:
                continue
            if filing_date < start_date:
                continue
            if end_date and filing_date > end_date:
                continue

            accession_raw = block["accessionNumber"][i]
            accession_nodash = accession_raw.replace("-", "")
            primary_doc = block["primaryDocument"][i]

            out.append({
                "form_type": form,
                "filing_date": filing_date,
                "period_of_report": block.get("reportDate", [None] * n)[i],
                "accession_number": accession_raw,
                "primary_document": primary_doc,
                "description": block.get("primaryDocDescription", [""] * n)[i],
                "doc_url": (
                    f"https://www.sec.gov/Archives/edgar/data/{cik_int}/"
                    f"{accession_nodash}/{primary_doc}"
                ),
                "folder_url": (
                    f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/"
                ),
                "index_url": (
                    f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/"
                    f"{accession_raw}-index.htm"
                ),
            })
        return out

    results = extract(data["filings"]["recent"])

    # Older filings live in paginated files, if any
    for extra_file in data["filings"].get("files", []):
        extra_url = f"https://data.sec.gov/submissions/{extra_file['name']}"
        resp = requests.get(extra_url, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            results.extend(extract(resp.json()))
        time.sleep(0.15)  # stay well under SEC's rate limit

    results.sort(key=lambda r: r["filing_date"])
    return results


def get_filing_documents(index_url: str, folder_url: str) -> List[Dict]:
    """
    Parse a filing's index page to get every document in it, with SEC's own
    'Type' label for each (e.g. '6-K', 'EX-1', 'EX-99.1', 'GRAPHIC').
    This is how you find exhibits — the submissions JSON only exposes the
    single 'primary document', not the full document list.
    """
    resp = requests.get(index_url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    table = soup.find("table", class_="tableFile")
    if not table:
        return []

    docs = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue  # header row or the "Complete submission text file" row
        description = cells[1].get_text(strip=True)
        doc_link = cells[2].find("a")
        doc_name = doc_link.get_text(strip=True) if doc_link else cells[2].get_text(strip=True)
        doc_type = cells[3].get_text(strip=True)
        size = cells[4].get_text(strip=True) if len(cells) > 4 else ""

        if not doc_name or doc_type == "":
            continue  # skip the complete submission .txt row (no Type)

        docs.append({
            "description": description,
            "document": doc_name,
            "type": doc_type,
            "size": size,
            "url": folder_url.rstrip("/") + "/" + doc_name,
        })

    return docs


def _matches_exhibit_filter(doc_type: str, exhibit_types: Optional[List[str]]) -> bool:
    """True if doc_type should be downloaded, given the EXHIBIT_TYPES filter."""
    if exhibit_types is None:
        return True  # download everything
    return any(doc_type.upper().startswith(t.upper()) for t in exhibit_types)


def download_filings(filings: List[Dict], output_dir: str,
                      exhibit_types: Optional[List[str]] = None,
                      group_by_form: bool = True) -> List[Dict]:
    """
    Download each filing's primary document, PLUS any exhibits matching
    exhibit_types (by SEC's own Type label, e.g. "EX-1", "EX-99"). Pass
    exhibit_types=None to download every document in the filing (incl. images).

    Adds 'downloaded_files' (list of saved paths) and 'ok' to each entry.
    """
    for f in filings:
        subdir = f["form_type"].replace("/", "-") if group_by_form else ""
        out_dir = Path(output_dir) / subdir
        out_dir.mkdir(parents=True, exist_ok=True)

        f["downloaded_files"] = []
        f["ok"] = True

        # Get the full document list for this filing (primary doc + exhibits)
        try:
            all_docs = get_filing_documents(f["index_url"], f["folder_url"])
        except Exception as e:
            print(f"  FAIL  {f['filing_date']}  {f['form_type']:8s}  could not read index -> {e}")
            f["ok"] = False
            continue

        # Always include the primary document; add exhibits matching the filter
        wanted_docs = [d for d in all_docs if d["document"] == f["primary_document"]]
        wanted_docs += [
            d for d in all_docs
            if d["document"] != f["primary_document"] and _matches_exhibit_filter(d["type"], exhibit_types)
        ]

        for doc in wanted_docs:
            fname = f"{f['filing_date']}_{doc['document']}"
            out_path = out_dir / fname
            try:
                resp = requests.get(doc["url"], headers=HEADERS, timeout=30)
                resp.raise_for_status()
                out_path.write_bytes(resp.content)
                f["downloaded_files"].append(str(out_path))
                print(f"  OK    {f['filing_date']}  {f['form_type']:8s}  [{doc['type']:8s}]  {fname}  "
                      f"({len(resp.content)/1024:.0f} KB)")
            except Exception as e:
                f["ok"] = False
                print(f"  FAIL  {f['filing_date']}  {f['form_type']:8s}  [{doc['type']:8s}]  {fname}  -> {e}")
            time.sleep(0.15)  # stay well under SEC's 10 req/sec limit

        time.sleep(0.1)

    return filings


def main():
    cik = CIK

    if not cik:
        print(f"No CIK set — looking up '{COMPANY_NAME}'...")
        candidates = find_cik(COMPANY_NAME)
        if not candidates:
            print("No matches found. Set CIK manually — look it up at:")
            print("  https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company="
                  f"{COMPANY_NAME.replace(' ', '+')}")
            return
        print("Candidates found:")
        for c in candidates:
            print(f"  CIK {c['cik']}  —  {c['name']}")
        cik = candidates[0]["cik"]
        print(f"\nUsing first match: CIK {cik} ({candidates[0]['name']})")
        print("(If wrong, set CIK explicitly in the CONFIG block and re-run.)\n")

    print("=" * 80)
    print(f"Fetching filings: CIK {cik}  |  forms {FORM_TYPES}  |  from {START_DATE}"
          f"{' to ' + END_DATE if END_DATE else ' to latest'}")
    print("=" * 80)

    filings = list_filings(cik, FORM_TYPES, START_DATE, END_DATE)
    print(f"\nFound {len(filings)} matching filings.\n")

    if not filings:
        print("Nothing to download. Check the CIK, form types, and date range.")
        return

    print(f"Downloading (exhibit types: {EXHIBIT_TYPES if EXHIBIT_TYPES else 'ALL documents'})...")
    download_filings(filings, OUTPUT_DIR, exhibit_types=EXHIBIT_TYPES)

    ok_count = sum(1 for f in filings if f["ok"])
    total_files = sum(len(f["downloaded_files"]) for f in filings)
    print(f"\nDone: {ok_count}/{len(filings)} filings processed, {total_files} files downloaded to '{OUTPUT_DIR}/'")

    # Save a manifest CSV alongside the downloads
    import csv
    manifest_path = Path(OUTPUT_DIR) / "manifest.csv"
    with open(manifest_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "filing_date", "form_type", "accession_number", "primary_document",
            "description", "doc_url", "folder_url", "index_url", "downloaded_files", "ok"
        ])
        writer.writeheader()
        for row in filings:
            out_row = {k: row.get(k) for k in writer.fieldnames}
            out_row["downloaded_files"] = "; ".join(row.get("downloaded_files", []))
            writer.writerow(out_row)
    print(f"Manifest saved: {manifest_path}")


if __name__ == "__main__":
    main()
