"""
Check the Manchester NH Zoning Board page for new PDFs and email a notification.
Also monitors Merrimack NH board pages for new agendas.

New items are determined by comparing against manifest.json.
Manchester PDFs are tracked by filename; Merrimack agendas by URL (prefixed
with "merrimack::").

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
    MERRIMACK_URLS,
    fetch_pdf_links,
    fetch_agenda_links,
    download_pdf,
    sanitize_filename,
)

MANIFEST_PATH = Path(__file__).parent / "manifest.json"
GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 465


def load_manifest() -> set[str]:
    if MANIFEST_PATH.exists():
        return set(json.loads(MANIFEST_PATH.read_text()))
    return set()


def save_manifest(seen: set[str]) -> None:
    MANIFEST_PATH.write_text(json.dumps(sorted(seen), indent=2))


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


def main():
    parser = argparse.ArgumentParser(
        description="Check for new ZBA PDFs and optionally email a notification."
    )
    parser.add_argument(
        "-o", "--output", default="pdfs",
        help="Directory to download new PDFs into (default: ./pdfs)",
    )
    parser.add_argument(
        "--email", action="store_true",
        help="Send an email notification when new PDFs are found "
             "(requires NOTIFY_FROM, NOTIFY_PASSWORD, NOTIFY_TO env vars)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print new PDFs without downloading or updating the manifest",
    )
    parser.add_argument(
        "--test-email", action="store_true",
        help="Send a test email immediately regardless of new PDFs "
             "(requires NOTIFY_FROM, NOTIFY_PASSWORD, NOTIFY_TO env vars)",
    )
    args = parser.parse_args()

    if args.test_email:
        send_email(
            "[NH Scraper] Test email",
            "This is a test from the NH PDF/agenda scraper.\n\nEmail notifications are working correctly.",
        )
        return

    seen = load_manifest()
    # (item_dict, source_url) pairs — item has at minimum "url" and either "filename" or "title"
    new_manchester_pdfs = []
    new_merrimack_agendas = []
    all_manchester_keys = []   # manifest keys for everything seen this run
    all_merrimack_keys = []

    # --- Manchester NH ZBA / Planning Board PDFs ---
    for url in PAGE_URLS:
        all_pdfs = fetch_pdf_links(url)
        for p in all_pdfs:
            all_manchester_keys.append(p["filename"])
            if p["filename"] not in seen:
                new_manchester_pdfs.append((p, url))

    # --- Merrimack NH agendas ---
    for url in MERRIMACK_URLS:
        try:
            all_agendas = fetch_agenda_links(url)
        except Exception as e:
            print(f"  [err] Could not fetch {url}: {e}", file=sys.stderr)
            continue
        for item in all_agendas:
            key = f"merrimack::{item['url']}"
            all_merrimack_keys.append(key)
            if key not in seen:
                new_merrimack_agendas.append((item, url))

    total_new = len(new_manchester_pdfs) + len(new_merrimack_agendas)

    if total_new == 0:
        print("No new items found.")
        return

    if new_manchester_pdfs:
        print(f"\n{len(new_manchester_pdfs)} new Manchester PDF(s):")
        for p, url in new_manchester_pdfs:
            print(f"  {p['filename']}  ({url})")

    if new_merrimack_agendas:
        print(f"\n{len(new_merrimack_agendas)} new Merrimack agenda(s):")
        for item, url in new_merrimack_agendas:
            print(f"  [{item.get('year', '?')}] {item['title']}  {item['url']}")

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
    seen.update(all_manchester_keys)
    seen.update(all_merrimack_keys)
    save_manifest(seen)
    print(f"\nManifest updated ({len(seen)} total entries).")

    # Send email
    if args.email:
        email_parts: list[str] = []
        subject_parts: list[str] = []

        if new_manchester_pdfs:
            subject_parts.append(f"{len(new_manchester_pdfs)} Manchester PDF(s)")
            email_parts.append("=== Manchester NH ZBA / Planning Board — New PDFs ===\n")
            for p, source_url in new_manchester_pdfs:
                encoded_url = urllib.parse.quote(p["url"], safe=":/?=&#")
                email_parts.append(f"  {p['filename']}")
                email_parts.append(f"  {encoded_url}\n")
            email_parts.append(f"Source(s): {', '.join(PAGE_URLS)}\n")

        if new_merrimack_agendas:
            subject_parts.append(f"{len(new_merrimack_agendas)} Merrimack agenda(s)")
            email_parts.append("=== Merrimack NH — New Agendas ===\n")
            for item, source_url in new_merrimack_agendas:
                year_label = f"[{item['year']}] " if item.get("year") else ""
                email_parts.append(f"  {year_label}{item['title']}")
                email_parts.append(f"  {item['url']}\n")
            email_parts.append(f"Source(s): {', '.join(MERRIMACK_URLS)}\n")

        subject = "[NH Scraper] " + ", ".join(subject_parts)
        send_email(subject, "\n".join(email_parts))


if __name__ == "__main__":
    main()
