"""End-to-end test: runs the whole pipeline on the fake sample inbox."""

import csv
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run_demo(cwd):
    return subprocess.run([sys.executable, "-m", "organizer", "--demo"], cwd=cwd,
                          capture_output=True, text=True, check=True,
                          env={**os.environ, "PYTHONPATH": str(ROOT)}).stdout


def test_demo_files_everything_once(tmp_path):
    out = run_demo(tmp_path)
    assert "7 filed, 1 duplicates skipped, 0 errors" in out

    organized = tmp_path / "organized"
    names = sorted(p.relative_to(organized).as_posix() for p in organized.rglob("*.pdf"))
    assert names == [
        "AP/2026-10/2026-10-21_CloudDesk-Software(NWA)_Receipt-CD-40917_149.00.pdf",
        "AP/2026-11/2026-11-05_BlueWave-Telecom(NWC)_Invoice-BW-88213_389.40.pdf",
        "AP/2026-11/2026-11-13_Acme-Office-Supplies(NWA)_Invoice-INV-1042_1250.00.pdf",
        "AP/2026-12/2026-12-01_Summit-Legal-Partners(NWC)_Invoice-SLP-7781_2750.00.pdf",
        "AR/2026-10/2026-10-20_Harbor-Logistics(NWA)_Remittance-ACH-55102_12600.00.pdf",
        "AR/2026-11/2026-11-16_Harbor-Logistics(NWA)_Invoice-INV-2031_8400.00.pdf",
        "Other/2026-10/2026-10-22_Document.pdf",
    ]

    with (organized / "remittances.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["invoices_paid"] == "INV-2027 INV-2031"

    # Running again must not duplicate anything.
    assert "0 filed, 8 duplicates skipped" in run_demo(tmp_path)
