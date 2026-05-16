import argparse
from pathlib import Path
from eec.container_reader import validate_container
from eec.cli_common import print_json

parser = argparse.ArgumentParser(description="Validate payload hashes in a FITS evidence container")
parser.add_argument("--container", type=Path, required=True)
args = parser.parse_args()
result = validate_container(args.container)
print_json(result.to_dict())
raise SystemExit(0 if result.status == "PASS" else 2)
