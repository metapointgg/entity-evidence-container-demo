from __future__ import annotations

import argparse
from pathlib import Path

from eec.vector_search import build_vector_index


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a local offline vector index from the SQLite evidence index")
    parser.add_argument("--sqlite", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    count = build_vector_index(args.sqlite, args.output)
    print(f"Built vector index with {count} objects: {args.output}")


if __name__ == "__main__":
    main()
