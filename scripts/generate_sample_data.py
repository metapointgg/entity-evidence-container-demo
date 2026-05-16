import argparse
from pathlib import Path
from eec.demo_data import generate_customers

parser = argparse.ArgumentParser(description="Generate rich synthetic financial-services customer evidence")
parser.add_argument("--customers", type=int, default=3)
parser.add_argument("--output", type=Path, default=Path("data/source"))
parser.add_argument("--target-mb-per-customer", type=int, default=2)
parser.add_argument("--seed", type=int, default=42)
args = parser.parse_args()

created = generate_customers(args.output, args.customers, args.target_mb_per_customer, args.seed)
print(f"Generated {len(created)} customers in {args.output}")
