"""
NH Board Agenda & PDF Scraper

Monitors multiple NH municipal board pages for new agendas and PDFs.
Add new sources to the SOURCES list; supported types:
  node_agenda   — CivicEngage /node/NNN/agenda (Cloudflare, year subpath)
  agendacenter  — CivicPlus AgendaCenter /AgendaCenter/<Board>-<ID>
  archive       — CivicPlus Archive.aspx?AMID=NNN
  legistar      — Legistar REST API (webapi.legistar.com)
  civicclerk    — CivicClerk portal (public OData API)
  portsmouth    — Portsmouth Planning Dept board page + upcoming event pages
  gdoc_agenda   — Published Google Sheet board list → per-board Google Doc agenda
"""

import argparse
import datetime
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Manchester NH — PDF sources (tracked by filename)
# ---------------------------------------------------------------------------
BASE_URL = "https://www.manchesternh.gov"
PAGE_URLS = [
    f"{BASE_URL}/Departments/Planning-and-Comm-Dev/Zoning-Board/Project-Applications",
    f"{BASE_URL}/Departments/Planning-and-Comm-Dev/Planning-Board/Project-Applications",
]
PAGE_URL = PAGE_URLS[0]  # kept for backward compatibility

# ---------------------------------------------------------------------------
# All other agenda/document monitoring sources
# ---------------------------------------------------------------------------
TILTON_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vRghDfL4lr5rKTLWbSOd_j_eVXfp8yaWu4ags2TUOpgjHfhkmCZ7UhiXlYHUTfr73bwsGmXyWJ7tCPe"
    "/pubhtml/sheet?headers=false&gid=0"
)

SOURCES = [
    # CivicEngage node/agenda — Cloudflare-protected, year-as-subpath
    {"type": "node_agenda", "url": "https://www.merrimacknh.gov/node/2261/agenda",  "label": "Merrimack Planning Board"},
    {"type": "node_agenda", "url": "https://www.merrimacknh.gov/node/2296/agenda",  "label": "Merrimack Zoning Board"},
    {"type": "node_agenda", "url": "https://www.derrynh.gov/node/206/agenda",       "label": "Derry Planning Board"},
    {"type": "node_agenda", "url": "https://www.derrynh.gov/node/216/agenda",       "label": "Derry Zoning Board"},
    {"type": "node_agenda", "url": "https://www.somersworthnh.gov/node/673/agenda", "label": "Somersworth Planning Board"},
    {"type": "node_agenda", "url": "https://www.somersworthnh.gov/node/746/agenda", "label": "Somersworth ZBA"},
    # CivicPlus AgendaCenter
    {"type": "agendacenter", "url": "https://www.salemnh.gov/AgendaCenter/Zoning-Board-of-Adjustment-14", "label": "Salem ZBA"},
    {"type": "agendacenter", "url": "https://www.salemnh.gov/AgendaCenter/Planning-Board-6",              "label": "Salem Planning Board"},
    {"type": "agendacenter", "url": "https://www.londonderrynh.gov/AgendaCenter/Planning-Board-16",       "label": "Londonderry Planning Board"},
    {"type": "agendacenter", "url": "https://www.londonderrynh.gov/AgendaCenter/Zoning-Board-of-Adjustment-24", "label": "Londonderry ZBA"},
    # CivicPlus Archive.aspx
    {"type": "archive", "url": "https://www.concordnh.gov/Archive.aspx?AMID=61&Type=&ADID=", "label": "Concord ZBA"},
    # Legistar REST API — Planning Board only
    {"type": "legistar", "url": "https://webapi.legistar.com/v1/ConcordNH/events",
     "label": "Concord Planning Board", "board_filter": "Planning Board"},
    # CivicClerk portal (public API) — Planning & Zoning categories 38 and 77
    {"type": "civicclerk", "url": "https://nashuanh.portal.civicclerk.com/?category_id=38,77",
     "label": "Nashua Planning/Zoning"},
    # Portsmouth Planning Department board pages
    {"type": "portsmouth", "url": "https://www.portsmouthnh.gov/planportsmouth/planning-board",
     "archive_url": "https://www.portsmouthnh.gov/planportsmouth/planning-board/planning-board-archived-meetings-and-material",
     "label": "Portsmouth Planning Board"},
    {"type": "portsmouth", "url": "https://www.portsmouthnh.gov/planportsmouth/zoning-board-adjustment",
     "archive_url": "https://www.portsmouthnh.gov/planportsmouth/zoning-board-adjustment/zoning-board-adjustment-archived-meetings-and-material",
     "label": "Portsmouth ZBA"},
    # Google Sheet → Google Doc agendas (Tilton) — one doc per board, overwritten each meeting
    {"type": "gdoc_agenda", "url": TILTON_SHEET_URL,
     "label": "Tilton Planning Board", "board_filter": "Planning Board"},
    {"type": "gdoc_agenda", "url": TILTON_SHEET_URL,
     "label": "Tilton ZBA", "board_filter": "Zoning Board of Adjustment"},
]

# Keep for backward compatibility with existing manifest entries
MERRIMACK_URLS = [s["url"] for s in SOURCES if "merrimacknh.gov" in s["url"]]

# Sources that list many dated meetings only report ones this recent (avoids
# flooding the first email with a whole year of old agendas).
RECENT_DAYS = 30

_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_YEAR_ONLY_RE = re.compile(r"^(20\d{2})$")


# ---------------------------------------------------------------------------
# Manchester NH — PDF scraper
# ---------------------------------------------------------------------------

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
    module_div = soup.find("div", class_="ModManchesterDynamicFileListC") or soup
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
    parsed = urllib.parse.urlparse(pdf_url)
    encoded_url = parsed._replace(path=urllib.parse.quote(parsed.path, safe="/:")).geturl()
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


# ---------------------------------------------------------------------------
# CivicEngage node/agenda scraper (Merrimack, Derry — Cloudflare)
# ---------------------------------------------------------------------------

def fetch_agenda_links(url: str) -> list[dict]:
    """Fetch agenda links from a CivicEngage /node/NNN/agenda page.

    Detects year-as-subpath navigation, follows the most recent year's URL,
    and extracts agenda items from <h3> links.  Uses cloudscraper to bypass
    Cloudflare.  Returns list of dicts: url, title, year, source_url.
    """
    import cloudscraper
    print(f"Fetching: {url}")
    parsed = urllib.parse.urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    session = cloudscraper.create_scraper()

    resp = session.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

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

    most_recent_year, container = _find_most_recent_year_section(soup)
    if container is None:
        print(f"  [warn] No year sections found; scraping all h3 links from {url}")
        container = soup
    else:
        print(f"  Found {most_recent_year} section")
    return _extract_h3_agenda_links(container, url, base, most_recent_year)


def _extract_h3_agenda_links(container, page_url: str, base: str, year) -> list[dict]:
    h3_links = [a for h in container.find_all("h3") for a in h.find_all("a", href=True)]
    source = h3_links if h3_links else container.find_all("a", href=True)
    links: list[dict] = []
    seen: set[str] = set()
    for a_tag in source:
        href = a_tag["href"].strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript"):
            continue
        full_url = href if href.startswith("http") else (
            base + href if href.startswith("/") else urllib.parse.urljoin(page_url, href)
        )
        if full_url in seen:
            continue
        seen.add(full_url)
        title = a_tag.get_text(strip=True) or Path(urllib.parse.unquote(href)).name
        links.append({"url": full_url, "title": title, "year": year, "source_url": page_url})
    return links


def _find_most_recent_year_section(soup):
    year_panes: dict[int, object] = {}
    for tag in soup.find_all(id=_YEAR_RE):
        m = _YEAR_RE.search(tag.get("id", ""))
        if m:
            year_panes[int(m.group(1))] = tag
    if year_panes:
        best = max(year_panes)
        return best, year_panes[best]

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
            if (hasattr(sibling, "name") and sibling.name in ("h1", "h2", "h3", "h4", "h5")
                    and _YEAR_ONLY_RE.match(sibling.get_text(strip=True))):
                break
            siblings_html.append(str(sibling))
        if siblings_html:
            return best, BeautifulSoup("".join(siblings_html), "html.parser")
        return best, heading.parent

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


# ---------------------------------------------------------------------------
# CivicPlus AgendaCenter scraper (Salem, Londonderry)
# ---------------------------------------------------------------------------

def fetch_agendacenter_links(url: str) -> list[dict]:
    """Fetch agenda links from a CivicPlus AgendaCenter page.

    The page HTML contains all years' agenda links; this function extracts
    /AgendaCenter/ViewFile/Agenda/_MMDDYYYY-ID hrefs, groups by year, and
    returns only the most recent year's items.
    """
    import requests
    print(f"Fetching: {url}")
    parsed = urllib.parse.urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    _ac_re = re.compile(r"/AgendaCenter/ViewFile/Agenda/_(\d{2})(\d{2})(\d{4})-(\d+)", re.I)
    by_year: dict[int, list] = {}
    seen: set[str] = set()

    for a_tag in soup.find_all("a", href=True):
        m = _ac_re.search(a_tag["href"])
        if not m:
            continue
        mm, dd, yyyy, item_id = m.groups()
        year = int(yyyy)
        canonical = f"{base}/AgendaCenter/ViewFile/Agenda/_{mm}{dd}{yyyy}-{item_id}"
        if canonical in seen:
            continue
        seen.add(canonical)
        title = a_tag.get_text(strip=True) or f"Agenda {mm}/{dd}/{yyyy}"
        by_year.setdefault(year, []).append(
            {"url": canonical, "title": title, "year": year, "source_url": url}
        )

    if not by_year:
        print(f"  [warn] No AgendaCenter agenda links found at {url}")
        return []

    best = max(by_year)
    print(f"  Found {len(by_year[best])} agendas for {best}")
    return by_year[best]


# ---------------------------------------------------------------------------
# CivicPlus Archive.aspx scraper (Concord)
# ---------------------------------------------------------------------------

def fetch_archive_links(url: str) -> list[dict]:
    """Fetch document links from a CivicPlus Archive.aspx page.

    Filters to the current calendar year to avoid flooding on first run.
    """
    import requests
    print(f"Fetching: {url}")
    parsed = urllib.parse.urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    current_year = datetime.date.today().year

    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    _adid_re = re.compile(r"ADID=(\d+)", re.I)

    links: list[dict] = []
    seen: set[str] = set()

    for a_tag in soup.find_all("a", href=True):
        m = _adid_re.search(a_tag["href"])
        if not m:
            continue
        adid = m.group(1)
        canonical = f"{base}/Archive.aspx?ADID={adid}"
        if canonical in seen:
            continue

        # Look for a year in surrounding text (parent row / nearby siblings)
        ctx = ""
        for node in [a_tag.parent, a_tag.find_previous("td"), a_tag.find_previous("li")]:
            if node and hasattr(node, "get_text"):
                ctx += node.get_text(" ", strip=True) + " "
        ctx += a_tag.get_text(strip=True)
        year_m = _YEAR_RE.search(ctx)
        item_year = int(year_m.group(1)) if year_m else None

        # Only notify about current-year items
        if item_year and item_year != current_year:
            continue

        seen.add(canonical)
        title = a_tag.get_text(strip=True) or f"Document {adid}"
        links.append({"url": canonical, "title": title, "year": item_year, "source_url": url})

    print(f"  Found {len(links)} current-year archive documents")
    return links


# ---------------------------------------------------------------------------
# Legistar REST API scraper (Concord Planning Board)
# ---------------------------------------------------------------------------

def fetch_legistar_links(url: str, board_filter=None) -> list[dict]:
    """Fetch meetings from the Legistar REST API that have agendas posted.

    url      — Legistar API base, e.g. https://webapi.legistar.com/v1/ConcordNH/events
    board_filter — case-insensitive substring to match EventBodyName (e.g. "Planning Board")

    Only returns meetings from the current year that have EventAgendaFile set.
    """
    import requests
    current_year = datetime.date.today().year
    print(f"Fetching Legistar API: {url} (filter={board_filter!r})")

    params = {
        "$filter": f"EventDate ge datetime'{current_year}-01-01T00:00:00'",
        "$orderby": "EventDate desc",
        "$top": 200,
    }
    r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    events = r.json()

    links: list[dict] = []
    for event in events:
        body_name = event.get("EventBodyName", "")
        if board_filter and board_filter.lower() not in body_name.lower():
            continue
        agenda_file = event.get("EventAgendaFile") or ""
        if not agenda_file:
            continue
        date_str = (event.get("EventDate") or "")[:10]
        title = f"{body_name} — {date_str}"
        year = int(date_str[:4]) if date_str else current_year
        links.append({"url": agenda_file, "title": title, "year": year, "source_url": url})

    print(f"  Found {len(links)} events with agendas")
    return links


# ---------------------------------------------------------------------------
# CivicClerk scraper (Nashua)
# ---------------------------------------------------------------------------

def fetch_civicclerk_links(url: str) -> list[dict]:
    """Fetch agenda files from a CivicClerk portal via its public OData API.

    url — portal URL with category IDs, e.g.
          https://nashuanh.portal.civicclerk.com/?category_id=38,77
    The portal itself is a JavaScript SPA; the data comes from the matching
    https://<tenant>.api.civicclerk.com/v1/Events endpoint.  Returns one item
    per published "Agenda" file for meetings from RECENT_DAYS ago onward, so
    an amended agenda (new file) also triggers a notification.
    """
    import requests
    print(f"Fetching CivicClerk: {url}")
    parsed = urllib.parse.urlparse(url)
    api = f"https://{parsed.netloc.replace('.portal.', '.api.')}/v1"
    category_ids = urllib.parse.parse_qs(parsed.query).get("category_id", [""])[0]
    since = (datetime.date.today() - datetime.timedelta(days=RECENT_DAYS)).isoformat()

    flt = f"startDateTime ge {since}"
    if category_ids:
        flt = f"categoryId in ({category_ids}) and {flt}"
    r = requests.get(
        f"{api}/Events",
        params={"$filter": flt, "$orderby": "startDateTime desc", "$top": 200},
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        timeout=30,
    )
    r.raise_for_status()

    links: list[dict] = []
    for event in r.json().get("value", []):
        date_str = (event.get("startDateTime") or "")[:10]
        for f in event.get("publishedFiles") or []:
            if (f.get("type") or "").lower() != "agenda" or not f.get("fileId"):
                continue
            links.append({
                "url": f"{api}/Meetings/GetMeetingFileStream(fileId={f['fileId']},plainText=false)",
                "title": f"{event.get('eventName', 'Meeting')} — {date_str} — {f.get('name') or 'Agenda'}",
                "year": int(date_str[:4]) if date_str else None,
                "source_url": url,
            })

    print(f"  Found {len(links)} agenda files since {since}")
    return links


# ---------------------------------------------------------------------------
# Google Sheet → Google Doc agenda scraper (Tilton)
# ---------------------------------------------------------------------------

_MONTHS = ["january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december"]
_DATE_RE = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b", re.I
)


def _unwrap_google_redirect(href: str) -> str:
    parsed = urllib.parse.urlparse(href)
    if parsed.netloc.endswith("google.com") and parsed.path == "/url":
        return urllib.parse.parse_qs(parsed.query).get("q", [href])[0]
    return href


def fetch_gdoc_agenda_links(url: str, board_filter=None) -> list[dict]:
    """Fetch the current agenda for one board from a published Google Sheet.

    The sheet has one row per board; its "Agenda" cell links to a Google Doc
    that the town overwrites for each meeting.  The doc is exported as plain
    text and the meeting date in its header makes each meeting a distinct
    item (falls back to a content hash if no date is found).
    """
    import hashlib
    import requests
    print(f"Fetching Google Sheet: {url} (board={board_filter!r})")
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    agenda_href = None
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if not tds or tds[0].get_text(strip=True).lower() != (board_filter or "").lower():
            continue
        cells = [td for td in tds if td.get_text(strip=True).lower() == "agenda"] or tds[1:2]
        a_tag = cells[0].find("a", href=True) if cells else None
        if a_tag:
            agenda_href = _unwrap_google_redirect(a_tag["href"])
        break

    m = re.search(r"/document/d/([\w-]+)", agenda_href or "")
    if not m:
        print(f"  [warn] No Google Doc agenda link found for {board_filter!r}", file=sys.stderr)
        return []
    doc_id = m.group(1)

    r = requests.get(f"https://docs.google.com/document/d/{doc_id}/export?format=txt",
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    text = r.content.decode("utf-8-sig", errors="replace")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
    for line in lines[:15]:
        dm = _DATE_RE.search(line)
        if dm:
            month, day, year = _MONTHS.index(dm.group(1).lower()) + 1, int(dm.group(2)), int(dm.group(3))
            meeting = f"{year:04d}-{month:02d}-{day:02d}"
            print(f"  Current agenda: {meeting}")
            return [{"url": f"{doc_url}#meeting={meeting}", "title": f"Agenda — {line}",
                     "year": year, "source_url": url}]

    digest = hashlib.sha1(" ".join(" ".join(lines).split()).encode()).hexdigest()[:12]
    print(f"  [warn] No meeting date found in agenda doc; using content hash {digest}")
    return [{"url": f"{doc_url}#rev={digest}", "title": f"Agenda — {lines[0] if lines else 'updated'}",
             "year": datetime.date.today().year, "source_url": url}]


# ---------------------------------------------------------------------------
# Portsmouth Planning Department board pages
# ---------------------------------------------------------------------------

_MDY_IN_URL_RE = re.compile(r"(\d{1,2})-(\d{1,2})-(20\d{2})")


def _canonical_portsmouth_file(href: str) -> str:
    """Normalize a Portsmouth file URL.

    The same PDF is linked under files.portsmouthnh.gov and
    files.cityofportsmouth.com, with '+' or '%20' for spaces.
    """
    parsed = urllib.parse.urlparse(href)
    path = urllib.parse.unquote_plus(parsed.path)
    return "https://files.portsmouthnh.gov" + urllib.parse.quote(path)


def fetch_portsmouth_links(url: str, archive_url=None) -> list[dict]:
    """Fetch agenda PDFs for one Portsmouth board.

    url         — board home page; lists upcoming /planportsmouth/events/ pages,
                  each of which gets an "Agenda" link once one is posted.
    archive_url — board's archived-meetings page (recent past meetings inline).
    Only meetings dated within the last RECENT_DAYS days or later are returned.
    """
    import requests
    print(f"Fetching Portsmouth: {url}")
    base = "https://www.portsmouthnh.gov"
    headers = {"User-Agent": "Mozilla/5.0"}
    cutoff = datetime.date.today() - datetime.timedelta(days=RECENT_DAYS)

    def get_soup(page_url):
        r = requests.get(page_url, headers=headers, timeout=30)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")

    home = get_soup(url)
    board_slug = urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1]
    event_prefix = {"planning-board": "planning-board-",
                    "zoning-board-adjustment": "board-adjustment-"}.get(board_slug, board_slug + "-")
    event_urls = sorted({
        base + a["href"] for a in home.find_all("a", href=True)
        if a["href"].startswith(f"/planportsmouth/events/{event_prefix}")
    })
    pages = [get_soup(u) for u in event_urls]
    if archive_url:
        pages.append(get_soup(archive_url))

    links: list[dict] = []
    seen: set[str] = set()
    for soup in pages:
        for a_tag in soup.find_all("a", href=True):
            text = a_tag.get_text(" ", strip=True)
            href = a_tag["href"]
            if "agenda" not in text.lower() or "packet" in text.lower():
                continue
            if "/agendas/" not in href or not href.lower().endswith(".pdf"):
                continue
            m = _MDY_IN_URL_RE.search(urllib.parse.unquote_plus(href))
            if not m:
                continue
            mm, dd, yyyy = (int(x) for x in m.groups())
            try:
                meeting = datetime.date(yyyy, mm, dd)
            except ValueError:
                continue
            if meeting < cutoff:
                continue
            canonical = _canonical_portsmouth_file(href)
            if canonical in seen:
                continue
            seen.add(canonical)
            links.append({"url": canonical, "title": f"{meeting.isoformat()} — {text}",
                          "year": yyyy, "source_url": url})

    print(f"  Found {len(links)} agendas ({len(event_urls)} upcoming event pages checked)")
    return links


# ---------------------------------------------------------------------------
# CLI entry point (Manchester PDFs only)
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Download PDFs from the Manchester NH Zoning Board Project Applications page."
    )
    parser.add_argument("-o", "--output", default="pdfs",
                        help="Output directory for downloaded PDFs (default: ./pdfs)")
    parser.add_argument("--list", action="store_true",
                        help="List available PDFs without downloading")
    parser.add_argument("--url", default=PAGE_URL,
                        help="Page URL to scrape")
    args = parser.parse_args()

    pdfs = fetch_pdf_links(args.url)
    if not pdfs:
        print("No PDFs found on the page.")
        sys.exit(1)

    print(f"\nFound {len(pdfs)} PDF(s):\n")
    if args.list:
        for pdf in pdfs:
            print(f"  {pdf['filename']}\n    {pdf['url']}")
        return

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading to: {output_dir.resolve()}\n")
    success = sum(
        download_pdf(pdf["url"], output_dir / (sanitize_filename(pdf["filename"])
                                               if pdf["filename"].lower().endswith(".pdf")
                                               else sanitize_filename(pdf["filename"]) + ".pdf"))
        for pdf in pdfs
    )
    print(f"\nDone: {success}/{len(pdfs)} PDFs downloaded to '{output_dir}'")


if __name__ == "__main__":
    main()
