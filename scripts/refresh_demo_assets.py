from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from eec.container_builder import build_all_containers
from eec.demo_data import generate_customers, generate_high_risk_missing_proof_of_address_customer
from eec.indexer import rebuild_index
from eec.vector_search import build_vector_index
from eec.lmstudio_vector_search import build_lmstudio_vector_index


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh demo assets: optional sample-data generation, single-entity FITS containers, SQLite index and vector index."
    )
    parser.add_argument("--root", type=Path, default=Path("samples"), help="Demo root folder containing source/containers/index")
    parser.add_argument("--regenerate", action="store_true", help="Regenerate synthetic source data before rebuilding containers and indexes")
    parser.add_argument("--customers", type=int, default=3, help="Customer count when --regenerate is used")
    parser.add_argument("--target-mb-per-customer", type=int, default=2, help="Approximate source size per customer when --regenerate is used")
    parser.add_argument("--seed", type=int, default=42, help="Synthetic data seed when --regenerate is used")
    parser.add_argument("--split-snapshots", action="store_true", help="Legacy mode: build multiple immutable snapshot containers instead of one active FITS file per entity")
    parser.add_argument("--clean", action="store_true", help="Remove existing containers and indexes before rebuilding")
    parser.add_argument("--lmstudio-vector", action="store_true", help="Also build the LM Studio embedding vector index using the local /v1/embeddings endpoint")
    parser.add_argument("--include-edge-cases", action="store_true", help="Add deterministic edge-case customers for demo testing when --regenerate is used")
    args = parser.parse_args()

    root = args.root
    source = root / "source"
    containers = root / "containers"
    index_dir = root / "index"
    sqlite_path = index_dir / "evidence_index.db"
    vector_path = index_dir / "evidence_vector.pkl"
    lmstudio_vector_path = index_dir / "evidence_lmstudio_vector.pkl"

    root.mkdir(parents=True, exist_ok=True)
    if args.clean:
        if containers.exists():
            shutil.rmtree(containers)
        if index_dir.exists():
            shutil.rmtree(index_dir)

    if args.regenerate:
        if args.clean and source.exists():
            shutil.rmtree(source)
        created = generate_customers(source, args.customers, args.target_mb_per_customer, args.seed)
        if args.include_edge_cases:
            created.append(generate_high_risk_missing_proof_of_address_customer(source, args.target_mb_per_customer, args.seed + 999))
        print(f"Generated {len(created)} customers in {source}")

    if not source.exists():
        raise SystemExit(f"Source folder not found: {source}. Run with --regenerate or generate sample data first.")

    containers.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)

    built = build_all_containers(source, containers, split_snapshots=args.split_snapshots)
    print(f"Built {len(built)} FITS container(s) in {containers}")
    for item in built[:12]:
        print(f"  {item}")
    if len(built) > 12:
        print(f"  ... {len(built) - 12} more")

    object_count = rebuild_index(containers, sqlite_path)
    print(f"Rebuilt SQLite index with {object_count} objects: {sqlite_path}")

    vector_count = build_vector_index(sqlite_path, vector_path)
    print(f"Rebuilt local vector index with {vector_count} objects: {vector_path}")

    if args.lmstudio_vector:
        lmstudio_count = build_lmstudio_vector_index(sqlite_path, lmstudio_vector_path)
        print(f"Rebuilt LM Studio embedding vector index with {lmstudio_count} objects: {lmstudio_vector_path}")

    print("\nSmoke-test commands:")
    print(f"python scripts\\search_index.py --sqlite {sqlite_path} --query \"source of wealth\" --limit 3")
    print(f"python scripts\\search_vector_index.py --index {vector_path} --query \"where did the customer money come from\" --limit 3")
    if built:
        print(f"python scripts\\validate_container.py --container {built[0]}")


if __name__ == "__main__":
    main()
