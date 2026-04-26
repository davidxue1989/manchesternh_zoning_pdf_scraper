"""
NH Board Agenda & PDF change notifier.

Checks all sources in SOURCES (scraper.py) plus Manchester NH PDF pages.
New items are compared against manifest.json; email is sent when anything new
is found.

Manifest key format:
  Manchester PDFs  → filename string  (e.g. "September 9, 2025.pdf")
  All other items  → "{type}::{url}"  (Merrimack keeps legacy "merrimack::{url}")

Environment variables (required when --email is used):
  NOTIFY_FROM      sender Gmail address
  NOTIFY_PASSWORD  Gmail app password (https://myaccount.google.com/apppasswords)
  NOTIFY_TO        recipient address (comma-separated for multiple)
"""

import argparse
import json
import os
import smtplib
import ssl
import sys
import urllib.parse
from email.mime.text import MIMEText
from pathlib import Path

from scraper import (
    PAGE_URLS,
    SOURCES,
    fetch_pdf_links,
    fetch_agenda_links,
    fetch_agendacenter_links,
    fetch_archive_links,
    fetch_legistar_links,
    fetch_civicclerk_links,
    download_pdf,
    sanitize_filename,
)

MANIFEST_PATH = Path(__file__).parent / "manifest.json"
GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 465


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def load_manifest() -> set[str]:
    if MANIFEST_PATH.exists():
        return set(json.loads(MANIFEST_PATH.read_text()))
    return set()


def save_manifest(seen: set[str]) -> None:
    MANIFEST_PATH.write_text(json.dumps(sorted(seen), indent=2))


def _manifest_key(source_type: str, item_url: str) -> str:
    """Return a stable manifest key, preserving the legacy 'merrimack::' prefix."""
    if "merrimacknh.gov" in item_url:
        return f"merrimack::{item_url}"
    return f"{source_type}::{item_url}"


# ---------------------------------------------------------------------------
# Source dispatcher
# ---------------------------------------------------------------------------

def fetch_source(source: dict) -> list[dict]:
    """Fetch all current agenda/document items for one source config dict."""
    t, url = source["type"], source["url"]
    try:
        if t == "node_agenda":
            return fetch_agenda_links(url)
        if t == "agendacenter":
            return fetch_agendacenter_links(url)
        if t == "archive":
            return fetch_archive_links(url)
        if t == "legistar":
            return fetch_legistar_links(url, board_filter=source.get("board_filter"))
        if t == "civicclerk":
            return fetch_civicclerk_links(url)
        raise ValueError(f"Unknown source type: {t!r}")
    except Exception as e:
        print(f"  [err] {source['label']} ({url}): {e}", file=sys.stderr)
        return []


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_email(subject: str, body: str) -> None:
    sender = os.environ["NOTIFY_FROM"]
    password = os.environ["NOTIFY_PASSWORD"]
    recipients = [r.strip() for r in os.environ["NOTIFY_TO"].split(",")]
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(GMAIL_SMTP_HOST, GMAIL_SMTP_PORT, context=ctx) as smtp:
        smtp.login(sender, password)
        smtp.sendmail(sender, recipients, msg.as_string())
    print(f"Email sent to: {', '.join(recipients)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Check all NH board sources for new agendas/PDFs and optionally email a notification."
    )
    parser.add_argument("-o", "--output", default="pdfs",
                        help="Directory to download new PDFs into (default: ./pdfs)")
    parser.add_argument("--email", action="store_true",
                        help="Send email when new items are found "
                             "(requires NOTIFY_FROM, NOTIFY_PASSWORD, NOTIFY_TO env vars)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print new items without downloading or updating the manifest")
    parser.add_argument("--test-email", action="store_true",
                        help="Send a test email immediately (requires email env vars)")
    args = parser.parse_args()

    if args.test_email:
        send_email(
            "[NH Scraper] Test email",
            "This is a test from the NH board agenda scraper.\n\nEmail notifications are working correctly.",
        )
        return

    seen = load_manifest()
    all_keys_this_run: list[str] = []          # every key seen (for manifest update)
    new_by_label: dict[str, list[dict]] = {}   # label -> list of new items
    new_manchester_pdfs: list[tuple] = []

    # --- Manchester NH ZBA / Planning Board PDFs ---
    for url in PAGE_URLS:
        for p in fetch_pdf_links(url):
            all_keys_this_run.append(p["filename"])
            if p["filename"] not in seen:
                new_manchester_pdfs.append((p, url))

    # --- All SOURCES ---
    for source in SOURCES:
        items = fetch_source(source)
        label = source["label"]
        t = source["type"]
        for item in items:
            key = _manifest_key(t, item["url"])
            all_keys_this_run.append(key)
            if key not in seen:
                new_by_label.setdefault(label, []).append(item)

    total_new = len(new_manchester_pdfs) + sum(len(v) for v in new_by_label.values())

    if total_new == 0:
        print("No new items found.")
        return

    # Print summary
    if new_manchester_pdfs:
        print(f"\n{len(new_manchester_pdfs)} new Manchester PDF(s):")
        for p, url in new_manchester_pdfs:
            print(f"  {p['filename']}  ({url})")

    for label, items in new_by_label.items():
        print(f"\n{len(items)} new item(s) — {label}:")
        for item in items:
            year = f"[{item['year']}] " if item.get("year") else ""
            print(f"  {year}{item['title']}")
            print(f"    {item['url']}")

    if args.dry_run:
        return

    # Download new Manchester PDFs
    if new_manchester_pdfs:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        for pdf, _ in new_manchester_pdfs:
            filename = sanitize_filename(pdf["filename"])
            if not filename.lower().endswith(".pdf"):
                filename += ".pdf"
            download_pdf(pdf["url"], output_dir / filename)

    # Update manifest
    seen.update(all_keys_this_run)
    save_manifest(seen)
    print(f"\nManifest updated ({len(seen)} total entries).")

    # Send email
    if args.email:
        email_parts: list[str] = []
        subject_parts: list[str] = []

        if new_manchester_pdfs:
            subject_parts.append(f"{len(new_manchester_pdfs)} Manchester PDF(s)")
            email_parts.append("=== Manchester NH ZBA / Planning Board — New PDFs ===\n")
            for p, _ in new_manchester_pdfs:
                email_parts.append(f"  {p['filename']}")
                email_parts.append(f"  {urllib.parse.quote(p['url'], safe=':/?=&#')}\n")

        for label, items in new_by_label.items():
            subject_parts.append(f"{len(items)} {label}")
            email_parts.append(f"=== {label} — New Items ===\n")
            for item in items:
                year = f"[{item['year']}] " if item.get("year") else ""
                email_parts.append(f"  {year}{item['title']}")
                email_parts.append(f"  {item['url']}\n")

        subject = "[NH Scraper] " + ", ".join(subject_parts)
        send_email(subject, "\n".join(email_parts))


if __name__ == "__main__":
    main()
