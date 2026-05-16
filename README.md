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

## Local LM Studio integration

The demo can optionally use local models served by LM Studio. This keeps AI assistance local to the machine running the POC.

Recommended model roles:

| Model | Role |
|---|---|
| `qwen/qwen3.5-9b` | Query expansion and structured search assistance |
| `google/gemma-4-e4b` | Result summaries and ask-the-archive answers |
| `text-embedding-nomic-embed-text-v1.5` | Local embedding/vector search |

Set the environment variables before running Streamlit or the API:

```bash
export EEC_LM_STUDIO_BASE_URL="http://127.0.0.1:1234/v1"
export EEC_LM_STUDIO_MODEL="google/gemma-4-e4b"
export EEC_LM_STUDIO_QUERY_MODEL="qwen/qwen3.5-9b"
export EEC_LM_STUDIO_EMBEDDING_MODEL="text-embedding-nomic-embed-text-v1.5"
```

Check that LM Studio is available:

```bash
python scripts/list_lm_studio_models.py
python scripts/test_lm_studio.py
```

Build the normal TF-IDF vector index and the LM Studio embedding index:

```bash
python scripts/refresh_demo_assets.py --root samples --clean --lmstudio-vector
```

Or build only the LM Studio embedding index:

```bash
python scripts/build_lmstudio_vector_index.py \
  --sqlite samples/index/evidence_index.db \
  --output samples/index/evidence_lmstudio_vector.pkl
```

Search the LM Studio embedding index:

```bash
python scripts/search_lmstudio_vector_index.py \
  --index samples/index/evidence_lmstudio_vector.pkl \
  --query "where did the customer money come from" \
  --limit 5
```

In Streamlit, open the **Dashboard** tab to see LM Studio status and build the LM Studio embedding index, then use **Search → lmstudio-vector** mode. The search tab also supports optional local LLM query expansion, result summarisation, and ask-the-archive over retrieved evidence.

The LLM is intentionally assistive only. It expands queries and summarises retrieved evidence, but the FITS preservation containers remain the source of truth.

## Intent-led search UI

The Search tab now works around user intent rather than exposing every search mechanism directly.

Recommended scenarios:

1. **Selected customer evidence question**
   - Scope: `Selected customer`
   - Query: `What is the customer's source of wealth?`
   - Output: supporting evidence rows plus a local AI summary where LM Studio is available.

2. **Customer discovery**
   - Scope: `All customers`
   - Query: `Show me customers in Guernsey who are high risk`
   - Output: customer list, not document rows.

3. **Cohort evidence retrieval**
   - Scope: `All customers`
   - Query: `Show me the CDD for customers in Guernsey who are high risk`
   - Output: evidence rows grouped by customer.

4. **Retention/legal hold review**
   - Scope: `All customers`
   - Query: `Show me documents past retention date but blocked by legal hold`
   - Output: retention/legal-hold evidence rows.

The local LLM is used as a controlled interpretation and summarisation layer. It does **not** generate SQL. It produces a constrained structured query which is then validated and executed by application code.

You can test the interpreter from the command line:

```bash
python scripts/test_structured_search.py \
  --query "Show me the CDD for customers in Guernsey who are high risk"

python scripts/test_structured_search.py \
  --entity-id CUST-000001 \
  --query "What is the customer's source of wealth?"
```

## Intent-led search capability matrix

The Search tab now routes natural-language requests through a constrained query capability matrix rather than exposing search mechanics directly. The local LLM may interpret a user request into JSON, but the application validates it against supported capabilities and then executes deterministic Python/SQLite logic. The LLM never generates SQL.

Supported capabilities include:

- `customer_evidence_question` — answer a question about a selected customer using retrieved evidence.
- `customer_evidence_retrieval` — retrieve evidence for a selected customer.
- `customer_discovery` — find customers by risk, jurisdiction or similar customer-level filters.
- `missing_evidence_review` — find customers in a cohort who lack a required document/evidence type.
- `cohort_evidence_retrieval` — retrieve evidence for a cohort and group it by customer.
- `regulatory_pack_request` — retrieve/export evidence for audit or regulatory pack use cases.
- `retention_legal_hold_review` — review records by retention, legal hold or deletion status.
- `archive_health_query` — route integrity/corruption queries to archive-health logic.
- `general_archive_search` — fallback evidence search.

List the matrix from the command line:

```bash
python scripts/list_query_capabilities.py
```

Useful test queries:

```text
What is the customer's source of wealth?
Show me customers who are high risk
Show me customers in Guernsey who are high risk
Show me the CDD for customers in Guernsey who are high risk
Show me customers who are high risk and do not have proof of address
Show me all onboarding documentation for high risk clients in Guernsey
Show me documents past retention date but blocked by legal hold
Show me containers with integrity failures
```

## Evidence completeness and rulesets

The demo now includes a rules-driven evidence completeness layer.

### Default ruleset

The default ruleset is stored in `samples/config/evidence_rulesets.json` when first created and can be edited in the Streamlit **Rulesets** tab.

| Customer profile | Required evidence |
|---|---|
| Low-risk individual | Application, Passport / ID, Proof of Address, CDD Review |
| Medium-risk individual | Application, Passport / ID, Proof of Address, CDD Review, Source of Funds |
| High-risk individual | Application, Passport / ID, Proof of Address, CDD Review, Source of Wealth, Source of Funds, Screening, EDD Approval |
| Corporate customer | Application, Company Registry Extract, Beneficial Owner Evidence, Authorised Signatory ID, Proof of Address, CDD Review, Source of Funds |

### UI workflow

Run the app:

```bash
streamlit run app/streamlit_app.py
```

Use the new tabs:

- **Completeness**: evaluate customers against the selected evidence ruleset, view missing evidence and export reports.
- **Rulesets**: edit customer profiles and required evidence items.

### Command-line evaluation

```bash
python scripts/evaluate_completeness.py \
  --sqlite samples/index/evidence_index.db \
  --root samples
```

Filter examples:

```bash
python scripts/evaluate_completeness.py \
  --sqlite samples/index/evidence_index.db \
  --root samples \
  --risk-rating High \
  --missing-item "Proof of Address"
```

Export a report:

```bash
python scripts/evaluate_completeness.py \
  --sqlite samples/index/evidence_index.db \
  --root samples \
  --export samples/exports/completeness_report
```

### Natural-language examples

The Search tab can now route completeness-style requests to the ruleset engine:

```text
Is this customer's onboarding file complete?
Which customers have incomplete onboarding files?
Show me customers missing mandatory evidence
Show me high-risk customers with incomplete onboarding documentation
```

For deterministic edge-case testing, regenerate data with:

```bash
python scripts/refresh_demo_assets.py \
  --root samples \
  --clean \
  --regenerate \
  --customers 3 \
  --target-mb-per-customer 2 \
  --seed 42 \
  --include-edge-cases
```

This creates `CUST-999001`, a high-risk Guernsey customer deliberately missing Proof of Address evidence.

## Evidence Pack Export v2

Evidence pack export now creates a regulator/audit-friendly folder rather than just recovered payloads.

Search result exports include:

```text
README.md
EVIDENCE_PACK_SUMMARY.md
AI_SUMMARY.md
QUERY.json
STRUCTURED_QUERY.json
RULESET_USED.json
COMPLETENESS_REPORT.json
MANIFEST.json
HASH_REPORT.json
SOURCE_SYSTEMS.json
RETENTION_LEGAL_HOLD_REPORT.json
files/
```

The pack captures:

- the original natural-language query;
- the controlled structured query used by the application;
- recovered original payload files from the FITS containers;
- SHA-256 hashes for exported files compared with preserved manifest hashes;
- source-system provenance counts;
- retention and legal-hold context;
- completeness/ruleset context where applicable;
- any cached local-AI summary generated from the retrieved evidence.

The AI summary is assistive only. The manifest, hash report and recovered files remain the evidence of record.

Single-container exports from the Export tab now use the same report layout, with `files/` containing the extracted container payloads and JSON reports around the export.

## Next roadmap: ingestion and OCR

The next architectural stage is ingestion. The POC should support both:

1. **Bulk ingestion** — one-off import of historical customer folders, legacy exports, email archives, statements and CDD evidence.
2. **Continuous ingestion** — event-driven updates from source systems such as Salesforce, AML platforms, statement engines, email archives and document stores.

Recommended ingestion pipeline:

```text
Source systems / drop folders / APIs
        ↓
Ingestion manifest builder
        ↓
OCR and metadata extraction
        ↓
Evidence classification and ruleset mapping
        ↓
Snapshot/container builder
        ↓
Index rebuild or incremental index update
        ↓
Completeness / exception checks
```

OCR should be pluggable:

```text
EEC_OCR_PROVIDER=sidecar      # deterministic demo text files
EEC_OCR_PROVIDER=tesseract    # local/offline OCR
EEC_OCR_PROVIDER=aws_textract # future production-style option
EEC_OCR_PROVIDER=none
```

OCR output should be stored in the FITS manifest/search text so scanned documents remain searchable even if the original payload is an image-only PDF or scan.

## Bulk and continuous ingestion

The demo now includes an ingestion layer that normalises source-system files into the archive `source/` structure before FITS containers are built.

### Bulk ingestion

Bulk ingestion is for one-off imports of historical customer folders, legacy document stores, email exports, statements and CDD evidence.

Create a demo import set:

```bash
python scripts/create_ingestion_demo.py --root data/ingestion_demo
```

Run a manifest-driven import:

```bash
python scripts/bulk_ingest.py \
  --input data/ingestion_demo/legacy_export \
  --source data/source \
  --manifest data/ingestion_demo/legacy_export/bulk_manifest.csv \
  --default-jurisdiction Guernsey \
  --default-risk-rating Medium
```

Run a folder-discovery import without a manifest:

```bash
python scripts/bulk_ingest.py \
  --input data/ingestion_demo/legacy_export \
  --source data/source
```

The importer writes files under each customer folder and creates `.eec.json` sidecar metadata files. The FITS builder reads those sidecars so the preserved payload records carry source-system, category, document type, retention and sensitivity metadata.

### Continuous ingestion

Continuous ingestion is event-driven. A source system drops JSON events into a queue folder. Each event identifies the customer and file to ingest.

Example event:

```json
{
  "event_id": "EVT-STATEMENT-0001",
  "entity_id": "CUST-BULK001",
  "display_name": "Beatrice Martel",
  "jurisdiction": "Guernsey",
  "risk_rating": "High",
  "file_path": "data/ingestion_demo/continuous_payloads/CUST-BULK001_new_statement.pdf",
  "source_system": "Statement Engine",
  "category": "Statements",
  "document_type": "Monthly Statement",
  "retention_class": "Statements",
  "snapshot_id": "STATEMENT_EVENT_2026_04",
  "snapshot_type": "Continuous Statement Event"
}
```

Process the queue:

```bash
python scripts/process_ingestion_queue.py \
  --queue data/ingestion_demo/queue \
  --source data/source
```

Or ingest a single event:

```bash
python scripts/ingest_event.py \
  --event data/ingestion_demo/queue/event_statement_0001.json \
  --source data/source
```

After any ingestion, rebuild containers and indexes:

```bash
python scripts/build_containers.py \
  --source data/source \
  --output data/containers \
  --snapshot-model

python scripts/rebuild_index.py \
  --containers data/containers \
  --sqlite data/index/evidence_index.db

python scripts/build_vector_index.py \
  --sqlite data/index/evidence_index.db \
  --output data/index/evidence_vector.pkl
```

If LM Studio is running and you want embedding search:

```bash
python scripts/build_lmstudio_vector_index.py \
  --sqlite data/index/evidence_index.db \
  --output data/index/evidence_lmstudio_vector.pkl
```

### Ingestion UI

The Streamlit app includes an **Ingestion** tab with:

- bulk import from a source folder and optional manifest;
- continuous queue processing;
- post-ingestion rebuild of FITS containers and indexes;
- recent ingestion report inspection.

### API endpoints

The FastAPI layer includes ingestion endpoints:

```text
POST /ingestion/bulk?root=data&input_path=data/ingestion_demo/legacy_export
POST /ingestion/event?root=data
POST /ingestion/queue/process?root=data&queue_path=data/ingestion_demo/queue
```

The event endpoint accepts the same JSON payload shape used by the queue processor.

### OCR/searchable text during ingestion

The ingestion layer preserves the original document bytes and writes metadata sidecars. Searchable text is extracted when containers are built through `EEC_OCR_PROVIDER`:

- `auto` uses sidecars/direct text/PDF text, then Tesseract for images if available;
- `sidecar` uses existing `.search.txt` sidecars and embedded text extraction;
- `tesseract` prioritises native OCR for image files;
- `none` only indexes direct text formats.

This keeps ingestion and preservation separate: ingestion captures and classifies evidence, while the container build extracts text and embeds the searchable text in the FITS manifest.

## Architecture update: one active FITS file per entity

The default container build now follows **Option A — rebuild the customer/entity FITS file on update**.

Default build:

```bash
python scripts/build_containers.py \
  --source data/source \
  --output data/containers
```

This produces one active FITS file per entity:

```text
data/containers/CUST-000001.fits
data/containers/CUST-000002.fits
data/containers/CUST-999001.fits
```

Each entity FITS file contains internal logical snapshots in the `SNAPSHOTS` and `MANIFEST` HDUs. For example, a single `CUST-000001.fits` can contain evidence grouped as:

```text
ONBOARDING
CDD_REVIEW_2026
STATEMENTS_2026_Q1
CORRESPONDENCE_2026
TRANSACTIONS_2026_Q1
LEGAL_DISCLOSURE
```

The previous split-snapshot mode is still available for comparison or testing:

```bash
python scripts/build_containers.py \
  --source data/source \
  --output data/containers \
  --split-snapshots
```

### Rebuild-on-update

After bulk or continuous ingestion updates one customer's source folder, rebuild only that customer's active FITS container:

```bash
python scripts/rebuild_entity_container.py \
  --entity-id CUST-000001 \
  --source data/source \
  --output data/containers \
  --retain-version \
  --rebuild-index \
  --sqlite data/index/evidence_index.db
```

When `--retain-version` is supplied, the previous active container is copied into:

```text
data/containers/_versions/<ENTITY_ID>/
```

This keeps the simple user-facing model — one current entity archive — while preserving previous sealed versions for audit/rollback.

## Direct FITS search

The archive now supports direct search of a customer/entity FITS file without using the SQLite or vector indexes. This is intended to demonstrate that the FITS container is the preserved, self-describing source of truth. The indexes remain useful as rebuildable acceleration layers for cohort and cross-customer search.

Search a specific customer/entity container directly:

```bash
python scripts/search_fits_direct.py \
  --container samples/containers/CUST-000001.fits \
  --query "source of wealth" \
  --limit 5
```

Or search by entity ID:

```bash
python scripts/search_fits_direct.py \
  --containers samples/containers \
  --entity-id CUST-000001 \
  --query "where did the customer money come from" \
  --limit 5
```

In the Streamlit UI, selected-customer evidence searches default to direct FITS search. Cross-customer searches continue to use the rebuilt SQLite/FTS and vector indexes.

API endpoint:

```text
GET /search/direct-fits?root=samples&entity_id=CUST-000001&q=source%20of%20wealth
GET /search/direct-fits?root=samples&container_name=CUST-000001.fits&q=source%20of%20wealth
```

Architectural rule:

```text
FITS container = durable source of truth
SQLite/vector indexes = disposable search acceleration rebuilt from FITS
```

## OCR and structured extraction

The current architecture now treats each FITS container as more than a binary evidence store. During container build, each source payload is processed through a deterministic extraction pipeline:

1. preserve the original payload byte-for-byte;
2. extract searchable text using generated sidecars, direct text, PDF text, or optional Tesseract OCR;
3. derive structured fields such as detected names, addresses, dates, jurisdictions, source-of-wealth signals, risk-rating signals and evidence-quality flags;
4. store the original payload, OCR text, extracted fields and extraction events inside the customer/entity FITS file.

The following FITS HDUs are now included where available:

```text
OCR_TEXT
EXTRACTED_FIELDS
EXTRACTION_EVENTS
```

The rebuilt SQLite/FTS and vector indexes remain disposable acceleration layers. The source of truth is still the customer/entity FITS file.

### OCR provider

Set the OCR provider before building containers:

```bash
export EEC_OCR_PROVIDER=auto       # sidecar/direct/PDF text first, optional OCR fallback
export EEC_OCR_PROVIDER=sidecar    # generated sidecars/direct/PDF text, no native OCR
export EEC_OCR_PROVIDER=tesseract  # prefer native image OCR where possible
export EEC_OCR_PROVIDER=none       # direct text only
```

For native OCR on macOS:

```bash
brew install tesseract
python -m pip install pytesseract
```

Then rebuild containers and indexes:

```bash
python scripts/refresh_demo_assets.py --root samples --clean --regenerate --customers 3 --target-mb-per-customer 2 --seed 42 --include-edge-cases
```

### Inspect extraction results

```bash
python scripts/extraction_report.py --sqlite samples/index/evidence_index.db
python scripts/extraction_report.py --container samples/containers/CUST-000001.fits
```

The Streamlit app now includes an **Extraction** tab showing OCR source counts, extracted field counts, low-confidence extraction rows, and per-customer extracted field details.

### Example extraction-led queries

```text
Show me proof of address documents with low OCR confidence.
What address was extracted from this customer's proof of address?
Show me customers where source of wealth mentions property sale.
Show me documents where source of wealth mentions investment income.
Show me documents with low text extraction signal.
```

## Basic and Advanced UI modes

The Streamlit UI now supports two modes from the sidebar:

- **Basic**: a clean operational interface for normal users. It shows Search, Customers, Completeness and Evidence Packs. Search uses sensible defaults: local AI interpretation where available, direct FITS search for selected-customer evidence, AI summaries where relevant, and the rebuildable index for portfolio/cohort queries.
- **Advanced**: the full technical/demo interface with dashboard, health, comparison, rulesets, ingestion, extraction, retention, integrity, export and API tabs, plus detailed search controls and interpreted-query diagnostics.

Use Basic mode for business-user walkthroughs and Advanced mode for development, diagnostics and architecture demonstrations.
