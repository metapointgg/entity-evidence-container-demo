from __future__ import annotations

import argparse
from pathlib import Path

from eec.ingestion import bulk_ingest, write_ingestion_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk ingest historical customer evidence into the source archive structure.")
    parser.add_argument("--input", required=True, type=Path, help="Input folder containing legacy/customer folders or files")
    parser.add_argument("--source", required=True, type=Path, help="Target source root, for example data/source")
    parser.add_argument("--manifest", type=Path, help="Optional CSV/JSON manifest mapping files to customer/evidence metadata")
    parser.add_argument("--default-jurisdiction", default="Guernsey")
    parser.add_argument("--default-risk-rating", default="Medium")
    parser.add_argument("--default-entity-type", default="Individual")
    parser.add_argument("--default-source-system", default="")
    parser.add_argument("--no-overwrite", action="store_true")
    parser.add_argument("--report", type=Path, help="Optional output JSON report path")
    args = parser.parse_args()

    defaults = {
        "jurisdiction": args.default_jurisdiction,
        "risk_rating": args.default_risk_rating,
        "entity_type": args.default_entity_type,
    }
    if args.default_source_system:
        defaults["source_system"] = args.default_source_system

    report = bulk_ingest(
        args.input,
        args.source,
        manifest=args.manifest,
        defaults=defaults,
        overwrite=not args.no_overwrite,
    )
    report_path = args.report or (args.source.parent / "ingestion" / "reports" / f"{report.run_id}.json")
    write_ingestion_report(report, report_path)

    print(f"Bulk ingestion run: {report.run_id}")
    print(f"Total: {report.total_items}")
    print(f"Ingested: {report.ingested_items}")
    print(f"Skipped: {report.skipped_items}")
    print(f"Failed: {report.failed_items}")
    print(f"Report: {report_path}")
    if report.failed_items:
        print("\nFailures:")
        for item in report.items:
            if item.get("status") == "failed":
                print(f"- {item.get('message')}")


if __name__ == "__main__":
    main()
