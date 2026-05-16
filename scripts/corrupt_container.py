import argparse
from pathlib import Path
from eec.corruption import corrupt_container_payload

parser = argparse.ArgumentParser(description="Create a corrupted copy of a FITS container for validation demo")
parser.add_argument("--container", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--object-index", type=int, default=1)
args = parser.parse_args()
out = corrupt_container_payload(args.container, args.output, args.object_index)
print(f"Wrote corrupted copy: {out}")
