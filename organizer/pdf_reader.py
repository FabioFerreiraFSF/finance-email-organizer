"""
pdf_reader.py - The READING layer. Deterministic (no AI):
  1. Opens a PDF, unlocking it with a known password when needed.
  2. Extracts the text of every page (OCR as a fallback for scanned PDFs).
  3. Classifies the document: invoice, remittance advice, receipt or other.

It never renames or moves files. That is filer.py's job.
"""

import io
import os
import re
import shutil
import unicodedata

from pypdf import PdfReader

INVOICE, REMITTANCE, RECEIPT, OTHER = "invoice", "remittance", "receipt", "other"


def open_pdf(source, passwords=()):
    """Returns (reader, password_used). source is a path or bytes.

    Tries an empty password first (some PDFs only have an owner password),
    then each known password. Raises ValueError if none works.
    """
    reader = PdfReader(io.BytesIO(source) if isinstance(source, bytes) else source)
    if not reader.is_encrypted:
        return reader, None
    for password in ["", *passwords]:
        if reader.decrypt(password):
            return reader, password or None
    raise ValueError("Protected PDF and no known password opened it. "
                     "Add the password to PDF_PASSWORDS in your .env file.")


def extract_text(reader, source=None) -> str:
    """Joins the text of all pages. Scanned PDFs (no text layer) go through OCR."""
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if source is not None and len(text.strip()) < 20:
        return _ocr(source) or text
    return text


def _ocr(source) -> str:
    """OCR for image-only PDFs. Optional: needs PyMuPDF, pytesseract and Tesseract installed."""
    try:
        import fitz
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""
    tesseract = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
    if not tesseract:
        return ""
    pytesseract.pytesseract.tesseract_cmd = tesseract
    doc = fitz.open(stream=source, filetype="pdf") if isinstance(source, bytes) else fitz.open(source)
    parts = []
    for page in doc:
        image = Image.open(io.BytesIO(page.get_pixmap(dpi=220).tobytes("png")))
        parts.append(pytesseract.image_to_string(image, lang="eng"))
    doc.close()
    return "\n".join(parts)


def _unspace(text: str) -> str:
    """Fixes PDFs that extract with a space between EVERY letter ("I n v o i c e")."""
    fixed = []
    for line in text.split("\n"):
        tokens = [t for t in line.split(" ") if t]
        if len(tokens) >= 8 and sum(len(t) == 1 for t in tokens) / len(tokens) > 0.6:
            line = re.sub(r" {2,}", "\x00", line).replace(" ", "").replace("\x00", " ")
        fixed.append(line)
    return "\n".join(fixed)


def normalize(text: str) -> str:
    """Lowercase, no accents, single spaces: makes keyword matching robust."""
    nfkd = unicodedata.normalize("NFKD", _unspace(text))
    no_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(no_accents.split()).lower()


_REMITTANCE_SIGNS = ["remittance advice", "payment advice", "remittance details",
                     "ach payment", "invoices paid", "payment reference"]
_RECEIPT_SIGNS = ["receipt", "amount paid", "payment received", "paid on", "thank you for your payment",
                  "card ending", "transaction id"]
_INVOICE_SIGNS = ["invoice", "amount due", "balance due", "due date", "bill to", "invoice number",
                  "payment terms", "net 30", "remit to"]


def classify(text: str) -> str:
    """Returns 'invoice', 'remittance', 'receipt' or 'other'."""
    t = normalize(text)

    # 1) Remittance advice comes first: it always mentions the invoices it pays.
    if "remittance advice" in t or "payment advice" in t:
        return REMITTANCE

    # 2) A receipt says the money is already paid; an invoice still asks for it.
    if re.search(r"\breceipt\b", t) and not re.search(r"\b(amount|balance) due\b", t):
        return RECEIPT

    # 3) Score the remaining signals.
    scores = {
        REMITTANCE: sum(s in t for s in _REMITTANCE_SIGNS),
        RECEIPT: sum(s in t for s in _RECEIPT_SIGNS),
        INVOICE: sum(s in t for s in _INVOICE_SIGNS),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else OTHER
