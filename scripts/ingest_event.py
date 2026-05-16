from __future__ import annotations

import argparse
import json
from pathlib import Path

from eec.ingestion import ingest_event, write_ingestion_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest one continuous update event JSON file.")
    parser.add_argument("--event", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--no-overwrite", action="store_true")
    args = parser.parse_args()

    event = json.loads(args.event.read_text(encoding="utf-8"))
    report = ingest_event(event, source_root=args.source, overwrite=not args.no_overwrite)
    report_path = args.report or (args.source.parent / "ingestion" / "reports" / f"{report.run_id}.json")
    write_ingestion_report(report, report_path)
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
