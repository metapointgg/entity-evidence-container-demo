from __future__ import annotations

import csv
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List

from .render_docs import write_pdf, write_scan_image, image_to_pdf
from .utils import deterministic_bytes, utc_now_iso, write_json

FIRST_NAMES = ["Eleanor", "James", "Amelia", "Oliver", "Sophie", "Thomas", "Charlotte", "Henry", "Isla", "George", "Grace", "Arthur", "Freya", "Oscar", "Emily", "William"]
LAST_NAMES = ["Hartley", "Le Page", "Ozanne", "Carey", "Falla", "Dorey", "Bichard", "Renouf", "Mauger", "Ferbrache", "Bisson", "Collins", "Hughes", "Baker", "Morgan", "Wilson"]
OCCUPATIONS = ["Company Director", "Retired Teacher", "Software Consultant", "Property Developer", "Investment Manager", "Marine Engineer", "Medical Consultant", "Retail Business Owner"]
JURISDICTIONS = ["Guernsey", "Jersey", "United Kingdom", "Isle of Man", "Gibraltar", "Malta"]
RISK_RATINGS = ["Low", "Medium", "Medium", "Medium", "High"]
SOW_TYPES = ["employment income", "property sale", "inheritance", "business dividend", "investment portfolio liquidation", "pension drawdown", "company sale proceeds"]
PRODUCTS = ["Easy access savings", "Fixed term deposit", "Current account", "Notice account", "Cash ISA", "Regular saver"]
COMPLAINT_THEMES = ["overdraft charge", "payment delay", "statement discrepancy", "account opening delay", "interest calculation query"]


def _customer_id(i: int) -> str:
    return f"CUST-{i:06d}"


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_binary_padding(path: Path, mb: int, seed: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if mb <= 0:
        return
    path.write_bytes(deterministic_bytes(mb * 1024 * 1024, seed))


def generate_customers(output: Path, customers: int, target_mb_per_customer: int = 2, seed: int = 42) -> List[Path]:
    random.seed(seed)
    output.mkdir(parents=True, exist_ok=True)
    created: List[Path] = []
    for i in range(1, customers + 1):
        cid = _customer_id(i)
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        name = f"{first} {last}"
        jurisdiction = random.choice(JURISDICTIONS)
        risk = random.choice(RISK_RATINGS)
        occupation = random.choice(OCCUPATIONS)
        sow = random.choice(SOW_TYPES)
        product_sample = random.sample(PRODUCTS, k=random.randint(2, 4))
        theme = random.choice(COMPLAINT_THEMES)
        base = output / cid
        base.mkdir(parents=True, exist_ok=True)
        created.append(base)

        customer = {
            "entity_id": cid,
            "entity_type": "Customer",
            "display_name": name,
            "jurisdiction": jurisdiction,
            "risk_rating": risk,
            "occupation": occupation,
            "products": product_sample,
            "created_at": utc_now_iso(),
            "source_systems": ["Salesforce FSC", "Core Banking", "Email Archive", "Statement Engine", "AML Screening Platform"],
        }
        write_json(base / "metadata" / "customer.json", customer)

        accounts = []
        for n, product in enumerate(product_sample, start=1):
            accounts.append({
                "account_id": f"ACC-{i:06d}-{n}",
                "product": product,
                "currency": "GBP",
                "opened_on": str(date(2024, random.randint(1, 12), random.randint(1, 28))),
                "status": "Open",
                "balance": round(random.uniform(2500, 250000), 2),
            })
        write_json(base / "metadata" / "accounts.json", accounts)

        app_text = write_pdf(
            base / "documents" / "account_opening_application.pdf",
            "Account Opening Application",
            f"Synthetic customer onboarding pack for {name} / {cid}",
            [
                ("Customer details", [
                    f"Customer ID: {cid}",
                    f"Name: {name}",
                    f"Jurisdiction: {jurisdiction}",
                    f"Occupation: {occupation}",
                    f"Risk rating: {risk}",
                ]),
                ("Products requested", [f"Product {idx}: {prod}" for idx, prod in enumerate(product_sample, 1)]),
                ("Declarations", [
                    "Customer has confirmed tax residency and source of wealth information.",
                    "Customer has accepted account terms and data processing notice.",
                    "Consent recorded for electronic communications and statement delivery.",
                ]),
            ],
        )
        _write_text(base / "documents" / "account_opening_application.search.txt", app_text)

        cdd_text = write_pdf(
            base / "documents" / "cdd_risk_review.pdf",
            "Customer Due Diligence Risk Review",
            f"CDD periodic review for {name} / {cid}",
            [
                ("Risk assessment", [
                    f"Risk rating: {risk}",
                    f"Source of wealth: {sow}",
                    "PEP screening: No match" if risk != "High" else "PEP screening: Potential close associate match reviewed and discounted",
                    "Sanctions screening: Clear",
                    "Adverse media: No material adverse media" if risk != "High" else "Adverse media: Historic media mention reviewed by compliance",
                ]),
                ("Compliance decision", [
                    "Decision: Continue relationship",
                    "Reviewer: Compliance Officer 2",
                    "Rationale: Documentation supports declared activity and expected account usage.",
                    "Enhanced due diligence applied where risk rating is High.",
                ]),
            ],
        )
        _write_text(base / "documents" / "cdd_risk_review.search.txt", cdd_text)

        utility_text = write_pdf(
            base / "documents" / "proof_of_address_utility_bill.pdf",
            "Island Utilities Statement",
            f"Proof of address evidence for {name}",
            [
                ("Billing details", [
                    f"Account holder: {name}",
                    f"Service address: {random.randint(1, 80)} Harbour Road, St Peter Port, {jurisdiction}",
                    "Bill date: 2026-04-02",
                    f"Amount due: £{random.randint(80, 420)}.00",
                ]),
                ("Preservation note", ["Synthetic utility bill generated for document preservation testing."]),
            ],
        )
        _write_text(base / "documents" / "proof_of_address_utility_bill.search.txt", utility_text)

        passport_scan_text = write_scan_image(
            base / "scans" / "passport_scan.jpg",
            "PASSPORT IDENTITY EVIDENCE",
            [
                f"Name: {name}",
                f"Customer reference: {cid}",
                f"Nationality: British Citizen",
                f"Document number: P{random.randint(100000000, 999999999)}",
                "Document expiry: 2031-09-30",
                "Certification: Seen and certified as a true likeness by relationship manager.",
            ],
        )
        image_to_pdf(base / "scans" / "passport_scan.jpg", base / "documents" / "passport_scan_certified.pdf", "Certified passport evidence scan")
        _write_text(base / "documents" / "passport_scan_certified.search.txt", passport_scan_text)

        sow_scan_text = write_scan_image(
            base / "scans" / "source_of_wealth_evidence.jpg",
            "SOURCE OF WEALTH EVIDENCE",
            [
                f"Customer: {name}",
                f"Source of wealth category: {sow}",
                "Evidence reviewed: bank statements, sale contract, accountant letter, tax computation.",
                "Compliance conclusion: evidence is consistent with declared net worth and expected activity.",
                "Additional monitoring: periodic review cycle retained due to transaction profile.",
            ],
        )
        image_to_pdf(base / "scans" / "source_of_wealth_evidence.jpg", base / "documents" / "source_of_wealth_scan.pdf", "Source of wealth scan")
        _write_text(base / "documents" / "source_of_wealth_scan.search.txt", sow_scan_text)

        # Statements
        start_month = date(2026, 1, 1)
        for m in range(1, 7):
            stmt_date = start_month.replace(month=m)
            opening = random.uniform(1000, 100000)
            closing = opening + random.uniform(-2500, 5000)
            lines = [
                f"Statement period: {stmt_date.isoformat()} to {(stmt_date + timedelta(days=27)).isoformat()}",
                f"Customer ID: {cid}",
                f"Customer name: {name}",
                f"Opening balance: £{opening:,.2f}",
                f"Closing balance: £{closing:,.2f}",
                f"Product references: {', '.join(product_sample)}",
                f"Narrative: Monthly statement includes standing orders, inbound salary, card settlement and fixed term deposit maturity information where applicable.",
            ]
            stmt_text = write_pdf(
                base / "statements" / f"statement_2026_{m:02d}.pdf",
                "Monthly Account Statement",
                f"Statement for {name} / {cid}",
                [("Statement summary", lines), ("Regulatory wording", ["Please retain this statement for your records.", "Contact support immediately if any transaction appears incorrect."])],
            )
            _write_text(base / "statements" / f"statement_2026_{m:02d}.search.txt", stmt_text)

        # Emails as .eml files
        email_templates = [
            ("Welcome to Banxlocal", "Your account opening journey is now complete. Please review your statement preferences and online access arrangements."),
            ("CDD follow-up", f"Please provide further source of wealth information relating to {sow}. This supports our enhanced due diligence review."),
            ("Complaint acknowledgement", f"We acknowledge your complaint regarding {theme}. We will investigate and respond within the required timeframe."),
            ("Fixed term deposit maturity", "Your fixed term deposit maturity date is approaching. Please select reinvestment, withdrawal or rollover instructions."),
            ("Periodic review request", "We are completing a periodic review of your customer due diligence profile and may require updated information."),
        ]
        for eidx, (subject, body) in enumerate(email_templates, start=1):
            eml = (
                f"From: support@example-bank.test\n"
                f"To: {first.lower()}.{last.lower().replace(' ', '')}@example.test\n"
                f"Subject: {subject}\n"
                f"Date: Tue, {10+eidx} Feb 2026 09:3{eidx}:00 +0000\n"
                f"Message-ID: <{cid}-{eidx}@example-bank.test>\n"
                "MIME-Version: 1.0\n"
                "Content-Type: text/plain; charset=utf-8\n\n"
                f"Dear {first},\n\n{body}\n\nCustomer reference: {cid}\n\nRegards,\nCustomer Operations\n"
            )
            _write_text(base / "emails" / f"email_{eidx:02d}_{subject.lower().replace(' ', '_')}.eml", eml)

        # Transaction CSV
        tx_path = base / "extracts" / "transactions_2026_q1.csv"
        tx_path.parent.mkdir(parents=True, exist_ok=True)
        with tx_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "account_id", "description", "amount", "balance", "channel"])
            balance = random.uniform(1000, 50000)
            for t in range(40):
                amount = round(random.uniform(-800, 2500), 2)
                balance += amount
                writer.writerow([
                    (date(2026, 1, 1) + timedelta(days=t * 2)).isoformat(),
                    accounts[0]["account_id"],
                    random.choice(["Salary credit", "Card settlement", "Standing order", "Interest credit", "Transfer to savings", "ATM withdrawal"]),
                    amount,
                    round(balance, 2),
                    random.choice(["Mobile", "Branch", "Online", "Operations"]),
                ])
        _write_text(base / "extracts" / "transactions_2026_q1.search.txt", f"Transaction extract customer {cid} {name} salary credit standing order interest transfer savings")

        # Audit/provenance sample
        audit_events = []
        for aidx, event in enumerate(["Customer created", "CDD documents received", "Sanctions screening completed", "Account approved", "Statement generated", "Periodic review scheduled"], start=1):
            audit_events.append({
                "event_id": f"AUD-{cid}-{aidx:03d}",
                "timestamp": (datetime(2026, 1, 1, 9, 0, 0) + timedelta(days=aidx)).isoformat() + "Z",
                "event_type": event,
                "actor": random.choice(["system", "relationship.manager", "compliance.officer"]),
                "source_system": random.choice(["Salesforce FSC", "Core Banking", "AML Screening Platform"]),
            })
        write_json(base / "metadata" / "audit_events.json", audit_events)
        _write_text(base / "metadata" / "audit_events.search.txt", json.dumps(audit_events))

        # Configurable large payloads. These are deliberately synthetic and deterministic.
        current_size = sum(p.stat().st_size for p in base.rglob("*") if p.is_file())
        target = max(0, target_mb_per_customer) * 1024 * 1024
        remaining = max(0, target - current_size)
        if remaining > 0:
            # Split into a few large blobs to show large object behaviour without generating expensive PDF pages.
            blobs = min(4, max(1, remaining // (1024 * 1024)))
            each = remaining // blobs
            for b in range(1, blobs + 1):
                size = each if b < blobs else remaining - each * (blobs - 1)
                path = base / "large_evidence" / f"bulk_archive_attachment_{b:02d}.bin"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(deterministic_bytes(size, f"{cid}-{b}-{seed}"))
                _write_text(path.with_suffix(".search.txt"), f"Synthetic large evidence payload for {cid} {name}. Bulk archive attachment {b}. Contains preserved binary evidence placeholder.")

    return created
