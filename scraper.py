"""
Manchester NH Zoning Board Project Applications PDF Scraper

Add URLs to PAGE_URLS to scrape additional pages.
"""

import argparse
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

BASE_URL = "https://www.manchesternh.gov"

MERRIMACK_BASE_URL = "https://www.merrimacknh.gov"

# Merrimack NH pages to monitor for new agendas
MERRIMACK_URLS = [
    f"{MERRIMACK_BASE_URL}/node/2261/agenda",
]

_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_YEAR_ONLY_RE = re.compile(r"^(20\d{2})$")

# Add more URLs here to scrape additional pages
PAGE_URLS = [
    f"{BASE_URL}/Departments/Planning-and-Comm-Dev/Zoning-Board/Project-Applications",
    f"{BASE_URL}/Departments/Planning-and-Comm-Dev/Planning-Board/Project-Applications",
]

PAGE_URL = PAGE_URLS[0]  # kept for backward compatibility


def fetch_pdf_links(url: str) -> list[dict]:
    """Fetch the page and extract all PDF links."""
    print(f"Fetching: {url}")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; PDF-Scraper/1.0)"},
    )
    with urllib.request.urlopen(req) as response:
        html = response.read().decode("utf-8", errors="replace")

    soup = BeautifulSoup(html, "html.parser")

    # The PDFs are in a DNN module with class ModManchesterDynamicFileListC
    module_div = soup.find("div", class_="ModManchesterDynamicFileListC")
    if module_div is None:
        # Fall back to searching the entire page
        module_div = soup

    pdfs = []
    for a_tag in module_div.find_all("a", href=True):
        href = a_tag["href"]
        if href.lower().endswith(".pdf"):
            full_url = href if href.startswith("http") else BASE_URL + href
            filename = a_tag.get_text(strip=True) or Path(urllib.parse.unquote(href)).name
            pdfs.append({"url": full_url, "filename": filename})

    return pdfs


def download_pdf(pdf_url: str, dest_path: Path) -> bool:
    """Download a single PDF to dest_path. Returns True on success."""
    if dest_path.exists():
        print(f"  [skip] {dest_path.name} (already exists)")
        return True

    # URL-encode spaces and special characters in the path component
    parsed = urllib.parse.urlparse(pdf_url)
    encoded_path = urllib.parse.quote(parsed.path, safe="/:")
    encoded_url = parsed._replace(path=encoded_path).geturl()

    try:
        req = urllib.request.Request(
            encoded_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; PDF-Scraper/1.0)"},
        )
        with urllib.request.urlopen(req) as response:
            data = response.read()
        dest_path.write_bytes(data)
        print(f"  [ok]   {dest_path.name} ({len(data):,} bytes)")
        return True
    except urllib.error.HTTPError as e:
        print(f"  [err]  {dest_path.name} — HTTP {e.code}: {e.reason}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"  [err]  {dest_path.name} — {e}", file=sys.stderr)
        return False


def sanitize_filename(name: str) -> str:
    """Remove characters not safe for filenames."""
    return "".join(c for c in name if c not in r'\/:*?"<>|')


def fetch_agenda_links(url: str) -> list[dict]:
    """Fetch agenda links from a year-tabbed government page, returning only the most recent year.

    Handles two layouts:
    - Sub-URL per year (e.g. /node/2261/agenda/2026): finds the highest-year link on the
      index page, fetches it, then extracts agenda items from <h3> tags.
    - In-page tabs: finds the most recent year section via id/heading/aria heuristics.

    Uses cloudscraper to handle Cloudflare-protected sites.
    Each returned dict has keys: url, title, year, source_url.
    """
    import cloudscraper
    print(f"Fetching: {url}")
    parsed = urllib.parse.urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    session = cloudscraper.create_scraper()

    resp = session.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Strategy A: year-as-subpath links (e.g. href="/node/2261/agenda/2026")
    _path_year_re = re.compile(r"/(\d{4})/?$")
    subpath_years: dict[int, str] = {}
    for a_tag in soup.find_all("a", href=True):
        m = _path_year_re.search(a_tag["href"])
        if m:
            year = int(m.group(1))
            if 2000 <= year <= 2099:
                href = a_tag["href"]
                subpath_years[year] = href if href.startswith("http") else base + href

    if subpath_years:
        best_year = max(subpath_years)
        year_url = subpath_years[best_year]
        print(f"  Following {best_year} sub-page: {year_url}")
        resp2 = session.get(year_url)
        resp2.raise_for_status()
        soup = BeautifulSoup(resp2.text, "html.parser")
        return _extract_h3_agenda_links(soup, year_url, base, best_year)

    # Strategy B: in-page year sections (tab panes, year headings, aria-controls)
    most_recent_year, container = _find_most_recent_year_section(soup)
    if container is None:
        print(f"  [warn] No year sections found; scraping all h3 links from {url}")
        container = soup
    else:
        print(f"  Found {most_recent_year} section")
    return _extract_h3_agenda_links(container, url, base, most_recent_year)


def _extract_h3_agenda_links(container, page_url: str, base: str, year) -> list[dict]:
    """Extract agenda item links, preferring links inside <h3> tags."""
    links: list[dict] = []
    seen: set[str] = set()

    # Prefer links inside <h3> tags (agenda titles on Merrimack-style pages)
    h3_links = [a for h in container.find_all("h3") for a in h.find_all("a", href=True)]
    source = h3_links if h3_links else container.find_all("a", href=True)

    for a_tag in source:
        href = a_tag["href"].strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript"):
            continue
        if href.startswith("http"):
            full_url = href
        elif href.startswith("/"):
            full_url = base + href
        else:
            full_url = urllib.parse.urljoin(page_url, href)
        if full_url in seen:
            continue
        seen.add(full_url)
        title = a_tag.get_text(strip=True) or Path(urllib.parse.unquote(href)).name
        links.append({"url": full_url, "title": title, "year": year, "source_url": page_url})

    return links


def _find_most_recent_year_section(soup):
    """Return (year, container_element) for the most recent year found on the page.

    Tries three strategies:
      1. Elements whose id contains a 4-digit year (Bootstrap/Drupal tab panes).
      2. Headings whose full text is a 4-digit year; returns sibling content up to the next year heading.
      3. Tab links/buttons with year text; resolves via aria-controls/href when possible.
    Returns (None, None) if no year structure is detected.
    """
    # Strategy 1: tab panes with year in id
    year_panes: dict[int, object] = {}
    for tag in soup.find_all(id=_YEAR_RE):
        m = _YEAR_RE.search(tag.get("id", ""))
        if m:
            year_panes[int(m.group(1))] = tag
    if year_panes:
        best = max(year_panes)
        return best, year_panes[best]

    # Strategy 2: headings whose full text is exactly a 4-digit year
    year_headings: dict[int, object] = {}
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5"]):
        text = tag.get_text(strip=True)
        if _YEAR_ONLY_RE.match(text):
            year_headings[int(text)] = tag
    if year_headings:
        best = max(year_headings)
        heading = year_headings[best]
        siblings_html: list[str] = []
        collecting = False
        for sibling in heading.parent.children:
            if sibling is heading:
                collecting = True
                continue
            if not collecting:
                continue
            if (
                hasattr(sibling, "name")
                and sibling.name in ("h1", "h2", "h3", "h4", "h5")
                and _YEAR_ONLY_RE.match(sibling.get_text(strip=True))
            ):
                break
            siblings_html.append(str(sibling))
        if siblings_html:
            return best, BeautifulSoup("".join(siblings_html), "html.parser")
        return best, heading.parent

    # Strategy 3: tab buttons/links whose text is exactly a 4-digit year
    year_tabs: dict[int, object] = {}
    for tag in soup.find_all(["a", "button"]):
        text = tag.get_text(strip=True)
        if _YEAR_ONLY_RE.match(text):
            year_tabs[int(text)] = tag
    if year_tabs:
        best = max(year_tabs)
        tab = year_tabs[best]
        panel_id = tab.get("aria-controls") or tab.get("href", "").lstrip("#")
        if panel_id:
            panel = soup.find(id=panel_id)
            if panel:
                return best, panel
        return best, soup

    return None, None


def main():
    parser = argparse.ArgumentParser(
        description="Download PDFs from the Manchester NH Zoning Board Project Applications page."
    )
    parser.add_argument(
        "-o",
        "--output",
        default="pdfs",
        help="Output directory for downloaded PDFs (default: ./pdfs)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available PDFs without downloading",
    )
    parser.add_argument(
        "--url",
        default=PAGE_URL,
        help="Page URL to scrape (default: Manchester NH Zoning Board Project Applications)",
    )
    args = parser.parse_args()

    pdfs = fetch_pdf_links(args.url)

    if not pdfs:
        print("No PDFs found on the page.")
        sys.exit(1)

    print(f"\nFound {len(pdfs)} PDF(s):\n")

    if args.list:
        for pdf in pdfs:
            print(f"  {pdf['filename']}")
            print(f"    {pdf['url']}")
        return

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading to: {output_dir.resolve()}\n")

    success = 0
    for pdf in pdfs:
        filename = sanitize_filename(pdf["filename"])
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        dest = output_dir / filename
        if download_pdf(pdf["url"], dest):
            success += 1

    print(f"\nDone: {success}/{len(pdfs)} PDFs downloaded to '{output_dir}'")


if __name__ == "__main__":
    main()
