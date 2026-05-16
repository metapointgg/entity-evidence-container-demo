# Entity Evidence Container Demo

This proof of concept explores using FITS as a self-describing, entity-level preservation container for financial-services evidence.

The goal is not to replace live CRM, core banking, workflow or document management. The goal is to prove that customer, account, case or regulatory evidence can be preserved as portable objects that contain the original payloads, metadata, provenance, retention data and SHA-256 fixity information, with search indexes that can be rebuilt from the preserved containers.

## Current capabilities

- Synthetic financial-services customer evidence generation.
- Rich sample content: applications, CDD reviews, passport scans, source-of-wealth scans, statements, emails, transaction extracts, audit events and large binary archive payloads.
- FITS preservation container build.
- Immutable snapshot/version model.
- SQLite/FTS keyword search.
- Local semantic-style search.
- Local offline vector search using scikit-learn TF-IDF vectors.
- Structured filters/facets.
- OCR/indexing pipeline with sidecar, PDF text and optional Tesseract modes.
- Regulatory evidence search presets.
- Search-result evidence pack export.
- Integrity dashboard and corruption detection.
- Retention and legal-hold reporting.
- Streamlit demo UI.
- FastAPI API layer.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```


## Refresh or repair demo assets

If you overlay this repo on top of an older copy, your existing `samples/index/evidence_index.db` or `data/index/evidence_index.db` may have an older schema. Rebuild the containers and indexes with:

```powershell
python scripts\refresh_demo_assets.py --root samples --clean
```

For your larger generated demo:

```powershell
python scripts\refresh_demo_assets.py --root data --clean
```

To regenerate the sample source data as well:

```powershell
python scripts\refresh_demo_assets.py --root samples --clean --regenerate --customers 3 --target-mb-per-customer 2 --seed 42
```

## Run the Streamlit UI

```powershell
streamlit run app\streamlit_app.py
```

The included `samples` folder already contains a small 3-customer snapshot demo, a SQLite index and a local vector index.

## Generate a larger 50-customer demo

```powershell
python scripts\generate_sample_data.py `
  --customers 50 `
  --output data\source `
  --target-mb-per-customer 25 `
  --seed 42
```

Build immutable snapshot containers:

```powershell
python scripts\build_containers.py `
  --source data\source `
  --output data\containers `
  --snapshot-model
```

Rebuild the SQLite/FTS index:

```powershell
python scripts\rebuild_index.py `
  --containers data\containers `
  --sqlite data\index\evidence_index.db
```

Build the local offline vector index:

```powershell
python scripts\build_vector_index.py `
  --sqlite data\index\evidence_index.db `
  --output data\index\evidence_vector.pkl
```

Then run the UI and set the sidebar root folder to:

```text
data
```

## Snapshot/version model

The `--snapshot-model` option builds several smaller, immutable preservation containers per entity:

```text
CUST-000001__ONBOARDING.fits
CUST-000001__CDD_REVIEW_2026.fits
CUST-000001__STATEMENTS_2026_Q1.fits
CUST-000001__CORRESPONDENCE_2026.fits
CUST-000001__TRANSACTIONS_2026_Q1.fits
CUST-000001__LEGAL_DISCLOSURE.fits
```

This is more realistic than one very large file per customer because it improves corruption isolation, retention handling, legal-hold handling and incremental archive growth.

## OCR options

The builder uses `EEC_OCR_PROVIDER` to control indexing/OCR behaviour:

```powershell
$env:EEC_OCR_PROVIDER = "auto"
```

Supported values:

| Provider | Behaviour |
|---|---|
| `auto` | Sidecar text/direct text/PDF text, then Tesseract for images if available. |
| `sidecar` | Generated `.search.txt` sidecars, direct text and PDF text. |
| `tesseract` | Try native Tesseract OCR for image files before sidecars. |
| `none` | Only direct text formats are indexed. |

Tesseract mode requires the native Tesseract executable to be installed on your machine as well as the Python `pytesseract` package.

## Search examples

Keyword:

```powershell
python scripts\search_index.py `
  --sqlite data\index\evidence_index.db `
  --query "source of wealth"
```

Vector:

```powershell
python scripts\search_vector_index.py `
  --index data\index\evidence_vector.pkl `
  --query "show me documents that explain where the customer money came from"
```

Good demo searches:

```text
source of wealth
customer due diligence
high risk enhanced due diligence
passport
monthly statement
customer correspondence
legal hold disclosure evidence
show me documents that explain where the customer money came from
find evidence that would help respond to a regulator
```

## Integrity and corruption demo

Create a corrupted copy:

```powershell
python scripts\corrupt_container.py `
  --container data\containers\CUST-000001__ONBOARDING.fits `
  --output data\containers\CUST-000001__ONBOARDING-corrupt.fits `
  --object-index 3
```

Validate:

```powershell
python scripts\validate_container.py `
  --container data\containers\CUST-000001__ONBOARDING-corrupt.fits
```

The validator checks each preserved payload against its SHA-256 hash and reports the exact failed object.

## Export evidence packs

Single container:

```powershell
python scripts\export_evidence_pack.py `
  --container data\containers\CUST-000001__CDD_REVIEW_2026.fits `
  --output data\exports\CUST-000001_CDD_REVIEW_2026
```

Search result exports are available from the UI Search tab.

## API layer

Start the API:

```powershell
uvicorn app.api:app --reload --host 127.0.0.1 --port 8000
```

Example endpoints:

```text
GET  /health?root=samples
POST /index/rebuild?root=samples
GET  /entities?root=samples
GET  /entities/{entity_id}/objects?root=samples
GET  /search?root=samples&q=source%20of%20wealth&mode=keyword
GET  /search?root=samples&q=where%20did%20money%20come%20from&mode=vector
GET  /containers/{container_name}/inspect?root=samples
GET  /containers/{container_name}/validate?root=samples
```

Interactive docs:

```text
http://127.0.0.1:8000/docs
```

## Architecture proposition

```text
Source systems
  ├─ Core Banking
  ├─ Salesforce / CRM
  ├─ Email Archive
  ├─ AML / KYC Platform
  ├─ Statement Engine
  └─ Document Store
        ↓
Entity Evidence Builder
        ↓
Self-describing FITS Preservation Containers
        ↓
Rebuildable SQLite/FTS and Local Vector Indexes
        ↓
Streamlit UI / API / Evidence Pack Export / Validation
```

The important principle is that the database/search index is an access layer. The preserved container remains the durable evidence object.
