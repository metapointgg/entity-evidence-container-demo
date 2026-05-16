import argparse
from pathlib import Path
from eec.container_builder import build_all_containers

parser = argparse.ArgumentParser(description="Build FITS evidence containers from generated source folders")
parser.add_argument("--source", type=Path, default=Path("data/source"))
parser.add_argument("--output", type=Path, default=Path("data/containers"))
args = parser.parse_args()

outputs = build_all_containers(args.source, args.output)
for out in outputs:
    print(out)
print(f"Built {len(outputs)} containers")
