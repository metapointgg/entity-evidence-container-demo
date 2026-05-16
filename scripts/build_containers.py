from __future__ import annotations

import argparse
from pathlib import Path

from eec.container_builder import build_all_containers


def main() -> None:
    parser = argparse.ArgumentParser(description="Build FITS entity evidence containers")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--snapshot-model", action="store_true", help="Build multiple immutable snapshot containers per entity rather than one full container")
    args = parser.parse_args()
    outputs = build_all_containers(args.source, args.output, snapshot_model=args.snapshot_model)
    for out in outputs:
        print(out)
    print(f"Built {len(outputs)} container(s).")


if __name__ == "__main__":
    main()
