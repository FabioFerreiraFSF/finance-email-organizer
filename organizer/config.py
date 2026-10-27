"""
config.py - Loads settings from config.json and environment variables.

Business data (company names, tax IDs, vendor aliases) lives in config.json,
which is NOT versioned. Secrets (API IDs, PDF passwords) live in .env.
Copy config.example.json and .env.example to get started.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv is optional
    pass


@dataclass
class Entity:
    """One company of the group (the side that receives invoices or issues them)."""
    code: str
    name: str
    tax_id: str = ""


@dataclass
class Config:
    company_name: str = "My Company"
    entities: list[Entity] = field(default_factory=list)
    own_domains: list[str] = field(default_factory=list)
    vendor_aliases: dict[str, str] = field(default_factory=dict)    # sender domain -> name
    content_aliases: dict[str, str] = field(default_factory=dict)   # text in PDF -> name
    platform_domains: list[str] = field(default_factory=list)       # billing platforms, not vendors
    trusted_link_domains: list[str] = field(default_factory=list)
    attachments_only_senders: list[str] = field(default_factory=list)
    output_dir: str = "organized"
    download_dir: str = "downloads"

    @property
    def pdf_passwords(self) -> list[str]:
        raw = os.environ.get("PDF_PASSWORDS", "")
        return [p.strip() for p in raw.split(",") if p.strip()]


def load_config(path: str | Path = "config.json") -> Config:
    """Reads config.json. Falls back to config.example.json so the demo runs out of the box."""
    path = Path(path)
    if not path.exists():
        path = Path(__file__).resolve().parent.parent / "config.example.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    company = data.get("company", {})
    return Config(
        company_name=company.get("name", "My Company"),
        entities=[Entity(**e) for e in company.get("entities", [])],
        own_domains=[d.lower() for d in data.get("own_domains", [])],
        vendor_aliases={k.lower(): v for k, v in data.get("vendor_aliases", {}).items()},
        content_aliases={k.lower(): v for k, v in data.get("content_aliases", {}).items()},
        platform_domains=[d.lower() for d in data.get("platform_domains", [])],
        trusted_link_domains=[d.lower() for d in data.get("trusted_link_domains", [])],
        attachments_only_senders=[s.lower() for s in data.get("attachments_only_senders", [])],
        output_dir=data.get("output_dir", "organized"),
        download_dir=data.get("download_dir", "downloads"),
    )
