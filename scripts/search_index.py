import argparse
from pathlib import Path
from eec.search import search_index

parser = argparse.ArgumentParser(description="Search the rebuilt SQLite/FTS index")
parser.add_argument("--sqlite", type=Path, default=Path("data/index/evidence_index.db"))
parser.add_argument("--query", required=True)
parser.add_argument("--limit", type=int, default=20)
args = parser.parse_args()
rows = search_index(args.sqlite, args.query, args.limit)
print(f"Results: {len(rows)}")
for row in rows:
    print("-" * 90)
    print(f"{row['entity_id']} / {row['display_name']} / {row['document_type']} / {row['relative_path']}")
    print(f"Retention: {row['retention_class']} | Sensitivity: {row['sensitivity']} | Size: {row['size_bytes']} bytes")
    print(row.get("snippet") or "")
