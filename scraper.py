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
    """Fetch agenda links from a year-tabbed page, returning only the most recent year's items.

    Each returned dict has keys: url, title, year, source_url.
    """
    print(f"Fetching: {url}")
    parsed = urllib.parse.urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        },
    )
    with urllib.request.urlopen(req) as response:
        html = response.read().decode("utf-8", errors="replace")

    soup = BeautifulSoup(html, "html.parser")
    most_recent_year, container = _find_most_recent_year_section(soup)

    if container is None:
        print(f"  [warn] No year sections found; scraping all links from {url}")
        container = soup
    else:
        print(f"  Found {most_recent_year} section")

    links: list[dict] = []
    seen_urls: set[str] = set()
    for a_tag in container.find_all("a", href=True):
        href = a_tag["href"].strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript"):
            continue
        if href.startswith("http"):
            full_url = href
        elif href.startswith("/"):
            full_url = base + href
        else:
            full_url = urllib.parse.urljoin(url, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)
        title = a_tag.get_text(strip=True) or Path(urllib.parse.unquote(href)).name
        links.append({"url": full_url, "title": title, "year": most_recent_year, "source_url": url})

    return links


def _find_most_recent_year_section(soup):
    """Return (year, container_element) for the most recent year found on the page.

    Tries three strategies in order:
      1. Elements whose id attribute contains a 4-digit year (Bootstrap/Drupal tab panes).
      2. Headings whose text is exactly a 4-digit year; returns sibling content between
         that heading and the next year heading.
      3. Tab links/buttons whose text is exactly a 4-digit year; resolves the linked panel
         via aria-controls/href when possible.
    Returns (None, None) if no year structure is detected.
    """
    # Strategy 1: tab panes with year in id (e.g. <div id="year-2026"> or <div id="2026">)
    year_panes: dict[int, object] = {}
    for tag in soup.find_all(id=_YEAR_RE):
        m = _YEAR_RE.search(tag.get("id", ""))
        if m:
            year_panes[int(m.group(1))] = tag
    if year_panes:
        best = max(year_panes)
        return best, year_panes[best]

    # Strategy 2: headings whose full text is a 4-digit year
    year_headings: dict[int, object] = {}
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5"]):
        text = tag.get_text(strip=True)
        if _YEAR_ONLY_RE.match(text):
            year_headings[int(text)] = tag
    if year_headings:
        best = max(year_headings)
        heading = year_headings[best]
        # Collect sibling content between this heading and the next year heading
        siblings_html: list[str] = []
        collecting = False
        for sibling in heading.parent.children:
            if sibling is heading:
                collecting = True
                continue
            if not collecting:
                continue
            # Stop when we hit the next year heading
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
        # JS-driven tabs: all content is on the page but we can't isolate the panel
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
