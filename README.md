# Entity Evidence Container Demo

A Python proof of concept for **entity-centric preservation containers** using FITS as a self-describing, integrity-protected archive format.

The demo packages all evidence for a financial-services customer into a portable container that can be inspected, validated, searched, extracted, corrupted for testing, and used to rebuild a search index without relying on the original application database.

## What this demonstrates

- Generate rich synthetic financial-services customer evidence.
- Package each customer into a FITS-based preservation container.
- Preserve original file bytes and searchable text sidecars.
- Maintain a manifest, provenance events, retention classes and SHA-256 fixity metadata.
- Rebuild a SQLite/FTS search index from the containers.
- Search across customers, document metadata and extracted text.
- Detect corruption at individual payload level.
- Export a regulator/compliance evidence pack.
- Generate as many customers as required, with configurable file sizes.

## Repository structure

```text
entity-evidence-container-demo/
├── pyproject.toml
├── requirements.txt
├── README.md
├── .gitignore
├── scripts/
│   ├── demo_run.py
│   ├── generate_sample_data.py
│   ├── build_containers.py
│   ├── inspect_container.py
│   ├── validate_container.py
│   ├── rebuild_index.py
│   ├── search_index.py
│   ├── extract_container.py
│   ├── corrupt_container.py
│   └── export_evidence_pack.py
├── src/
│   └── eec/
│       ├── __init__.py
│       ├── cli_common.py
│       ├── container_builder.py
│       ├── container_reader.py
│       ├── corruption.py
│       ├── demo_data.py
│       ├── exporter.py
│       ├── indexer.py
│       ├── models.py
│       ├── render_docs.py
│       ├── search.py
│       └── utils.py
└── tests/
    └── test_round_trip.py
```

Generated data is deliberately excluded from Git by `.gitignore`.

## Quick start on Windows PowerShell

```powershell
cd C:\ProjectsGit
Expand-Archive .\entity-evidence-container-demo.zip -DestinationPath .
cd .\entity-evidence-container-demo

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .

python scripts\demo_run.py --customers 3 --target-mb-per-customer 2
```

## Quick start on macOS/Linux

```bash
cd ~/Projects
unzip entity-evidence-container-demo.zip
cd entity-evidence-container-demo

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .

python scripts/demo_run.py --customers 3 --target-mb-per-customer 2
```


## Included small sample

The repository includes a small three-customer sample under `samples/` so the structure can be inspected immediately without generating a large dataset. The generated `data/` folder remains ignored by Git and is intended for local demo runs.

```powershell
python scripts\inspect_container.py --container samples\containers\CUST-000001.fits
python scripts\validate_container.py --container samples\containers\CUST-000001.fits
python scripts\search_index.py --sqlite samples\index\evidence_index.db --query "source of wealth"
```

## Generate a larger demo set

This does **not** store large files in Git. It creates them locally when you need them.

```powershell
python scripts\generate_sample_data.py --customers 50 --output data\source --target-mb-per-customer 25 --seed 42
python scripts\build_containers.py --source data\source --output data\containers
python scripts\rebuild_index.py --containers data\containers --sqlite data\index\evidence_index.db
```

For a heavier demo:

```powershell
python scripts\generate_sample_data.py --customers 50 --output data\source --target-mb-per-customer 100 --seed 42
```

That would aim for roughly 5GB of generated source evidence before FITS overhead.

## Inspect a container

```powershell
python scripts\inspect_container.py --container data\containers\CUST-000001.fits
```

Example output:

```text
Container: CUST-000001.fits
Entity: CUST-000001 / Eleanor Hartley
Payloads: 24
Container size: 2.3 MB
Retention classes: CDD, Statements, Correspondence, Complaint, Tax, Governance
```

## Validate integrity

```powershell
python scripts\validate_container.py --container data\containers\CUST-000001.fits
```

The validator compares each embedded payload against the SHA-256 stored in the manifest.

## Search the rebuilt index

```powershell
python scripts\search_index.py --sqlite data\index\evidence_index.db --query "source of wealth property sale"
```

Useful demo searches:

```powershell
python scripts\search_index.py --sqlite data\index\evidence_index.db --query "enhanced due diligence"
python scripts\search_index.py --sqlite data\index\evidence_index.db --query "complaint overdraft charge"
python scripts\search_index.py --sqlite data\index\evidence_index.db --query "source of wealth inheritance"
python scripts\search_index.py --sqlite data\index\evidence_index.db --query "fixed term deposit maturity"
```

## Extract evidence

```powershell
python scripts\extract_container.py --container data\containers\CUST-000001.fits --output data\extracted\CUST-000001
```

## Export a regulator-style evidence pack

```powershell
python scripts\export_evidence_pack.py --container data\containers\CUST-000001.fits --output data\evidence_packs\CUST-000001
```

This exports:

- original payload files;
- manifest JSON;
- validation report JSON;
- provenance JSON;
- a Markdown pack summary.

## Corruption detection demo

Create a deliberately corrupted copy of a container:

```powershell
python scripts\corrupt_container.py --container data\containers\CUST-000001.fits --output data\containers\CUST-000001-corrupt.fits --object-index 3
```

Then validate it:

```powershell
python scripts\validate_container.py --container data\containers\CUST-000001-corrupt.fits
```

The validator should report `Integrity: FAIL` and identify the individual corrupted object.

## How the FITS container is structured

Each customer container has:

```text
Primary HDU
 └── human-readable high-level header

ENTITY_METADATA HDU
 └── JSON entity metadata

MANIFEST HDU
 └── JSON manifest of all payloads

PROVENANCE HDU
 └── JSON provenance/audit events

PAYLOAD_000001 HDU
 └── original file bytes as uint8 array

PAYLOAD_000002 HDU
 └── original file bytes as uint8 array

...
```

The manifest records the original filename, MIME type, source system, document type, retention class, sensitivity, searchable text, SHA-256 and payload HDU name.

## Design principles

1. **Preserve originals.** The original PDF, EML, CSV, JSON or image bytes are embedded and recoverable byte-for-byte.
2. **Use derivatives for access.** Search text and generated previews are helpful but are not the legal/evidential source.
3. **Make indexes rebuildable.** The SQLite/FTS index is a convenience layer that can be rebuilt from the FITS containers.
4. **Isolate failure domains.** One entity container can fail validation without corrupting a central database.
5. **Prefer sealed snapshots.** For regulated evidence, immutable containers are easier to reason about than constantly mutated archives.

## POC limitations

This is a demonstrator, not production software. Before production use, you would need to address:

- encryption at rest and tenant key management;
- legal hold and retention policy enforcement;
- authenticated access controls;
- immutable object storage;
- WORM or equivalent storage controls;
- audit logging for user access;
- digital signatures/sealing;
- formal evidence admissibility review;
- operational resilience and backup/restore testing;
- OCR over real scans;
- redaction workflows;
- object versioning strategy.

## Suggested next enhancements

- Add PDF/A generation and validation.
- Add OCR using Tesseract or AWS Textract for scanned documents.
- Add cryptographic signing of the manifest.
- Add S3/MinIO object storage integration.
- Add FastAPI viewer with search and evidence-pack export.
- Add optional compression and chunking strategy.
- Add object-level retention/legal hold metadata.
- Add IIIF-style image viewing for scanned evidence.

## Streamlit demo UI

The repository includes a lightweight Streamlit interface for demonstrating the archive concept visually.

Run it from the repository root:

```powershell
python -m pip install -r requirements.txt
python -m pip install -e .
streamlit run app\streamlit_app.py
```

The UI includes:

- dashboard metrics for containers, entities, preserved objects and storage size;
- controls to generate sample evidence, build FITS containers and rebuild the SQLite/FTS index;
- customer/entity browser with container metadata and object manifest;
- object preview/download for text, email, JSON, CSV, images and preserved binary payloads;
- full-text search across the rebuilt index;
- integrity validation for one or all containers;
- corruption-copy creation to demonstrate SHA-256 failure detection;
- evidence pack export with metadata, manifest, provenance and validation report.

For a larger demonstrator, generate data from the CLI first, then open the UI:

```powershell
python scripts\generate_sample_data.py --customers 50 --output data\source --target-mb-per-customer 25 --seed 42
python scripts\build_containers.py --source data\source --output data\containers
python scripts\rebuild_index.py --containers data\containers --sqlite data\index\evidence_index.db
streamlit run app\streamlit_app.py
```

Then change the UI sidebar root folder from `samples` to `data`.
