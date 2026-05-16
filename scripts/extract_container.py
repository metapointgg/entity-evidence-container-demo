import argparse
from pathlib import Path
from eec.container_reader import extract_container

parser = argparse.ArgumentParser(description="Extract original evidence payloads from a FITS container")
parser.add_argument("--container", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
extracted = extract_container(args.container, args.output)
print(f"Extracted {len(extracted)} payloads to {args.output}")
