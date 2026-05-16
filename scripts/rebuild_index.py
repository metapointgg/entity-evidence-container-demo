import argparse
from pathlib import Path
from eec.indexer import rebuild_index

parser = argparse.ArgumentParser(description="Rebuild SQLite/FTS index from FITS containers")
parser.add_argument("--containers", type=Path, default=Path("data/containers"))
parser.add_argument("--sqlite", type=Path, default=Path("data/index/evidence_index.db"))
args = parser.parse_args()
count = rebuild_index(args.containers, args.sqlite)
print(f"Indexed {count} objects into {args.sqlite}")
