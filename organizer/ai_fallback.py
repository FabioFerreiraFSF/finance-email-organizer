"""
ai_fallback.py - OPTIONAL backup extraction with a LOCAL AI model (Ollama).

Runs offline: the model lives on your own machine and no document leaves it.
It is only called when the rule-based extraction (extract.py) could not find
the counterparty, the amount or the date. If Ollama is not installed or not
running, it returns nothing and the pipeline carries on.

Setup (optional):
    ollama pull qwen2.5:3b
    pip install ollama
    set USE_LOCAL_AI=1 in your .env file
"""

import os
from typing import Optional

from pydantic import BaseModel, Field

from .extract import parse_date

MODEL = os.environ.get("LOCAL_AI_MODEL", "qwen2.5:3b")
MAX_CHARS = 6000          # the key fields are near the top; less text = faster on a CPU


def enabled() -> bool:
    return os.environ.get("USE_LOCAL_AI", "0") == "1"


class _Answer(BaseModel):
    """Answer schema. The descriptions go into the JSON schema and guide the model."""
    is_bill: bool = Field(..., description="true for a document that asks for or proves a "
                          "payment (invoice, receipt, remittance advice). false for anything else "
                          "(payslip, bank statement, letter, report, newsletter).")
    counterparty: Optional[str] = Field(None, description="Short name of the company that "
                                        "ISSUED the document. Never the 'Bill To' company.")
    amount: Optional[float] = Field(None, description="Total amount as a number, e.g. 1456.60.")
    date: Optional[str] = Field(None, description="Due date (or payment date) as MM/DD/YYYY.")


_PROMPT = """You extract data from financial documents (invoices, receipts, remittance advices).

FIRST decide if the document is a bill. If it is not (payslip, statement, letter, report),
answer is_bill=false and leave the other fields null.

If it is, extract:
- counterparty: the company that ISSUED it (letterhead, 'From', 'Remit To'). The company
  under 'Bill To' or 'Customer' is the payer: IGNORE it.
- amount: 'Balance Due', 'Amount Due', 'Total', 'Amount Paid'.
- date: the due date for invoices, the payment date for receipts and remittances.

EXAMPLES:
TEXT: "Acme Office Supplies LLC ... INVOICE ... Bill To Northwind Advisory LLC ... Due Date:
11/14/2026 ... Balance Due $1,250.00"
ANSWER: {"is_bill": true, "counterparty": "Acme Office Supplies", "amount": 1250.00, "date": "11/14/2026"}

TEXT: "Northwind Advisory ... Payroll June 2026 ... Employee: Jane Doe ... Net Pay 3,100.00"
ANSWER: {"is_bill": false, "counterparty": null, "amount": null, "date": null}

NOW THE REAL DOCUMENT:

TEXT:
"""


def ask(text: str):
    """Returns (counterparty, amount, iso_date, is_bill). All None when the AI is off or unavailable."""
    if not enabled():
        return None, None, None, None
    try:
        from ollama import chat
        reply = chat(
            model=MODEL,
            messages=[{"role": "user", "content": _PROMPT + text[:MAX_CHARS]}],
            format=_Answer.model_json_schema(),     # structured output: valid JSON guaranteed
            options={"temperature": 0},             # deterministic extraction
        )
        answer = _Answer.model_validate_json(reply.message.content)
    except Exception as e:                          # missing package, server down, bad JSON...
        print(f"  AI: unavailable ({type(e).__name__}), continuing without it.")
        return None, None, None, None

    if not answer.is_bill:
        return None, None, None, False
    date = parse_date(answer.date) if answer.date else None
    return (answer.counterparty or None), answer.amount, date, True
