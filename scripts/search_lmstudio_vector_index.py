from __future__ import annotations

import argparse
from pathlib import Path

from eec.lmstudio_vector_search import lmstudio_vector_search

parser = argparse.ArgumentParser(description="Search an LM Studio embedding vector index.")
parser.add_argument("--index", type=Path, required=True)
parser.add_argument("--query", required=True)
parser.add_argument("--limit", type=int, default=10)
parser.add_argument("--model", default=None)
args = parser.parse_args()

rows = lmstudio_vector_search(args.index, args.query, args.limit, model=args.model)
for row in rows:
    print(f"{row.get('lmstudio_vector_score', 0):.3f} | {row.get('entity_id')} | {row.get('document_type')} | {row.get('filename')}")
