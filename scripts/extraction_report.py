from __future__ import annotations

import argparse
import json
from pathlib import Path

from eec.extraction_report import extraction_dashboard, extraction_report_for_container

parser = argparse.ArgumentParser(description="Inspect OCR and structured extraction results.")
parser.add_argument("--sqlite", type=Path, help="SQLite evidence index path")
parser.add_argument("--container", type=Path, help="FITS container path")
args = parser.parse_args()

if args.container:
    print(json.dumps(extraction_report_for_container(args.container), indent=2, ensure_ascii=False))
elif args.sqlite:
    print(json.dumps(extraction_dashboard(args.sqlite), indent=2, ensure_ascii=False))
else:
    parser.error("Provide --sqlite or --container")
