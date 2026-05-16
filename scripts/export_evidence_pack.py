import argparse
from pathlib import Path
from eec.exporter import export_evidence_pack

parser = argparse.ArgumentParser(description="Export a regulator/compliance evidence pack from a container")
parser.add_argument("--container", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
out = export_evidence_pack(args.container, args.output)
print(f"Exported evidence pack to {out}")
