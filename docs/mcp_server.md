# TrustVault MCP Server

TrustVault can expose its FITS evidence archive to LM Studio and other MCP-compatible clients through a controlled Model Context Protocol server.

The MCP server is designed to make the archive queryable by a local/private LLM without exposing arbitrary filesystem access, arbitrary SQL execution, or unrestricted evidence payload downloads.

## Design principles

- FITS containers remain the durable source of truth.
- The SQLite/FTS and vector indexes are disposable acceleration layers and can be rebuilt from FITS.
- Selected-customer evidence queries use direct FITS search where possible.
- Cross-customer and cohort queries use the rebuilt index for performance.
- AI use is optional and evidence-bound.
- The MCP tool layer returns metadata and snippets by default, not full sensitive documents.
- Evidence pack export is disabled by default.
- Binary payload reads are disabled by default.

## New files

```text
src/eec/mcp_tools.py       Pure Python tool functions used by tests and MCP transport
src/eec/mcp_server.py      FastMCP server wrapper exposing tools and resources
scripts/run_mcp_server.py  Local runner for stdio-based MCP clients
tests/test_mcp_tools.py    Lightweight tests for configuration, query normalisation and export guarding
docs/mcp_server.md         This guide
```

## Install

Install the existing project dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

Install the optional MCP dependency:

```powershell
python -m pip install -e ".[mcp]"
```

Or install the SDK directly:

```powershell
python -m pip install "mcp[cli]"
```

If the MCP SDK is not installed, `trustvault-mcp` and `scripts/run_mcp_server.py` fail safely with clear install instructions.

## Configuration

The server reads archive locations and security flags from environment variables.

```powershell
$env:TRUSTVAULT_ROOT = "data"
$env:TRUSTVAULT_SOURCE_DIR = "data/source"
$env:TRUSTVAULT_CONTAINERS_DIR = "data/containers"
$env:TRUSTVAULT_INDEX_PATH = "data/index/evidence_index.db"
$env:TRUSTVAULT_VECTOR_PATH = "data/index/evidence_vector.pkl"
$env:TRUSTVAULT_LMSTUDIO_VECTOR_PATH = "data/index/evidence_lmstudio_vector.pkl"
$env:TRUSTVAULT_EXPORTS_DIR = "data/exports"
$env:TRUSTVAULT_MCP_READ_ONLY = "true"
$env:TRUSTVAULT_MCP_ENABLE_EXPORT = "false"
$env:TRUSTVAULT_MCP_ENABLE_PAYLOAD_READ = "false"
$env:TRUSTVAULT_MCP_MAX_RESULTS = "25"
```

For macOS/Linux shells:

```bash
export TRUSTVAULT_ROOT=data
export TRUSTVAULT_SOURCE_DIR=data/source
export TRUSTVAULT_CONTAINERS_DIR=data/containers
export TRUSTVAULT_INDEX_PATH=data/index/evidence_index.db
export TRUSTVAULT_VECTOR_PATH=data/index/evidence_vector.pkl
export TRUSTVAULT_LMSTUDIO_VECTOR_PATH=data/index/evidence_lmstudio_vector.pkl
export TRUSTVAULT_EXPORTS_DIR=data/exports
export TRUSTVAULT_MCP_READ_ONLY=true
export TRUSTVAULT_MCP_ENABLE_EXPORT=false
export TRUSTVAULT_MCP_ENABLE_PAYLOAD_READ=false
export TRUSTVAULT_MCP_MAX_RESULTS=25
```

## Run locally

From the repository root:

```powershell
python scripts\run_mcp_server.py
```

Or, after installing the package in editable mode:

```powershell
trustvault-mcp
```

The default transport is `stdio`, which is the normal local transport for desktop MCP clients.

For testing with an HTTP-capable MCP client:

```powershell
trustvault-mcp --transport streamable-http
```

## LM Studio MCP configuration example

Adjust the paths to your local checkout and virtual environment.

### Windows example

```json
{
  "mcpServers": {
    "trustvault": {
      "command": "C:\\ProjectsGit\\entity-evidence-container-demo\\.venv\\Scripts\\python.exe",
      "args": [
        "C:\\ProjectsGit\\entity-evidence-container-demo\\scripts\\run_mcp_server.py"
      ],
      "env": {
        "TRUSTVAULT_ROOT": "C:\\ProjectsGit\\entity-evidence-container-demo\\data",
        "TRUSTVAULT_SOURCE_DIR": "C:\\ProjectsGit\\entity-evidence-container-demo\\data\\source",
        "TRUSTVAULT_CONTAINERS_DIR": "C:\\ProjectsGit\\entity-evidence-container-demo\\data\\containers",
        "TRUSTVAULT_INDEX_PATH": "C:\\ProjectsGit\\entity-evidence-container-demo\\data\\index\\evidence_index.db",
        "TRUSTVAULT_VECTOR_PATH": "C:\\ProjectsGit\\entity-evidence-container-demo\\data\\index\\evidence_vector.pkl",
        "TRUSTVAULT_LMSTUDIO_VECTOR_PATH": "C:\\ProjectsGit\\entity-evidence-container-demo\\data\\index\\evidence_lmstudio_vector.pkl",
        "TRUSTVAULT_EXPORTS_DIR": "C:\\ProjectsGit\\entity-evidence-container-demo\\data\\exports",
        "TRUSTVAULT_MCP_READ_ONLY": "true",
        "TRUSTVAULT_MCP_ENABLE_EXPORT": "false",
        "TRUSTVAULT_MCP_ENABLE_PAYLOAD_READ": "false",
        "TRUSTVAULT_MCP_MAX_RESULTS": "25"
      }
    }
  }
}
```

### macOS/Linux example

```json
{
  "mcpServers": {
    "trustvault": {
      "command": "/Users/mike/ProjectsGit/entity-evidence-container-demo/.venv/bin/python",
      "args": [
        "/Users/mike/ProjectsGit/entity-evidence-container-demo/scripts/run_mcp_server.py"
      ],
      "env": {
        "TRUSTVAULT_ROOT": "/Users/mike/ProjectsGit/entity-evidence-container-demo/data",
        "TRUSTVAULT_SOURCE_DIR": "/Users/mike/ProjectsGit/entity-evidence-container-demo/data/source",
        "TRUSTVAULT_CONTAINERS_DIR": "/Users/mike/ProjectsGit/entity-evidence-container-demo/data/containers",
        "TRUSTVAULT_INDEX_PATH": "/Users/mike/ProjectsGit/entity-evidence-container-demo/data/index/evidence_index.db",
        "TRUSTVAULT_VECTOR_PATH": "/Users/mike/ProjectsGit/entity-evidence-container-demo/data/index/evidence_vector.pkl",
        "TRUSTVAULT_LMSTUDIO_VECTOR_PATH": "/Users/mike/ProjectsGit/entity-evidence-container-demo/data/index/evidence_lmstudio_vector.pkl",
        "TRUSTVAULT_EXPORTS_DIR": "/Users/mike/ProjectsGit/entity-evidence-container-demo/data/exports",
        "TRUSTVAULT_MCP_READ_ONLY": "true",
        "TRUSTVAULT_MCP_ENABLE_EXPORT": "false",
        "TRUSTVAULT_MCP_ENABLE_PAYLOAD_READ": "false",
        "TRUSTVAULT_MCP_MAX_RESULTS": "25"
      }
    }
  }
}
```

## Exposed MCP tools

### `trustvault_archive_status`

Returns configured archive paths and high-level status.

Example arguments:

```json
{}
```

Expected result shape:

```json
{
  "product": "TrustVault",
  "paths": {
    "source_folder": "data/source",
    "containers_folder": "data/containers",
    "index_path": "data/index/evidence_index.db"
  },
  "entity_count": 50,
  "container_count": 250,
  "indexed_object_count": 1234
}
```

### `trustvault_list_entities`

Lists customer/entity records.

Example arguments:

```json
{
  "jurisdiction": "Guernsey",
  "risk_rating": "High",
  "limit": 10
}
```

Returns rows containing:

```text
entity_id, display_name, entity_type, jurisdiction, risk_rating, object_count, payload_size_bytes
```

### `trustvault_get_entity_summary`

Returns metadata and evidence summary for one entity.

Example arguments:

```json
{
  "entity_id": "CUST-000001"
}
```

Returns:

- entity metadata;
- FITS container names and paths;
- counts by category, document type and snapshot;
- available source systems;
- retention/legal-hold summary;
- completeness status when the index is available.

### `trustvault_search_entity_fits`

Searches one entity's FITS container(s) directly.

Example arguments:

```json
{
  "entity_id": "CUST-000001",
  "query": "source of wealth",
  "limit": 5,
  "snapshot_id": "CDD_REVIEW_2026"
}
```

Returns evidence rows containing:

```text
object_id, filename, document_type, category, snapshot_id, source_system,
captured_at, snippet, sha256, container_path
```

### `trustvault_search_archive`

Searches across the archive using the rebuilt SQLite/FTS index.

Example arguments:

```json
{
  "query": "source of funds",
  "jurisdiction": "Guernsey",
  "risk_rating": "High",
  "limit": 10
}
```

Returns both flat rows and grouped rows by `entity_id`.

### `trustvault_interpret_query`

Converts a natural-language archive request into the existing `StructuredArchiveQuery` format.

Example arguments:

```json
{
  "query": "Show me all onboarding documentation for high risk clients in Guernsey",
  "use_local_ai": false,
  "limit": 25
}
```

Expected normalisation:

```json
{
  "snapshot_id": "ONBOARDING",
  "document_type": null,
  "risk_rating": "High",
  "jurisdiction": "Guernsey"
}
```

Important: onboarding is a lifecycle snapshot, not a document type.

### `trustvault_execute_query`

Interprets and executes a natural-language query.

Example selected-customer query:

```json
{
  "query": "Show me source of wealth evidence",
  "selected_entity_id": "CUST-000001",
  "use_local_ai": false,
  "limit": 5
}
```

Expected source note:

```text
Selected-customer evidence query used direct FITS search.
```

Example cohort query:

```json
{
  "query": "Show me all onboarding documentation for high risk clients in Guernsey",
  "use_local_ai": false,
  "limit": 25
}
```

Expected source note:

```text
Cross-customer/cohort query used the rebuilt index.
```

### `trustvault_check_completeness`

Checks evidence completeness for one or more customers.

Example arguments:

```json
{
  "jurisdiction": "Guernsey",
  "risk_rating": "High",
  "missing_only": true,
  "ruleset_id": "retail_cdd_v1"
}
```

Returns:

- completeness summary;
- rows showing present and missing evidence;
- ruleset used.

### `trustvault_get_evidence_payload_metadata`

Returns metadata and a safe preview for a specific evidence object.

Example arguments:

```json
{
  "entity_id": "CUST-000001",
  "object_id": "OBJ-000001"
}
```

This tool does not return full binary payloads. It returns metadata, hash, retention fields, legal-hold status, MIME type, size and safe preview text.

### `trustvault_export_evidence_pack`

Exports an evidence pack from object IDs, an entity or query results.

This tool is disabled by default.

To enable it:

```powershell
$env:TRUSTVAULT_MCP_READ_ONLY = "false"
$env:TRUSTVAULT_MCP_ENABLE_EXPORT = "true"
```

Example arguments:

```json
{
  "entity_id": "CUST-000001",
  "object_ids": ["OBJ-000001", "OBJ-000002"],
  "output_name": "CUST-000001_regulator_pack"
}
```

Returns:

```json
{
  "status": "created",
  "export_path": "data/exports/CUST-000001_regulator_pack",
  "manifest_summary": {
    "object_count": 2,
    "hash_status": "PASS"
  },
  "hash_report_path": "data/exports/CUST-000001_regulator_pack/HASH_REPORT.json"
}
```

## Exposed MCP resources

```text
trustvault://entities
trustvault://entities/{entity_id}
trustvault://entities/{entity_id}/evidence
trustvault://containers/{entity_id}
trustvault://rulesets
trustvault://archive/status
```

Resources are intentionally concise. Use the tools for filtered searches and detailed metadata lookups.

## Tests

Run the MCP tool tests:

```powershell
python -m pytest tests\test_mcp_tools.py
```

Run the full suite:

```powershell
python -m pytest
```

## Security notes

The MCP server does not expose:

- arbitrary file reads;
- arbitrary SQL execution;
- unrestricted binary payload download;
- write access to the archive;
- export by default.

Configuration is controlled by environment variables. Tool calls are ordinary Python functions and are suitable for later audit logging by wrapping calls in `src/eec/mcp_tools.py` or in the MCP transport wrapper.

## Limitations

- Cross-customer/cohort queries require a current SQLite/FTS index.
- Completeness checks require the rebuilt index.
- Selected-customer evidence searches can operate directly against FITS.
- MCP export currently creates a selected-evidence pack and should be used with care because exports may contain sensitive data.
- `TRUSTVAULT_MCP_ENABLE_PAYLOAD_READ` is recorded in status and metadata responses but no binary payload download MCP tool is exposed by default.
