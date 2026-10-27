"""
links.py - Downloads invoices that arrive as LINKS in the email body
("View invoice", "Download PDF") instead of attachments.

Security rules:
  - HTTPS only.
  - The link's HOST must be on the allowlist (config.trusted_link_domains).
    We compare the real host name, not a substring of the URL, so a link like
    https://evil.example/?x=billing.vendor.com is rejected.
  - The response must really be a PDF (checked by its first bytes).
"""

import html
import re
from urllib.parse import urlparse

import requests

TIMEOUT = 30
_HREF = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)


def extract_links(body_html: str) -> list[str]:
    """All href URLs in the email body, without duplicates, in order."""
    seen, links = set(), []
    for url in (html.unescape(u) for u in _HREF.findall(body_html or "")):
        if url not in seen:
            seen.add(url)
            links.append(url)
    return links


def is_trusted(url: str, trusted_domains: list[str]) -> bool:
    """True if the URL is https and its host is a trusted domain (or a subdomain of one)."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in trusted_domains)


def download_pdf(url: str) -> bytes | None:
    """Downloads a trusted link. Returns the PDF bytes, or None if it is not a PDF."""
    resp = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    content = resp.content
    return content if content[:5] == b"%PDF-" else None


def pdfs_from_links(body_html: str, trusted_domains: list[str]) -> list[tuple[str, bytes]]:
    """Downloads every PDF linked from trusted domains. Returns (file name, content) pairs."""
    files = []
    for url in extract_links(body_html):
        if not is_trusted(url, trusted_domains):
            continue
        try:
            content = download_pdf(url)
        except requests.RequestException as e:
            print(f"  link skipped: {url[:60]} ({type(e).__name__})")
            continue
        if content:
            name = re.sub(r"\W+", "_", urlparse(url).path)[-50:].strip("_") or "linked"
            files.append((f"link_{name}.pdf", content))
    return files
