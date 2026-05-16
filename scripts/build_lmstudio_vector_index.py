from __future__ import annotations

import argparse
from pathlib import Path

from eec.lmstudio_vector_search import build_lmstudio_vector_index

parser = argparse.ArgumentParser(description="Build an LM Studio embedding vector index from the SQLite evidence index.")
parser.add_argument("--sqlite", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--batch-size", type=int, default=32)
parser.add_argument("--model", default=None)
args = parser.parse_args()

count = build_lmstudio_vector_index(args.sqlite, args.output, batch_size=args.batch_size, model=args.model)
print(f"LM Studio vector indexed {count} objects into {args.output}")
