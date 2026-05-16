from __future__ import annotations

import argparse
from pathlib import Path

from eec.container_builder import build_all_containers


def main() -> None:
    parser = argparse.ArgumentParser(description="Build FITS entity evidence containers")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--split-snapshots",
        action="store_true",
        help="Legacy mode: build multiple snapshot FITS files per entity. Default is one active FITS file per entity with internal snapshots.",
    )
    parser.add_argument(
        "--snapshot-model",
        action="store_true",
        help="Deprecated alias for --split-snapshots.",
    )
    args = parser.parse_args()
    outputs = build_all_containers(args.source, args.output, split_snapshots=args.split_snapshots or args.snapshot_model)
    for out in outputs:
        print(out)
    model = "split snapshot containers" if args.split_snapshots or args.snapshot_model else "single entity containers"
    print(f"Built {len(outputs)} {model}.")


if __name__ == "__main__":
    main()
