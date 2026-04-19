"""
Check the Manchester NH Zoning Board page for new PDFs and email a notification.

New PDFs are determined by comparing against manifest.json (list of previously
seen filenames). New files are downloaded and the manifest is updated.

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

from scraper import PAGE_URLS, fetch_pdf_links, download_pdf, sanitize_filename

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
            "[Manchester ZBA] Test email",
            "This is a test from the Manchester NH ZBA PDF scraper.\n\nEmail notifications are working correctly.",
        )
        return

    seen = load_manifest()
    all_new_pdfs = []  # (pdf_dict, source_url) pairs
    all_seen_this_run = []

    for url in PAGE_URLS:
        all_pdfs = fetch_pdf_links(url)
        new_pdfs = [p for p in all_pdfs if p["filename"] not in seen]
        all_new_pdfs.extend((p, url) for p in new_pdfs)
        all_seen_this_run.extend(all_pdfs)

    if not all_new_pdfs:
        print("No new PDFs found.")
        return

    print(f"\n{len(all_new_pdfs)} new PDF(s) found:")
    for p, url in all_new_pdfs:
        print(f"  {p['filename']}  ({url})")

    if args.dry_run:
        return

    # Download new PDFs
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    for pdf, _ in all_new_pdfs:
        filename = sanitize_filename(pdf["filename"])
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        download_pdf(pdf["url"], output_dir / filename)

    # Update manifest with all currently listed PDFs
    seen.update(p["filename"] for p in all_seen_this_run)
    save_manifest(seen)
    print(f"\nManifest updated ({len(seen)} total entries).")

    # Send email
    if args.email:
        subject = f"[Manchester ZBA] {len(all_new_pdfs)} new PDF(s) posted"
        lines = ["New PDFs are available on the Manchester NH Zoning Board page:\n"]
        for p, source_url in all_new_pdfs:
            encoded_url = urllib.parse.quote(p['url'], safe=":/?=&#")
            lines.append(f"  {p['filename']}")
            lines.append(f"  {encoded_url}\n")
        lines.append(f"\nSources: {', '.join(PAGE_URLS)}")
        send_email(subject, "\n".join(lines))


if __name__ == "__main__":
    main()
