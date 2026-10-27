"""
filer.py - Names and files each PDF using one standard.

Folder:  organized/AP/2026-11/   (AP or AR, then the month of the document's date)
Name:    2026-11-14_Acme-Office-Supplies(NWA)_Invoice-INV-1042_1250.00.pdf
         date _ counterparty(group entity) _ type-number _ amount

Duplicates are skipped twice over:
  - same file content (SHA-256), e.g. a reminder email with the same attachment;
  - same business key (type + counterparty + number + amount), e.g. a re-sent invoice.
The index lives in organized/.index.json, so running again never duplicates files.

Protected PDFs are saved as an unlocked copy, so nobody needs the password later.
"""

import hashlib
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfWriter

from . import ai_fallback
from .config import Config
from .extract import Fields, extract_fields, short_name
from .mailbox import Email
from .pdf_reader import OTHER, classify, extract_text, open_pdf

LABELS = {"invoice": "Invoice", "remittance": "Remittance", "receipt": "Receipt", OTHER: "Document"}
INDEX_FILE = ".index.json"


@dataclass
class Filed:
    path: Path | None          # None when skipped
    status: str                # filed | duplicate | error
    fields: Fields | None = None
    source_name: str = ""
    note: str = ""


class Index:
    """Remembers what was already filed (content hashes and business keys)."""

    def __init__(self, output_dir: Path):
        self.path = output_dir / INDEX_FILE
        data = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.hashes = set(data.get("hashes", []))
        self.keys = set(data.get("keys", []))

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"hashes": sorted(self.hashes), "keys": sorted(self.keys)},
                                        indent=2))


def _business_key(f: Fields) -> str | None:
    if not f.number:
        return None
    return f"{f.doc_type}|{f.counterparty}|{f.number}|{f.amount}"


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "-", name)


def _free_path(path: Path) -> Path:
    """Never overwrite: two different documents with the same name get _2, _3..."""
    if not path.exists():
        return path
    i = 2
    while path.with_name(f"{path.stem}_{i}{path.suffix}").exists():
        i += 1
    return path.with_name(f"{path.stem}_{i}{path.suffix}")


def build_name(f: Fields) -> str:
    party = f.counterparty + (f"({f.entity_code})" if f.entity_code else "")
    if f.doc_type == OTHER:
        return _safe(f"{f.date}_Document.pdf")
    label = LABELS[f.doc_type] + (f"-{f.number}" if f.number else "")
    amount = f"{f.amount:.2f}" if f.amount is not None else "no-amount"
    ai_mark = "_AI" if f.ai_used else ""
    return _safe(f"{f.date}_{party}_{label}_{amount}{ai_mark}.pdf")


def file_document(name: str, content: bytes, email: Email, cfg: Config, index: Index) -> Filed:
    digest = hashlib.sha256(content).hexdigest()
    if digest in index.hashes:
        return Filed(None, "duplicate", source_name=name, note="same file already filed")

    reader, password = open_pdf(content, cfg.pdf_passwords)
    text = extract_text(reader, content)
    doc_type = classify(text)
    fields = extract_fields(text, doc_type, email.sender, cfg)

    # Backup extraction with a local AI model, only for what the rules missed.
    ai_used = False
    if doc_type != OTHER and len(text.strip()) >= 80 and \
            (fields.counterparty == "Unknown" or fields.amount is None or fields.date is None):
        party, amount, date, is_bill = ai_fallback.ask(text)
        if is_bill:
            if fields.counterparty == "Unknown" and party:
                fields.counterparty, ai_used = short_name(party), True
            if fields.amount is None and amount is not None:
                fields.amount, ai_used = amount, True
            if fields.date is None and date:
                fields.date, fields.date_source, ai_used = date, "ai", True
    fields.ai_used = ai_used

    if fields.date is None:                       # last resort: the day the email arrived
        fields.date, fields.date_source = email.received[:10], "email"

    key = _business_key(fields)
    if key and key in index.keys:
        index.hashes.add(digest)
        return Filed(None, "duplicate", fields, name, "same document number already filed")

    group = fields.direction if doc_type != OTHER else "Other"
    folder = Path(cfg.output_dir) / group / fields.date[:7]
    folder.mkdir(parents=True, exist_ok=True)
    target = _free_path(folder / build_name(fields))

    if password is not None or reader.is_encrypted:  # save an unlocked copy
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        buffer = io.BytesIO()
        writer.write(buffer)
        target.write_bytes(buffer.getvalue())
    else:
        target.write_bytes(content)

    index.hashes.add(digest)
    if key:
        index.keys.add(key)
    note = "unlocked copy" if reader.is_encrypted else ""
    return Filed(target, "filed", fields, name, note)
