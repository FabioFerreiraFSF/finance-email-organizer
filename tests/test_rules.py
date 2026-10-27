"""Unit tests for the rule-based reading: classification, fields and link safety."""

from organizer.config import load_config
from organizer.extract import AP, AR, extract_fields, parse_date, short_name
from organizer.links import is_trusted
from organizer.pdf_reader import INVOICE, OTHER, RECEIPT, REMITTANCE, classify

CFG = load_config("does-not-exist.json")      # falls back to config.example.json

VENDOR_INVOICE = """Acme Office Supplies LLC
INVOICE
Invoice Number: INV-1042
Due Date: Nov 13, 2026
Bill To: Northwind Advisory LLC (EIN 12-3456789)
Balance Due: $1,250.00"""

REMITTANCE_ADVICE = """Harbor Logistics Inc
REMITTANCE ADVICE
Paid by: Harbor Logistics Inc
Paid to: Northwind Advisory LLC
Payment Reference: ACH-55102
Payment Date: October 20, 2026
Invoice INV-2027 ..... $4,200.00
Invoice INV-2031 ..... $8,400.00
Total Payment: $12,600.00"""

RECEIPT_TEXT = """CloudDesk Software Inc
RECEIPT
Receipt Number: CD-40917
Date paid: Oct 21, 2026
Amount paid: $149.00"""


def test_classify():
    assert classify(VENDOR_INVOICE) == INVOICE
    assert classify(REMITTANCE_ADVICE) == REMITTANCE      # mentions invoices, still a remittance
    assert classify(RECEIPT_TEXT) == RECEIPT
    assert classify("Travel policy. Book flights 14 days in advance.") == OTHER


def test_spaced_out_text_is_fixed():
    assert classify("I N V O I C E  A m o u n t  D u e  $ 1 0 . 0 0  D u e  D a t e") == INVOICE


def test_vendor_invoice_fields():
    f = extract_fields(VENDOR_INVOICE, INVOICE, "billing@acme-supplies.example", CFG)
    assert (f.direction, f.counterparty, f.entity_code) == (AP, "Acme-Office-Supplies", "NWA")
    assert (f.number, f.amount, f.date) == ("INV-1042", 1250.00, "2026-11-13")


def test_own_invoice_is_receivable():
    text = "Northwind Advisory LLC\nINVOICE\nInvoice #: INV-2031\nBill To: Harbor Logistics Inc\n" \
           "Due Date: 2026-11-16\nTotal Due: $8,400.00"
    f = extract_fields(text, INVOICE, "ar@northwind-advisory.example", CFG)
    assert (f.direction, f.counterparty, f.amount) == (AR, "Harbor-Logistics", 8400.00)


def test_remittance_lists_paid_invoices():
    f = extract_fields(REMITTANCE_ADVICE, REMITTANCE, "payments@harbor-logistics.example", CFG)
    assert (f.direction, f.counterparty, f.number) == (AR, "Harbor-Logistics", "ACH-55102")
    assert f.amount == 12600.00 and f.date == "2026-10-20"
    assert f.invoices_paid == ["INV-2027", "INV-2031"]


def test_receipt_fields():
    f = extract_fields(RECEIPT_TEXT, RECEIPT, "receipts@clouddesk.example", CFG)
    assert (f.counterparty, f.number, f.amount, f.date) == ("CloudDesk-Software", "CD-40917",
                                                            149.00, "2026-10-21")


def test_parse_date_formats():
    for raw in ["10/15/2026", "2026-10-15", "Oct 15, 2026", "October 15 2026", "15-OCT-2026"]:
        assert parse_date(raw) == "2026-10-15", raw


def test_short_name():
    assert short_name("Acme Office Supplies, LLC") == "Acme-Office-Supplies"
    assert short_name("Summit Legal Partners LLP") == "Summit-Legal-Partners"


def test_link_allowlist_checks_the_real_host():
    trusted = ["invoices.acme-supplies.example"]
    assert is_trusted("https://invoices.acme-supplies.example/inv/1042.pdf", trusted)
    assert not is_trusted("http://invoices.acme-supplies.example/inv/1042.pdf", trusted)     # no https
    assert not is_trusted("https://evil.example/?x=invoices.acme-supplies.example", trusted)  # lookalike
    assert not is_trusted("https://invoices.acme-supplies.example.evil.example/x", trusted)
