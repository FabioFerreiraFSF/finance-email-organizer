"""
Finance Email Organizer - command line.

    python -m organizer --demo                         # sample inbox, no login needed
    python -m organizer --outlook                      # your 50 newest emails
    python -m organizer --outlook --since 2026-10-01 --until 2026-10-31

For each email: take the PDF attachments, plus PDFs linked from trusted domains,
then read, classify, name and file each one. Every step is isolated: if one
email fails, the run moves on to the next.

At the end it writes two CSV files to the output folder:
  filing_log.csv   - one line per document (ready for Excel or Power BI)
  remittances.csv  - customer payments and the invoices they cover (cash application)
"""

import argparse
import csv
import os
import time
from pathlib import Path

from .config import load_config
from .filer import Index, file_document
from .links import pdfs_from_links
from .mailbox import EmlFolder, GraphMailbox

SAMPLE_INBOX = Path(__file__).resolve().parent.parent / "samples" / "inbox"


def _append_csv(path: Path, header: list[str], rows: list[list]):
    if not rows:
        return
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new:
            writer.writerow(header)
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Files invoices, remittance advices and "
                                                 "receipts from a mailbox.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--demo", action="store_true", help="use the fake sample inbox")
    source.add_argument("--outlook", action="store_true", help="read your Outlook inbox")
    source.add_argument("--eml", metavar="FOLDER", help="read .eml files from a folder")
    parser.add_argument("--since", help="first day, YYYY-MM-DD")
    parser.add_argument("--until", help="last day, YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=50, help="newest N emails (default 50)")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--no-links", action="store_true", help="do not follow links in emails")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.demo:
        os.environ.setdefault("PDF_PASSWORDS", "demo1234")   # the sample protected PDF
        args.no_links = True                                 # the demo runs offline
        mailbox = EmlFolder(SAMPLE_INBOX)
    elif args.eml:
        mailbox = EmlFolder(args.eml)
    else:
        from .auth import get_token
        mailbox = GraphMailbox(get_token())

    start = time.time()
    output = Path(cfg.output_dir)
    index = Index(output)
    log_rows, remittance_rows = [], []
    counts = {"filed": 0, "duplicate": 0, "error": 0}

    emails = list(mailbox.emails(limit=args.limit, since=args.since, until=args.until))
    for email in reversed(emails):                   # oldest first, like reading the inbox
        files = email.pdf_attachments()
        if not args.no_links and email.sender.lower() not in cfg.attachments_only_senders:
            files += pdfs_from_links(email.body_html, cfg.trusted_link_domains)
        if not files:
            continue

        print(f"\n- {email.received[:10]} | {email.sender} | {email.subject}")
        for name, content in files:
            try:
                result = file_document(name, content, email, cfg, index)
            except Exception as e:                       # one bad PDF never stops the run
                counts["error"] += 1
                print(f"  ERROR {name}: {e}")
                continue

            counts[result.status] += 1
            if result.status == "duplicate":
                print(f"  skipped {name} ({result.note})")
                continue

            f = result.fields
            check = "   <- email date used, please CHECK" if f.date_source == "email" else ""
            print(f"  saved  {result.path.relative_to(output)}{check}")
            log_rows.append([f.date, f.direction if f.doc_type != "other" else "", f.doc_type,
                             f.counterparty, f.entity_code or "", f.number or "",
                             f"{f.amount:.2f}" if f.amount is not None else "",
                             f.date_source, email.sender, str(result.path)])
            if f.doc_type == "remittance" and f.direction == "AR":
                remittance_rows.append([f.date, f.counterparty, f.number or "",
                                        f"{f.amount:.2f}" if f.amount is not None else "",
                                        " ".join(f.invoices_paid)])

    index.save()
    _append_csv(output / "filing_log.csv",
                ["date", "direction", "type", "counterparty", "entity", "number", "amount",
                 "date_source", "sender", "file"], log_rows)
    _append_csv(output / "remittances.csv",
                ["payment_date", "customer", "payment_ref", "amount", "invoices_paid"],
                remittance_rows)

    seconds = int(time.time() - start)
    print(f"\nDone in {seconds // 60}m {seconds % 60}s: {counts['filed']} filed, "
          f"{counts['duplicate']} duplicates skipped, {counts['error']} errors. "
          f"See the '{output}' folder.")


if __name__ == "__main__":
    main()
