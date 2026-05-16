from __future__ import annotations

import argparse
from pathlib import Path

from eec.query_interpreter import execute_structured_query, interpret_archive_query


def main() -> None:
    parser = argparse.ArgumentParser(description="Test the natural-language structured archive search interpreter.")
    parser.add_argument("--sqlite", type=Path, default=Path("samples/index/evidence_index.db"))
    parser.add_argument("--query", default="Show me the CDD for customers in Guernsey who are high risk")
    parser.add_argument("--entity-id", default=None)
    parser.add_argument("--no-ai", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    structured = interpret_archive_query(
        args.query,
        selected_entity_id=args.entity_id,
        use_local_ai=not args.no_ai,
        limit=args.limit,
    )
    print("Interpreted query:")
    for key, value in structured.to_dict().items():
        print(f"  {key}: {value}")

    result = execute_structured_query(args.sqlite, structured)
    print()
    print(f"Result type: {result['type']}")
    print(f"Rows: {len(result['rows'])}")
    for row in result["rows"][: args.limit]:
        print(
            " | ".join(
                str(row.get(k, ""))
                for k in ["entity_id", "display_name", "risk_rating", "jurisdiction", "category", "document_type", "filename"]
            )
        )


if __name__ == "__main__":
    main()
