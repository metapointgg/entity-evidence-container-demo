from __future__ import annotations

import argparse
from pathlib import Path

from eec.ingestion import process_event_queue, write_ingestion_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Process continuous ingestion event JSON files from a queue folder.")
    parser.add_argument("--queue", required=True, type=Path, help="Folder containing event JSON files")
    parser.add_argument("--source", required=True, type=Path, help="Target source root, for example data/source")
    parser.add_argument("--processed", type=Path, help="Processed event folder")
    parser.add_argument("--failed", type=Path, help="Failed event folder")
    parser.add_argument("--no-overwrite", action="store_true")
    parser.add_argument("--report", type=Path, help="Optional output JSON report path")
    args = parser.parse_args()

    report = process_event_queue(
        args.queue,
        args.source,
        processed_dir=args.processed,
        failed_dir=args.failed,
        overwrite=not args.no_overwrite,
    )
    report_path = args.report or (args.source.parent / "ingestion" / "reports" / f"{report.run_id}.json")
    write_ingestion_report(report, report_path)

    print(f"Continuous ingestion queue run: {report.run_id}")
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
