from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

from eec.container_builder import build_container
from eec.indexer import rebuild_index
from eec.utils import read_json


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild one active FITS container for a single entity after ingestion/update."
    )
    parser.add_argument("--entity-id", required=True, help="Entity/customer ID to rebuild, e.g. CUST-000001")
    parser.add_argument("--source", required=True, type=Path, help="Source root containing one folder per entity")
    parser.add_argument("--output", required=True, type=Path, help="Container output root")
    parser.add_argument("--retain-version", action="store_true", help="Copy the existing active container into _versions before replacing it")
    parser.add_argument("--rebuild-index", action="store_true", help="Rebuild the SQLite index after rebuilding the entity container")
    parser.add_argument("--sqlite", type=Path, default=None, help="SQLite index path when --rebuild-index is used")
    args = parser.parse_args()

    entity_dir = args.source / args.entity_id
    if not entity_dir.exists():
        # Fallback: locate by metadata entity_id in case folder naming differs.
        for candidate in sorted(p for p in args.source.iterdir() if p.is_dir()):
            metadata = candidate / "metadata" / "customer.json"
            if metadata.exists() and read_json(metadata).get("entity_id") == args.entity_id:
                entity_dir = candidate
                break

    metadata = entity_dir / "metadata" / "customer.json"
    if not metadata.exists():
        raise SystemExit(f"Could not find source metadata for entity {args.entity_id} under {args.source}")

    entity = read_json(metadata)
    entity_id = entity["entity_id"]
    args.output.mkdir(parents=True, exist_ok=True)
    active = args.output / f"{entity_id}.fits"

    if args.retain_version and active.exists():
        version_dir = args.output / "_versions" / entity_id
        version_dir.mkdir(parents=True, exist_ok=True)
        versioned = version_dir / f"{entity_id}__{_timestamp()}.fits"
        shutil.copy2(active, versioned)
        print(f"Retained previous version: {versioned}")

    built = build_container(entity_dir, active, snapshot_id="ENTITY_ARCHIVE", snapshot_type="Full Entity Archive")
    print(f"Rebuilt active entity container: {built}")

    if args.rebuild_index:
        if args.sqlite is None:
            raise SystemExit("--sqlite is required when --rebuild-index is used")
        count = rebuild_index(args.output, args.sqlite)
        print(f"Rebuilt SQLite index with {count} objects: {args.sqlite}")


if __name__ == "__main__":
    main()
