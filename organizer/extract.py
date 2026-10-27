"""
extract.py - Reads the business fields of a document with regular expressions:
counterparty (vendor or customer), group entity, document number, amount,
reference date and, for remittance advices, the invoices that were paid.

It also decides the direction:
  AP (accounts payable)    - a vendor bills us, or we keep a receipt of a purchase.
  AR (accounts receivable) - we bill a customer, or a customer tells us what it paid.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime

from .config import Config
from .pdf_reader import INVOICE, OTHER, RECEIPT, REMITTANCE, normalize

AP, AR = "AP", "AR"


@dataclass
class Fields:
    doc_type: str
    direction: str = AP
    counterparty: str = "Unknown"
    entity_code: str | None = None
    number: str | None = None
    amount: float | None = None
    date: str | None = None            # ISO YYYY-MM-DD
    date_source: str = "document"      # document | email | ai
    invoices_paid: list[str] = field(default_factory=list)
    ai_used: bool = False              # True when the local AI filled a field


# ---------------------------------------------------------------- amounts
_MONEY = r"(?:USD|US\$|\$)?\s*(-?[\d,]+\.\d{2})"
_AMOUNT_LABELS = {
    INVOICE: ["balance due", "amount due", "total due", "invoice total", "total"],
    REMITTANCE: ["total payment", "payment amount", "total paid", "amount paid", "total"],
    RECEIPT: ["amount paid", "total paid", "total charged", "total"],
}


def _to_float(s: str) -> float:
    return float(s.replace(",", ""))


def extract_amount(text: str, doc_type: str) -> float | None:
    """Amount after the most specific label for this type; else the largest $ amount."""
    for label in _AMOUNT_LABELS.get(doc_type, ["total"]):
        m = re.search(rf"{label}\b[^\d$\n]{{0,25}}{_MONEY}", text, re.IGNORECASE)
        if m:
            return _to_float(m.group(1))
    found = [_to_float(a) for a in re.findall(r"(?:USD|\$)\s*([\d,]+\.\d{2})", text)]
    return max(found) if found else None


# ------------------------------------------------------------------ dates
_DATE = (r"(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2}|[A-Za-z]{3,9}\.? \d{1,2},? \d{4}"
         r"|\d{1,2}[- ][A-Za-z]{3}[- ]\d{4})")
_DATE_FORMATS = ["%m/%d/%Y", "%Y-%m-%d", "%b %d %Y", "%B %d %Y", "%d-%b-%Y", "%d %b %Y"]
_DATE_LABELS = {
    INVOICE: ["due date", "payment due", "invoice date", "date"],
    REMITTANCE: ["payment date", "settlement date", "date"],
    RECEIPT: ["date paid", "payment date", "paid on", "date"],
}


def parse_date(raw: str) -> str | None:
    """'Oct 15, 2026', '10/15/2026', '15-OCT-2026', '2026-10-15' -> '2026-10-15'."""
    raw = raw.replace(",", "").replace(".", "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw.title() if "%b" in fmt or "%B" in fmt else raw,
                                     fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def extract_date(text: str, doc_type: str) -> str | None:
    for label in _DATE_LABELS.get(doc_type, ["date"]):
        m = re.search(rf"\b{label}\b[^\n\d]{{0,20}}?\b{_DATE}", text, re.IGNORECASE)
        if m and (iso := parse_date(m.group(1))):
            return iso
    return None


# ---------------------------------------------------------------- numbers
_NUMBER_PATTERNS = {
    INVOICE: r"invoice\s*(?:number|no\.?|#)\s*:?\s*#?\s*([A-Z0-9][A-Z0-9-]{2,})",
    RECEIPT: r"receipt\s*(?:number|no\.?|#)\s*:?\s*#?\s*([A-Z0-9][A-Z0-9-]{2,})",
    REMITTANCE: r"(?:payment|remittance)\s*(?:reference|number|no\.?|id|#)\s*:?\s*#?\s*([A-Z0-9][A-Z0-9-]{2,})",
}


def extract_number(text: str, doc_type: str) -> str | None:
    pattern = _NUMBER_PATTERNS.get(doc_type)
    m = re.search(pattern, text, re.IGNORECASE) if pattern else None
    return m.group(1).upper() if m else None


def extract_invoices_paid(text: str) -> list[str]:
    """Invoice numbers listed in a remittance advice (e.g. INV-2031, INV-2032)."""
    found = re.findall(r"\b((?:INV|BILL)[-#]?\d[\w-]*)", text, re.IGNORECASE)
    return list(dict.fromkeys(f.upper() for f in found))


# ----------------------------------------------------------- counterparty
_COMPANY_SUFFIXES = {"llc", "inc", "corp", "corporation", "ltd", "co", "company", "plc", "lp", "llp"}
_LABEL_WORDS = {"invoice", "receipt", "remittance", "advice", "payment", "bill", "to", "from", "page"}


def short_name(raw: str) -> str:
    """'Acme Office Supplies, LLC' -> 'Acme-Office-Supplies' (safe for file names)."""
    words = [w for w in re.sub(r"[^\w&\s-]", " ", raw).split()
             if w.lower().strip(".") not in _COMPANY_SUFFIXES]
    return "-".join(words[:3]) or "Unknown"


def _issuer(text: str) -> str | None:
    """The letterhead: first line with letters that is not just a title like 'INVOICE'."""
    for line in text.splitlines():
        clean = line.strip()
        words = set(re.findall(r"[a-z]+", clean.lower()))
        if re.search(r"[A-Za-z]{3}", clean) and not words <= _LABEL_WORDS:
            return clean
    return None


def _after_label(text: str, labels: list[str]) -> str | None:
    """The company name right after 'Bill To', 'Paid by', etc. (same line or next line)."""
    for label in labels:
        m = re.search(rf"{label}\s*:?\s*\n?\s*([A-Za-z][^\n]+)", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _entity_in(text: str, cfg: Config):
    """The group entity whose tax ID or name appears in the text (or None)."""
    digits = re.sub(r"\D", "", text)
    norm = normalize(text)
    for e in cfg.entities:
        tax = re.sub(r"\D", "", e.tax_id)
        if (tax and tax in digits) or normalize(e.name) in norm:
            return e
    return None


def _is_own(name: str | None, cfg: Config) -> bool:
    if not name:
        return False
    n = normalize(name)
    return any(normalize(e.name) in n or n in normalize(e.name) for e in cfg.entities) \
        or normalize(cfg.company_name) in n


def _name_from_sender(sender: str, cfg: Config) -> str | None:
    """Vendor name from the sender's domain, unless it is our own domain or a billing platform."""
    domain = sender.split("@")[-1].lower() if "@" in sender else ""
    if not domain or any(domain == d or domain.endswith("." + d) for d in cfg.own_domains):
        return None
    if domain in cfg.vendor_aliases:
        return cfg.vendor_aliases[domain]
    if any(domain == p or domain.endswith("." + p) for p in cfg.platform_domains):
        return None
    return domain.split(".")[-2].capitalize() if domain.count(".") else None


def extract_fields(text: str, doc_type: str, sender: str, cfg: Config) -> Fields:
    f = Fields(doc_type=doc_type)
    if doc_type == OTHER:
        return f

    issuer = _issuer(text)
    entity = _entity_in(text, cfg)
    f.entity_code = entity.code if entity else None

    if doc_type == INVOICE and _is_own(issuer, cfg):
        f.direction, party = AR, _after_label(text, ["bill to", "billed to", "customer"])
    elif doc_type == REMITTANCE:
        payer = _after_label(text, ["paid by", "payer", "from"]) or issuer
        if _is_own(payer, cfg):        # we paid a vendor and sent them this advice
            f.direction, party = AP, _after_label(text, ["paid to", "payee", "vendor"])
        else:                          # a customer paid us: cash application
            f.direction, party = AR, payer
        f.invoices_paid = extract_invoices_paid(text)
    else:
        f.direction, party = AP, issuer

    # Highest confidence first: known brand in the PDF, known sender, then the PDF itself.
    norm = normalize(text)
    alias = next((name for key, name in cfg.content_aliases.items() if key in norm), None)
    if alias and not (f.direction == AR and doc_type == INVOICE):
        party = alias
    elif f.direction == AP and doc_type != REMITTANCE and not party:
        party = _name_from_sender(sender, cfg)

    if party and not _is_own(party, cfg):
        f.counterparty = short_name(party)
    f.number = extract_number(text, doc_type)
    f.amount = extract_amount(text, doc_type)
    f.date = extract_date(text, doc_type)
    return f
