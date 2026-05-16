import argparse
import subprocess
import sys
from pathlib import Path

parser = argparse.ArgumentParser(description="Run full entity evidence container demo")
parser.add_argument("--customers", type=int, default=3)
parser.add_argument("--target-mb-per-customer", type=int, default=2)
parser.add_argument("--seed", type=int, default=42)
args = parser.parse_args()

cmds = [
    [sys.executable, "scripts/generate_sample_data.py", "--customers", str(args.customers), "--output", "data/source", "--target-mb-per-customer", str(args.target_mb_per_customer), "--seed", str(args.seed)],
    [sys.executable, "scripts/build_containers.py", "--source", "data/source", "--output", "data/containers"],
    [sys.executable, "scripts/rebuild_index.py", "--containers", "data/containers", "--sqlite", "data/index/evidence_index.db"],
    [sys.executable, "scripts/inspect_container.py", "--container", "data/containers/CUST-000001.fits"],
    [sys.executable, "scripts/validate_container.py", "--container", "data/containers/CUST-000001.fits"],
    [sys.executable, "scripts/search_index.py", "--sqlite", "data/index/evidence_index.db", "--query", "source of wealth enhanced due diligence"],
    [sys.executable, "scripts/export_evidence_pack.py", "--container", "data/containers/CUST-000001.fits", "--output", "data/evidence_packs/CUST-000001"],
    [sys.executable, "scripts/corrupt_container.py", "--container", "data/containers/CUST-000001.fits", "--output", "data/containers/CUST-000001-corrupt.fits", "--object-index", "3"],
]
for cmd in cmds:
    print("\n> " + " ".join(cmd))
    subprocess.run(cmd, check=True)

print("\n> Validating corrupted copy; failure is expected")
result = subprocess.run([sys.executable, "scripts/validate_container.py", "--container", "data/containers/CUST-000001-corrupt.fits"], check=False)
if result.returncode == 2:
    print("Corruption detection demo succeeded: validator failed on corrupted copy as expected.")
else:
    raise SystemExit("Expected corrupted validation to fail")
