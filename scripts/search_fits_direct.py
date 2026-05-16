from __future__ import annotations

import argparse
from pathlib import Path

from eec.fits_direct_search import direct_search_container, direct_search_entity


def main() -> None:
    parser = argparse.ArgumentParser(description="Search FITS evidence containers directly without SQLite.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--container", type=Path, help="Specific FITS container to search")
    group.add_argument("--entity-id", help="Entity/customer ID to search within --containers")
    parser.add_argument("--containers", type=Path, default=Path("samples/containers"), help="Container folder used with --entity-id")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    if args.container:
        rows = direct_search_container(args.container, args.query, limit=args.limit)
    else:
        rows = direct_search_entity(args.containers, args.entity_id, args.query, limit=args.limit)

    for row in rows:
        print(
            f"{row.get('direct_fits_score', 0):.3f} | "
            f"{row.get('entity_id')} | {row.get('snapshot_id')} | "
            f"{row.get('document_type')} | {row.get('filename')}"
        )
        snippet = row.get("snippet") or ""
        if snippet:
            print(f"  {snippet[:220]}")


if __name__ == "__main__":
    main()
