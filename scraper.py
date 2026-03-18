"""
Manchester NH Zoning Board Project Applications PDF Scraper

Scrapes PDFs from:
https://www.manchesternh.gov/Departments/Planning-and-Comm-Dev/Zoning-Board/Project-Applications
"""

import argparse
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

BASE_URL = "https://www.manchesternh.gov"
PAGE_URL = f"{BASE_URL}/Departments/Planning-and-Comm-Dev/Zoning-Board/Project-Applications"


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
