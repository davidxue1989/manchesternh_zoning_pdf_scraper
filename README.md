# Manchester NH Zoning Board PDF Scraper

Downloads PDF application packets from the [Manchester NH Zoning Board of Adjustment Project Applications page](https://www.manchesternh.gov/Departments/Planning-and-Comm-Dev/Zoning-Board/Project-Applications) and sends email notifications when new ones are posted.

The city posts application packets for each upcoming ZBA meeting as a list of PDFs — one per project, plus the agenda and draft minutes. This scraper fetches that list, downloads the files locally, and can notify you by email whenever new PDFs appear.

---

## Files

| File | Purpose |
|---|---|
| `scraper.py` | Core scraper — fetches the page and downloads PDFs |
| `notify.py` | Notification checker — compares against manifest, sends email |
| `manifest.json` | Auto-generated list of all previously seen PDF filenames |
| `.github/workflows/check.yml` | GitHub Actions workflow that runs every 15 minutes |

---

## Requirements

- Python 3.10+
- [beautifulsoup4](https://pypi.org/project/beautifulsoup4/)

---

## Installation

```bash
git clone https://github.com/davidxue1989/manchesternh_zoning_pdf_scraper.git
cd manchesternh_zoning_pdf_scraper
pip install -r requirements.txt
```

A virtual environment is recommended:

```bash
python -m venv .venv
source .venv/bin/activate      # macOS/Linux
.venv\Scripts\activate         # Windows
pip install -r requirements.txt
```

---

## scraper.py — One-shot downloader

Downloads all PDFs currently listed on the page. Already-downloaded files are skipped.

### Download all PDFs

```bash
python scraper.py
```

Saves to `./pdfs/` (created automatically).

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

### All options

```
usage: scraper.py [-h] [-o OUTPUT] [--list] [--url URL]

options:
  -h, --help            show this help message and exit
  -o, --output OUTPUT   Output directory (default: ./pdfs)
  --list                List PDFs without downloading
  --url URL             Page URL to scrape
```

### Example output

```
Fetching: https://www.manchesternh.gov/Departments/Planning-and-Comm-Dev/Zoning-Board/Project-Applications

Found 9 PDF(s):

Downloading to: /home/user/manchesternh_zoning_pdf_scraper/pdfs

  [ok]   2026-03-12_ZBA2026-016_YOUVILLE_STREET_385_PACKET.PDF (4,112,384 bytes)
  [ok]   2026-03-12_ZBA2026-015_WEST_MITCHELL_STREET_247_PACKET.PDF (2,987,520 bytes)
  [skip] 2026-03-12_ZBA_AGENDA.PDF (already exists)

Done: 9/9 PDFs downloaded to 'pdfs'
```

---

## notify.py — New PDF checker with email alerts

Compares the current page against `manifest.json` to detect new PDFs. If any are found, downloads them and optionally sends an email notification. Updates `manifest.json` after each run.

### Check for new PDFs (no email)

```bash
python notify.py
```

### Check and send email if new PDFs found

```bash
NOTIFY_FROM=you@gmail.com \
NOTIFY_PASSWORD=yourapppassword \
NOTIFY_TO=recipient@example.com \
python notify.py --email
```

Multiple recipients are supported — separate with commas:

```bash
NOTIFY_TO="alice@example.com, bob@example.com" python notify.py --email
```

### Send a test email (verify config works)

```bash
NOTIFY_FROM=you@gmail.com \
NOTIFY_PASSWORD=yourapppassword \
NOTIFY_TO=recipient@example.com \
python notify.py --test-email
```

Sends a test message immediately, regardless of whether there are new PDFs.

### Dry run (see what's new without downloading or updating manifest)

```bash
python notify.py --dry-run
```

### All options

```
usage: notify.py [-h] [-o OUTPUT] [--email] [--test-email] [--dry-run] [--url URL]

options:
  -h, --help            show this help message and exit
  -o, --output OUTPUT   Directory to download new PDFs into (default: ./pdfs)
  --email               Send email when new PDFs are found
  --test-email          Send a test email immediately
  --dry-run             Print new PDFs without downloading or updating manifest
  --url URL             Page URL to scrape
```

### Environment variables

| Variable | Description |
|---|---|
| `NOTIFY_FROM` | Gmail address to send from |
| `NOTIFY_PASSWORD` | Gmail App Password (see below) |
| `NOTIFY_TO` | Recipient address(es), comma-separated |

#### Getting a Gmail App Password

1. Go to [myaccount.google.com](https://myaccount.google.com)
2. Click **Security** → **2-Step Verification** (must be enabled)
3. Scroll to the bottom → **App passwords**
4. Type any name (e.g. `zba-scraper`) → click **Create**
5. Google shows a 16-character code — copy it **without spaces**

---

## Automated monitoring via GitHub Actions

The workflow at `.github/workflows/check.yml` runs `notify.py --email` every 15 minutes using GitHub's scheduler. When new PDFs are found, it emails all recipients and commits the updated `manifest.json` back to the repo so state persists across runs.

> **Note:** GitHub's cron scheduler is best-effort on free accounts — runs may be a few minutes late under load but will not be skipped.

### One-time setup

#### 1. Fork or clone the repo to your GitHub account

The Actions workflow runs on your own repo, so you need your own copy.

#### 2. Install the GitHub CLI

```bash
# Windows
winget install GitHub.cli

# macOS
brew install gh

# Linux
sudo apt install gh   # or see https://github.com/cli/cli
```

#### 3. Authenticate

```bash
gh auth login
```

Choose **GitHub.com → HTTPS → Login with a web browser** and follow the prompts.

#### 4. Add the three secrets

```bash
gh secret set NOTIFY_FROM    # your Gmail address
gh secret set NOTIFY_PASSWORD # your Gmail App Password (no spaces)
gh secret set NOTIFY_TO       # recipient address(es), comma-separated
```

Each command will prompt you to type/paste the value.

Or set them via the GitHub web UI:
**Settings → Secrets and variables → Actions → New repository secret**

#### 5. Verify with a test email

Trigger a test run manually from the CLI:

```bash
gh workflow run check.yml --field test_email=yes
```

Or from the web UI:
1. Go to **Actions → Check for new ZBA PDFs**
2. Click **Run workflow**
3. Set **"Send a test email"** to `yes`
4. Click the green **Run workflow** button

You should receive a test email within ~30 seconds.

### Resetting the manifest

To clear history and re-notify about all currently posted PDFs on the next run:

```bash
rm manifest.json
git add manifest.json
git commit -m "reset manifest"
git push
```

### Monitoring runs

#### View recent runs in the browser

Go to **github.com/davidxue1989/manchesternh_zoning_pdf_scraper/actions** — each run shows a green checkmark (success) or red X (failure).

#### View recent runs from the CLI

```bash
gh run list --repo davidxue1989/manchesternh_zoning_pdf_scraper
```

#### Inspect the log of a specific run

```bash
# Get the run ID from the list above, then:
gh run view <run-id> --repo davidxue1989/manchesternh_zoning_pdf_scraper --log
```

Or just the failed steps:

```bash
gh run view <run-id> --repo davidxue1989/manchesternh_zoning_pdf_scraper --log-failed
```

#### Watch a run live

```bash
gh run watch --repo davidxue1989/manchesternh_zoning_pdf_scraper
```

#### Check if new PDFs were found

When new PDFs are detected, the workflow commits an updated `manifest.json` with the commit message `chore: update PDF manifest [skip ci]`. You can see these commits on the repo's main page or via:

```bash
git log --oneline
```

GitHub also sends you a notification email if a workflow **fails** — this is on by default under **Settings → Notifications**.

### Adjusting the schedule

Edit the cron expression in `.github/workflows/check.yml`:

```yaml
- cron: "*/15 * * * *"   # every 15 minutes (current)
- cron: "0 * * * *"      # every hour
- cron: "0 13 * * 1,4"   # Mon and Thu at 9 AM ET
```

Use [crontab.guru](https://crontab.guru) to build expressions.

---

## Design

### Page structure

The Manchester NH website runs on [DotNetNuke (DNN)](https://www.dnnsoftware.com/), a .NET CMS. The Project Applications page contains a custom DNN module (`ModManchesterDynamicFileListC`) that renders a `<ul>` list of `<a>` tags pointing directly to PDF files hosted under:

```
/Portals/2/Departments/pcd/BoardsCommissions/ZBA/Project Applications/
```

### How scraper.py works

1. **Fetch** — `urllib.request` fetches the page HTML with a browser-like `User-Agent` header.
2. **Parse** — `BeautifulSoup` locates the `ModManchesterDynamicFileListC` div and collects all `<a href="...pdf">` links. Falls back to scanning the full page if the module div is not found.
3. **URL encoding** — The server path contains spaces (`Project Applications/`). The path component is URL-encoded before each download request.
4. **Download** — Each PDF is saved using its display name from the page. Files already on disk are skipped, making repeated runs safe and incremental.
5. **Filename sanitization** — Characters illegal on Windows/macOS/Linux (`\ / : * ? " < > |`) are stripped.

### How notify.py works

1. **Load manifest** — Reads `manifest.json` (a JSON array of filenames). Empty set if the file doesn't exist.
2. **Diff** — Fetches the current page and compares filenames against the manifest. Anything not in the manifest is "new".
3. **Download** — New PDFs are downloaded to the output directory.
4. **Update manifest** — All currently listed filenames (not just new ones) are written back to `manifest.json`.
5. **Email** — If `--email` is set and new PDFs were found, sends a notification via Gmail SMTP (SSL, port 465) using Python's stdlib `smtplib`.

### Dependencies

| Library | Purpose |
|---|---|
| `beautifulsoup4` | HTML parsing to extract PDF links |

Everything else (`urllib`, `pathlib`, `argparse`, `smtplib`, `ssl`, `json`) is Python stdlib — no extra packages needed for email.
