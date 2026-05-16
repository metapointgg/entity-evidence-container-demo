from __future__ import annotations

import argparse
from pathlib import Path

from eec.rulesets import evaluate_completeness, export_completeness_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate customer evidence completeness against a configured ruleset.")
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--ruleset-id", default=None)
    parser.add_argument("--entity-id", default=None)
    parser.add_argument("--risk-rating", default=None)
    parser.add_argument("--jurisdiction", default=None)
    parser.add_argument("--missing-item", default=None)
    parser.add_argument("--export", type=Path, default=None)
    args = parser.parse_args()

    report = evaluate_completeness(
        args.sqlite,
        root=args.root,
        ruleset_id=args.ruleset_id,
        entity_id=args.entity_id,
        risk_rating=args.risk_rating,
        jurisdiction=args.jurisdiction,
        missing_item=args.missing_item,
    )
    print(report["summary"])
    for row in report["rows"][:50]:
        status = "PASS" if row["complete"] else "FAIL"
        missing = ", ".join(row["missing_evidence"]) or "-"
        print(f"{status} | {row['entity_id']} | {row['risk_rating']} | {row['jurisdiction']} | {row['profile']} | missing: {missing}")
    if args.export:
        out = export_completeness_report(report, args.export)
        print(f"Exported report to {out}")


if __name__ == "__main__":
    main()
