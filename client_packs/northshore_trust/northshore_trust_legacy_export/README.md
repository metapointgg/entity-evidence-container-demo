# Northshore Trust Legacy Source Data Pack

Synthetic demonstration data for the Entity Evidence Container POC.

This pack simulates a new client providing source material for ingestion into the FITS-based entity evidence archive.

## Contents

- `legacy_customer_folders/` - one folder per customer/entity with mixed source documents.
- `bulk_manifest.csv` - explicit metadata manifest for bulk ingestion.
- `continuous_ingestion_queue/` - JSON events simulating ongoing updates from source systems.
- `incoming_payloads/` - payload files referenced by continuous ingestion events.

## Customers

This pack contains 12 entities including individual, corporate and trust records. It deliberately includes control exceptions:

- `NTC-0002` - High-risk Guernsey individual missing proof of address in the legacy bulk import. A later continuous event supplies a replacement proof of address.
- `NTC-0007` - Corporate customer missing beneficial owner evidence.
- `NTC-0012` - High-risk customer missing EDD approval.

## Suggested ingestion into the POC

From the POC repo root:

```bash
python scripts/bulk_ingest.py   --input /path/to/northshore_trust_legacy_export/legacy_customer_folders   --source data/source   --manifest /path/to/northshore_trust_legacy_export/bulk_manifest.csv

python scripts/build_containers.py --source data/source --output data/containers
python scripts/rebuild_index.py --containers data/containers --sqlite data/index/evidence_index.db
```

Then process ongoing events:

```bash
python scripts/process_ingestion_queue.py   --queue /path/to/northshore_trust_legacy_export/continuous_ingestion_queue   --source data/source
```

Rebuild affected containers or run the full rebuild for the demo.

## Test queries

- Show me customers who are high risk and do not have proof of address.
- Show me all onboarding documentation for high-risk clients in Guernsey.
- What is the customer's source of wealth?
- Show me corporate customers missing beneficial owner evidence.
- Show me records from the Screening Provider.

All content is synthetic and for demonstration only.
