"""
mailbox.py - Where emails come from.

Two sources with the same interface, so the pipeline does not care which one runs:
  - GraphMailbox: a real Outlook / Microsoft 365 inbox, read-only (Microsoft Graph).
  - EmlFolder:    a folder of .eml files. Used by the demo and the tests,
                  so anyone can run the project without a corporate mailbox.

Only the Inbox is read. Junk email is skipped on purpose: it is where fake
invoices and malicious attachments usually land.
"""

import base64
import email
from dataclasses import dataclass, field
from email import policy
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterator

import requests

GRAPH = "https://graph.microsoft.com/v1.0"
TIMEOUT = 30


@dataclass
class Email:
    id: str
    received: str                       # ISO 8601, e.g. 2026-10-15T13:02:00Z
    sender: str
    subject: str
    body_html: str = ""
    attachments: list[tuple[str, bytes]] = field(default_factory=list)   # (file name, content)

    def pdf_attachments(self) -> list[tuple[str, bytes]]:
        return [(n, c) for n, c in self.attachments
                if n.lower().endswith(".pdf") or c[:5] == b"%PDF-"]


class GraphMailbox:
    """Reads the signed-in user's Inbox through Microsoft Graph (Mail.Read)."""

    def __init__(self, token: str):
        self._headers = {"Authorization": f"Bearer {token}"}

    def _get(self, url, params=None):
        resp = requests.get(url, headers=self._headers, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def emails(self, limit=50, since=None, until=None) -> Iterator[Email]:
        """Newest emails first. With since/until ("YYYY-MM-DD", UTC) it pages through the whole period."""
        params = {
            "$select": "id,subject,from,receivedDateTime,hasAttachments",
            "$orderby": "receivedDateTime desc",
            "$top": limit,
        }
        filters = []
        if since:
            filters.append(f"receivedDateTime ge {since}T00:00:00Z")
        if until:
            filters.append(f"receivedDateTime le {until}T23:59:59Z")
        if filters:
            params["$filter"] = " and ".join(filters)
            params["$top"] = 100

        data = self._get(f"{GRAPH}/me/mailFolders/inbox/messages", params)
        messages = list(data.get("value", []))
        next_link = data.get("@odata.nextLink")
        while filters and next_link:                 # next links already carry the filter
            data = self._get(next_link)
            messages += data.get("value", [])
            next_link = data.get("@odata.nextLink")

        for m in messages:
            yield Email(
                id=m["id"],
                received=m.get("receivedDateTime", ""),
                sender=m.get("from", {}).get("emailAddress", {}).get("address", ""),
                subject=m.get("subject") or "(no subject)",
                body_html=self._body(m["id"]),
                attachments=self._attachments(m["id"]) if m.get("hasAttachments") else [],
            )

    def _body(self, message_id):
        data = self._get(f"{GRAPH}/me/messages/{message_id}", {"$select": "body"})
        return data.get("body", {}).get("content", "")

    def _attachments(self, message_id):
        data = self._get(f"{GRAPH}/me/messages/{message_id}/attachments")
        files = []
        for a in data.get("value", []):
            if a.get("@odata.type") == "#microsoft.graph.fileAttachment":
                files.append((a.get("name", "attachment"), base64.b64decode(a["contentBytes"])))
        return files


class EmlFolder:
    """Reads .eml files from a folder (newest first). Same output as GraphMailbox."""

    def __init__(self, folder: str | Path):
        self.folder = Path(folder)

    def emails(self, limit=None, since=None, until=None) -> Iterator[Email]:
        items = []
        for path in sorted(self.folder.glob("*.eml")):
            msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
            received = parsedate_to_datetime(msg["Date"]).strftime("%Y-%m-%dT%H:%M:%SZ")
            day = received[:10]
            if (since and day < since) or (until and day > until):
                continue
            body = msg.get_body(preferencelist=("html", "plain"))
            attachments = [(part.get_filename() or "attachment", part.get_payload(decode=True))
                           for part in msg.iter_attachments()]
            items.append(Email(
                id=path.stem,
                received=received,
                sender=email.utils.parseaddr(msg["From"])[1],
                subject=msg["Subject"] or "(no subject)",
                body_html=body.get_content() if body else "",
                attachments=attachments,
            ))
        items.sort(key=lambda e: e.received, reverse=True)
        return iter(items[:limit] if limit else items)
