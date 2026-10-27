"""
make_samples.py - Builds the FAKE sample inbox used by the demo and the tests.

Every company, person, tax ID and amount here is fictional. The .eml files land
in samples/inbox/ and can be opened in any email app.

    pip install reportlab
    python scripts/make_samples.py
"""

import io
from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime, timezone
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parent.parent / "samples" / "inbox"


def pdf(lines: list[str], password: str | None = None) -> bytes:
    """A simple one-page PDF; the first line is the letterhead."""
    buffer = io.BytesIO()
    enc = StandardEncryption(password, canPrint=1) if password else None
    c = canvas.Canvas(buffer, pagesize=letter, encrypt=enc)
    y = 740
    for i, line in enumerate(lines):
        c.setFont("Helvetica-Bold" if i == 0 else "Helvetica", 16 if i == 0 else 11)
        c.drawString(60, y, line)
        y -= 26 if i == 0 else 18
    c.save()
    return buffer.getvalue()


def eml(name, when, sender, subject, body, attachments=()):
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "finance@northwind-advisory.example"
    msg["Subject"] = subject
    msg["Date"] = format_datetime(datetime(*when, tzinfo=timezone.utc))
    msg.set_content(body)
    msg.add_alternative(f"<html><body><p>{body}</p></body></html>", subtype="html")
    for file_name, content in attachments:
        msg.add_attachment(content, maintype="application", subtype="pdf", filename=file_name)
    (OUT / f"{name}.eml").write_bytes(bytes(msg))


ACME_INVOICE = pdf([
    "Acme Office Supplies LLC",
    "410 Market Street, Denver, CO 80202",
    "INVOICE",
    "Invoice Number: INV-1042",
    "Invoice Date: Oct 14, 2026",
    "Due Date: Nov 13, 2026",
    "Bill To: Northwind Advisory LLC (EIN 12-3456789)",
    "Printer paper, toner and desk chairs ........ $1,250.00",
    "Payment terms: Net 30",
    "Balance Due: $1,250.00",
])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.eml"):
        old.unlink()

    eml("01_acme_invoice", (2026, 10, 14, 13, 5), "billing@acme-supplies.example",
        "Invoice INV-1042 from Acme Office Supplies",
        'Hello, your invoice is attached. You can also <a href="https://invoices.acme-supplies.'
        'example/inv/1042.pdf">view it online</a>.',
        [("INV-1042.pdf", ACME_INVOICE)])

    eml("02_bluewave_protected", (2026, 10, 15, 9, 30), "noreply@billing-platform.example",
        "Your BlueWave Telecom invoice is ready",
        "Your monthly statement is attached. The PDF is protected with your account password.",
        [("statement.pdf", pdf([
            "BlueWave Telecom Inc",
            "INVOICE",
            "Invoice Number: BW-88213",
            "Bill To: Northwind Capital LLC (EIN 98-7654321)",
            "Service period: 09/15/2026 - 10/14/2026",
            "Due Date: 11/05/2026",
            "Amount Due: $389.40",
        ], password="demo1234"))])

    eml("03_acme_reminder", (2026, 10, 16, 8, 0), "billing@acme-supplies.example",
        "Reminder: Invoice INV-1042 is due soon",
        "Friendly reminder, the invoice is attached again.",
        [("INV-1042.pdf", ACME_INVOICE)])

    eml("04_northwind_ar_invoice", (2026, 10, 17, 16, 45), "ar@northwind-advisory.example",
        "Invoice INV-2031 sent to Harbor Logistics",
        "Copy of the invoice we sent to Harbor Logistics.",
        [("INV-2031.pdf", pdf([
            "Northwind Advisory LLC",
            "INVOICE",
            "Invoice #: INV-2031",
            "Invoice Date: 2026-10-17",
            "Bill To: Harbor Logistics Inc",
            "Monthly financial reporting package - October .... $8,400.00",
            "Due Date: 2026-11-16",
            "Total Due: $8,400.00",
        ]))])

    eml("05_harbor_remittance", (2026, 10, 20, 14, 10), "payments@harbor-logistics.example",
        "Remittance advice - ACH payment ACH-55102",
        "Please find our remittance advice attached.",
        [("remittance_ACH-55102.pdf", pdf([
            "Harbor Logistics Inc",
            "REMITTANCE ADVICE",
            "Paid by: Harbor Logistics Inc",
            "Paid to: Northwind Advisory LLC",
            "Payment Reference: ACH-55102",
            "Payment Date: October 20, 2026",
            "Payment method: ACH",
            "Invoice INV-2027 ................ $4,200.00",
            "Invoice INV-2031 ................ $8,400.00",
            "Total Payment: $12,600.00",
        ]))])

    eml("06_clouddesk_receipt", (2026, 10, 21, 7, 55), "receipts@clouddesk.example",
        "Your CloudDesk receipt #CD-40917",
        "Thanks for your payment! Your receipt is attached.",
        [("receipt.pdf", pdf([
            "CloudDesk Software Inc",
            "RECEIPT",
            "Receipt Number: CD-40917",
            "Billed to: Northwind Advisory LLC",
            "Date paid: Oct 21, 2026",
            "Team plan - 10 seats, monthly ....... $149.00",
            "Visa card ending 4242",
            "Amount paid: $149.00",
        ]))])

    eml("07_travel_policy", (2026, 10, 22, 11, 0), "hr@northwind-advisory.example",
        "Updated travel policy",
        "Hi all, the updated travel policy is attached.",
        [("travel_policy.pdf", pdf([
            "Northwind Advisory Group",
            "Travel and Expense Policy - version 3",
            "1. Book flights at least 14 days in advance.",
            "2. Hotels up to the city limit listed in Appendix A.",
            "3. Submit expenses within 30 days.",
        ]))])

    eml("08_forwarded_legal_invoice", (2026, 10, 23, 10, 20), "ap-forward@northwind-advisory.example",
        "FW: Summit Legal - October services",
        "Forwarding the invoice below for payment.",
        [("Summit_October.pdf", pdf([
            "Summit Legal Partners LLP",
            "INVOICE",
            "Invoice No. SLP-7781",
            "Bill To: Northwind Capital LLC",
            "Contract review - October 2026 ........ $2,750.00",
            "Due date: 12/01/2026",
            "Amount Due: $2,750.00",
        ]))])

    print(f"Sample inbox written to {OUT}")


if __name__ == "__main__":
    main()
