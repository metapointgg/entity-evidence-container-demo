import argparse
from pathlib import Path
from eec.demo_data import generate_customers, generate_high_risk_missing_proof_of_address_customer

parser = argparse.ArgumentParser(description="Generate rich synthetic financial-services customer evidence")
parser.add_argument("--customers", type=int, default=3)
parser.add_argument("--output", type=Path, default=Path("data/source"))
parser.add_argument("--target-mb-per-customer", type=int, default=2)
parser.add_argument("--seed", type=int, default=42)
parser.add_argument("--include-edge-cases", action="store_true", help="Add deterministic edge-case customers for demo testing")
args = parser.parse_args()

created = generate_customers(args.output, args.customers, args.target_mb_per_customer, args.seed)
if args.include_edge_cases:
    created.append(generate_high_risk_missing_proof_of_address_customer(args.output, args.target_mb_per_customer, args.seed + 999))
print(f"Generated {len(created)} customers in {args.output}")
