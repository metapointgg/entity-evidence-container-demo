from __future__ import annotations

import argparse
from pathlib import Path

from eec.vector_search import vector_search


def main() -> None:
    parser = argparse.ArgumentParser(description="Search the local offline vector index")
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    rows = vector_search(args.index, args.query, args.limit)
    if not rows:
        print("No vector results. Rebuild the vector index with scripts\build_vector_index.py and confirm the SQLite index contains objects.")
        return
    for row in rows:
        print(f"{row.get('vector_score', 0):.3f} {row['entity_id']} {row['filename']} {row.get('document_type')}")


if __name__ == "__main__":
    main()
