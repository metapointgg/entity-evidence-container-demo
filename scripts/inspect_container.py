import argparse
from pathlib import Path
from eec.container_reader import inspect_container
from eec.cli_common import print_json

parser = argparse.ArgumentParser(description="Inspect a FITS evidence container")
parser.add_argument("--container", type=Path, required=True)
args = parser.parse_args()
print_json(inspect_container(args.container))
