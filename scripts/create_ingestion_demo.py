from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def make_pdf(path: Path, title: str, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    c.setFont("Helvetica-Bold", 16)
    c.drawString(56, height - 72, title)
    c.setFont("Helvetica", 10)
    y = height - 110
    for line in lines:
        c.drawString(56, y, line)
        y -= 18
    c.showPage()
    c.save()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a small legacy-export folder and continuous event queue for ingestion demos.")
    parser.add_argument("--root", type=Path, default=Path("data/ingestion_demo"))
    args = parser.parse_args()
    root = args.root
    legacy = root / "legacy_export"
    queue = root / "queue"
    legacy.mkdir(parents=True, exist_ok=True)
    queue.mkdir(parents=True, exist_ok=True)

    customers = [
        ("CUST-BULK001", "Beatrice Martel", "Guernsey", "High"),
        ("CUST-BULK002", "Orion Holdings Limited", "Jersey", "Medium"),
    ]
    manifest_rows = []
    for entity_id, name, jurisdiction, risk in customers:
        folder = legacy / entity_id
        make_pdf(folder / "salesforce" / "application_form.pdf", "Account Opening Application", [name, f"Entity: {entity_id}", "Application captured from Salesforce FSC."])
        make_pdf(folder / "aml" / "cdd_review.pdf", "Customer Due Diligence Review", [name, f"Risk rating: {risk}", "CDD review completed by compliance."])
        make_pdf(folder / "aml" / "source_of_wealth.pdf", "Source of Wealth Evidence", [name, "Declared source of wealth: property sale and investment income."])
        make_pdf(folder / "salesforce" / "proof_of_address.pdf", "Proof of Address", [name, "Utility bill confirms residential address."])
        (folder / "email").mkdir(parents=True, exist_ok=True)
        (folder / "email" / "follow_up.eml").write_text(
            f"Subject: CDD follow-up\nTo: {name}\n\nPlease provide supporting documentation for the CDD review.",
            encoding="utf-8",
        )
        for file in folder.rglob("*"):
            if not file.is_file():
                continue
            manifest_rows.append({
                "entity_id": entity_id,
                "display_name": name,
                "jurisdiction": jurisdiction,
                "risk_rating": risk,
                "file_path": str(file.relative_to(legacy)),
                "source_system": "AML Platform" if "aml" in file.parts else ("Email Archive" if file.suffix == ".eml" else "Salesforce FSC"),
            })
    manifest_path = legacy / "bulk_manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(manifest_rows[0].keys()))
        writer.writeheader()
        writer.writerows(manifest_rows)

    event_pdf = root / "continuous_payloads" / "CUST-BULK001_new_statement.pdf"
    make_pdf(event_pdf, "Monthly Statement", ["Customer: CUST-BULK001", "Statement generated after initial bulk ingestion."])
    event = {
        "event_id": "EVT-STATEMENT-0001",
        "entity_id": "CUST-BULK001",
        "display_name": "Beatrice Martel",
        "jurisdiction": "Guernsey",
        "risk_rating": "High",
        "file_path": str(event_pdf),
        "source_system": "Statement Engine",
        "category": "Statements",
        "document_type": "Monthly Statement",
        "retention_class": "Statements",
        "snapshot_id": "STATEMENT_EVENT_2026_04",
        "snapshot_type": "Continuous Statement Event",
    }
    (queue / "event_statement_0001.json").write_text(json.dumps(event, indent=2), encoding="utf-8")

    print(f"Created ingestion demo under {root}")
    print(f"Bulk input: {legacy}")
    print(f"Bulk manifest: {manifest_path}")
    print(f"Event queue: {queue}")


if __name__ == "__main__":
    main()
