# Manchester NH Zoning Board PDF Scraper

Downloads PDF application packets from the [Manchester NH Zoning Board of Adjustment Project Applications page](https://www.manchesternh.gov/Departments/Planning-and-Comm-Dev/Zoning-Board/Project-Applications).

The city posts application packets for each upcoming ZBA meeting as a list of PDFs — one per project, plus the agenda and draft minutes. This scraper fetches that list and downloads the files locally.

## Requirements

- Python 3.10+
- [beautifulsoup4](https://pypi.org/project/beautifulsoup4/)

## Installation

```bash
git clone https://github.com/davidxue1989/manchesternh_zoning_pdf_scraper.git
cd manchesternh_zoning_pdf_scraper
pip install -r requirements.txt
```

No virtual environment is strictly required, but one is recommended:

```bash
python -m venv .venv
source .venv/bin/activate      # macOS/Linux
.venv\Scripts\activate         # Windows
pip install -r requirements.txt
```

## Usage

### Download all PDFs

```bash
python scraper.py
```

Downloads all PDFs to a `./pdfs/` directory (created automatically).

### Specify an output directory

```bash
python scraper.py -o /path/to/downloads
```

### Preview without downloading

```bash
python scraper.py --list
```

Prints each filename and its source URL without writing any files.

### Scrape a different page URL

```bash
python scraper.py --url "https://www.manchesternh.gov/some/other/page"
```

Useful if the city reorganizes the site or you want to scrape a related page (e.g. Agendas or Minutes).

### All options

```
usage: scraper.py [-h] [-o OUTPUT] [--list] [--url URL]

options:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        Output directory for downloaded PDFs (default: ./pdfs)
  --list                List available PDFs without downloading
  --url URL             Page URL to scrape
```

## Example output

```
Fetching: https://www.manchesternh.gov/Departments/Planning-and-Comm-Dev/Zoning-Board/Project-Applications

Found 9 PDF(s):

Downloading to: /home/user/manchesternh_zoning_pdf_scraper/pdfs

  [ok]   2026-03-12_ZBA2026-016_YOUVILLE_STREET_385_PACKET.PDF (4,112,384 bytes)
  [ok]   2026-03-12_ZBA2026-015_WEST_MITCHELL_STREET_247_PACKET.PDF (2,987,520 bytes)
  [ok]   2026-03-12_ZBA2026-014_SOUTH_WILLOW_STREET_1895_PACKET.PDF (3,145,728 bytes)
  ...
  [skip] 2026-03-12_ZBA_AGENDA.PDF (already exists)

Done: 9/9 PDFs downloaded to 'pdfs'
```

## Design

### Page structure

The Manchester NH website runs on [DotNetNuke (DNN)](https://www.dnnsoftware.com/), a .NET CMS. The Project Applications page contains a custom DNN module (`ModManchesterDynamicFileListC`) that renders a `<ul>` list of `<a>` tags pointing directly to PDF files hosted under `/Portals/2/Departments/pcd/BoardsCommissions/ZBA/Project Applications/`.

### How it works

1. **Fetch** — `urllib.request` fetches the page HTML with a browser-like `User-Agent` header.
2. **Parse** — `BeautifulSoup` locates the `ModManchesterDynamicFileListC` div, then collects all `<a href="...pdf">` links within it. If the module div is not found, it falls back to scanning the full page.
3. **URL encoding** — The server stores PDFs in a path containing spaces (`Project Applications/`). The download step URL-encodes the path component before making the request.
4. **Download** — Each PDF is saved using its display name from the page. Files that already exist on disk are skipped, making repeated runs safe and incremental.
5. **Filename sanitization** — Characters illegal in Windows/macOS/Linux filenames (`\ / : * ? " < > |`) are stripped before writing.

### Dependencies

Only one third-party library is used:

| Library | Purpose |
|---|---|
| `beautifulsoup4` | HTML parsing to extract PDF links |

Everything else (`urllib`, `pathlib`, `argparse`) is Python stdlib.
