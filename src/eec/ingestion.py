from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

from .utils import safe_rel_path, sha256_file, slug, utc_now_iso, write_json

SUPPORTED_SOURCE_EXTENSIONS = {
    ".pdf", ".eml", ".msg", ".txt", ".json", ".csv", ".xml", ".html", ".htm",
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".doc", ".docx", ".xls", ".xlsx",
}

DEFAULT_ENTITY_TYPE = "Individual"
DEFAULT_RISK_RATING = "Medium"
DEFAULT_JURISDICTION = "Guernsey"


@dataclass
class IngestedItem:
    entity_id: str
    display_name: str
    source_path: str
    target_path: str
    source_system: str
    category: str
    document_type: str
    snapshot_id: str
    sha256: str
    size_bytes: int
    status: str = "ingested"
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IngestionRun:
    run_id: str
    mode: str
    started_at: str
    completed_at: str
    source: str
    target_source_root: str
    total_items: int
    ingested_items: int
    skipped_items: int
    failed_items: int
    items: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_manifest(path: Path | None) -> list[dict[str, Any]]:
    if not path:
        return []
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")
    if path.suffix.lower() == ".json":
        value = _read_json(path)
        if isinstance(value, dict):
            value = value.get("records", [])
        if not isinstance(value, list):
            raise ValueError("JSON manifest must be a list or an object with a records list")
        return [dict(item) for item in value]
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return [dict(row) for row in csv.DictReader(f)]
    raise ValueError("Manifest must be .json or .csv")


def _infer_source_system(path: Path) -> str:
    lower_parts = {p.lower() for p in path.parts}
    lower_name = path.name.lower()
    if "email" in lower_parts or "emails" in lower_parts or lower_name.endswith(".eml"):
        return "Email Archive"
    if "statement" in lower_parts or "statements" in lower_parts:
        return "Statement Engine"
    if "aml" in lower_parts or "cdd" in lower_parts or "kyc" in lower_parts:
        return "AML Platform"
    if "salesforce" in lower_parts or "crm" in lower_parts:
        return "Salesforce FSC"
    if "core" in lower_parts or "transactions" in lower_parts or "extracts" in lower_parts:
        return "Core Banking"
    return "Legacy Archive"


def _infer_document_type(path: Path) -> tuple[str, str, str]:
    name = path.name.lower().replace("-", "_").replace(" ", "_")
    parts = {p.lower() for p in path.parts}
    if "passport" in name or "identity" in name or "id_" in name:
        return "Identity", "Passport / ID", "CDD"
    if "proof_of_address" in name or "utility" in name or "address" in name:
        return "Address", "Proof of Address", "CDD"
    if "source_of_wealth" in name or "sow" in name:
        return "Due Diligence", "Source of Wealth", "CDD"
    if "source_of_funds" in name or "sof" in name:
        return "Due Diligence", "Source of Funds", "CDD"
    if "cdd" in name or "kyc" in name or "risk" in name:
        return "Due Diligence", "CDD Review", "CDD"
    if "screen" in name or "sanction" in name or "pep" in name:
        return "Due Diligence", "Screening", "CDD"
    if "edd" in name or "enhanced" in name:
        return "Due Diligence", "EDD Approval", "CDD"
    if "statement" in name or "statements" in parts:
        return "Statements", "Monthly Statement", "Statements"
    if "transaction" in name or "extract" in name or "transactions" in parts or "extracts" in parts:
        return "Transactions", "Transaction Extract", "Transactional"
    if path.suffix.lower() == ".eml" or "email" in name or "emails" in parts:
        return "Correspondence", "Email", "Correspondence"
    if "application" in name or "onboarding" in name:
        return "Onboarding", "Application", "Customer File"
    if "registry" in name or "company" in name:
        return "Corporate", "Company Registry Extract", "CDD"
    if "beneficial" in name or "ubo" in name:
        return "Corporate", "Beneficial Owner Evidence", "CDD"
    return "Document", "Business Document", "Customer File"


def _entity_id_from_folder(folder: Path) -> str:
    text = folder.name.strip()
    if text.upper().startswith("CUST-"):
        return text.upper()
    return "CUST-" + slug(text.upper(), 32)


def _normalise_entity_metadata(record: dict[str, Any], *, entity_id: str, display_name: str | None = None) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "entity_type": record.get("entity_type") or DEFAULT_ENTITY_TYPE,
        "display_name": record.get("display_name") or record.get("customer_name") or display_name or entity_id,
        "jurisdiction": record.get("jurisdiction") or DEFAULT_JURISDICTION,
        "risk_rating": record.get("risk_rating") or DEFAULT_RISK_RATING,
        "occupation": record.get("occupation") or record.get("business_activity") or "Imported customer",
        "profile": record.get("profile") or "Imported customer",
        "created_at": record.get("created_at") or utc_now_iso(),
        "source_systems": record.get("source_systems") or [],
        "ingestion_source": record.get("ingestion_source") or "bulk-import",
    }


def _ensure_entity_folder(source_root: Path, entity: dict[str, Any]) -> Path:
    entity_dir = source_root / entity["entity_id"]
    metadata_dir = entity_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    customer_path = metadata_dir / "customer.json"
    if customer_path.exists():
        existing = _read_json(customer_path)
        merged = {**existing, **{k: v for k, v in entity.items() if v not in (None, "", [])}}
        write_json(customer_path, merged)
    else:
        write_json(customer_path, entity)
    return entity_dir


def _sidecar_path(target_file: Path) -> Path:
    return Path(str(target_file) + ".eec.json")


def _write_payload_metadata(target_file: Path, metadata: dict[str, Any]) -> None:
    sidecar = _sidecar_path(target_file)
    write_json(sidecar, metadata)


def _target_subfolder(source_system: str, category: str) -> str:
    system = slug(source_system.lower().replace(" ", "_"), 48)
    cat = slug(category.lower().replace(" ", "_"), 48)
    return f"documents/{system}/{cat}"


def _copy_file(source_file: Path, target_file: Path, *, overwrite: bool) -> None:
    target_file.parent.mkdir(parents=True, exist_ok=True)
    if target_file.exists() and not overwrite:
        return
    shutil.copy2(source_file, target_file)


def _append_ingestion_event(entity_dir: Path, event: dict[str, Any]) -> None:
    log_path = entity_dir / "metadata" / "ingestion_events.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _record_for_file(source_file: Path, input_root: Path, top_folder: Path, defaults: dict[str, Any]) -> dict[str, Any]:
    entity_id = defaults.get("entity_id") or _entity_id_from_folder(top_folder)
    display_name = defaults.get("display_name") or top_folder.name.replace("_", " ").replace("-", " ").title()
    category, document_type, retention_class = _infer_document_type(source_file)
    return {
        "entity_id": entity_id,
        "display_name": display_name,
        "entity_type": defaults.get("entity_type", DEFAULT_ENTITY_TYPE),
        "jurisdiction": defaults.get("jurisdiction", DEFAULT_JURISDICTION),
        "risk_rating": defaults.get("risk_rating", DEFAULT_RISK_RATING),
        "occupation": defaults.get("occupation", "Imported customer"),
        "source_system": defaults.get("source_system") or _infer_source_system(source_file.relative_to(input_root)),
        "category": defaults.get("category") or category,
        "document_type": defaults.get("document_type") or document_type,
        "retention_class": defaults.get("retention_class") or retention_class,
        "sensitivity": defaults.get("sensitivity") or "Confidential",
        "snapshot_id": defaults.get("snapshot_id") or "BULK_IMPORT",
        "snapshot_type": defaults.get("snapshot_type") or "Bulk Historical Import",
        "captured_at": defaults.get("captured_at") or utc_now_iso(),
        "file_path": str(source_file),
        "original_relative_path": safe_rel_path(source_file.relative_to(input_root)),
    }


def discover_bulk_records(input_root: Path, *, defaults: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    input_root = Path(input_root)
    defaults = defaults or {}
    records: list[dict[str, Any]] = []
    for path in sorted(input_root.rglob("*")):
        if not path.is_file():
            continue
        if path.name.endswith(".search.txt") or path.name.endswith(".eec.json"):
            continue
        if path.suffix.lower() not in SUPPORTED_SOURCE_EXTENSIONS:
            continue
        try:
            rel = path.relative_to(input_root)
            top_folder = input_root / rel.parts[0] if len(rel.parts) > 1 else input_root
        except Exception:
            top_folder = input_root
        records.append(_record_for_file(path, input_root, top_folder, defaults))
    return records


def ingest_records(records: Iterable[dict[str, Any]], *, source_root: Path, input_root: Path | None = None, overwrite: bool = True, mode: str = "bulk") -> IngestionRun:
    source_root = Path(source_root)
    input_root = Path(input_root) if input_root else None
    started = utc_now_iso()
    run_id = f"INGEST-{started.replace(':', '').replace('-', '')}"
    items: list[dict[str, Any]] = []
    ingested = skipped = failed = 0

    for raw in records:
        try:
            source_path_value = raw.get("file_path") or raw.get("source_path") or raw.get("path")
            if not source_path_value:
                raise ValueError("Record has no file_path/source_path/path")
            source_file = Path(str(source_path_value))
            if input_root and not source_file.is_absolute():
                source_file = input_root / source_file
            source_file = source_file.expanduser().resolve()
            if not source_file.exists():
                raise FileNotFoundError(f"Source file not found: {source_file}")

            entity_id = str(raw.get("entity_id") or "").strip() or _entity_id_from_folder(source_file.parent)
            entity = _normalise_entity_metadata(raw, entity_id=entity_id, display_name=raw.get("display_name"))
            entity_dir = _ensure_entity_folder(source_root, entity)

            category = raw.get("category") or raw.get("evidence_category")
            document_type = raw.get("document_type")
            retention_class = raw.get("retention_class")
            if not category or not document_type or not retention_class:
                inferred_category, inferred_document_type, inferred_retention = _infer_document_type(source_file)
                category = category or inferred_category
                document_type = document_type or inferred_document_type
                retention_class = retention_class or inferred_retention

            source_system = raw.get("source_system") or _infer_source_system(source_file)
            snapshot_id = raw.get("snapshot_id") or ("CONTINUOUS_UPDATE" if mode == "continuous" else "BULK_IMPORT")
            snapshot_type = raw.get("snapshot_type") or ("Continuous Update" if mode == "continuous" else "Bulk Historical Import")
            target_rel = raw.get("target_relative_path")
            if target_rel:
                relative_target = Path(str(target_rel))
            else:
                relative_target = Path(_target_subfolder(str(source_system), str(category))) / source_file.name
            target_file = entity_dir / relative_target
            if target_file.exists() and not overwrite:
                status = "skipped"
                skipped += 1
            else:
                _copy_file(source_file, target_file, overwrite=overwrite)
                status = "ingested"
                ingested += 1

            sha = sha256_file(target_file)
            metadata = {
                "entity_id": entity_id,
                "category": category,
                "document_type": document_type,
                "source_system": source_system,
                "captured_at": raw.get("captured_at") or utc_now_iso(),
                "retention_class": retention_class,
                "sensitivity": raw.get("sensitivity") or "Confidential",
                "snapshot_id": snapshot_id,
                "snapshot_type": snapshot_type,
                "legal_hold_status": raw.get("legal_hold_status") or "None",
                "retention_until": raw.get("retention_until") or "",
                "deletion_eligible": raw.get("deletion_eligible") or "No",
                "source_file": str(source_file),
                "original_relative_path": raw.get("original_relative_path") or (safe_rel_path(source_file.relative_to(input_root)) if input_root and source_file.is_relative_to(input_root) else source_file.name),
                "ingestion_run_id": run_id,
                "ingested_at": utc_now_iso(),
                "sha256": sha,
            }
            _write_payload_metadata(target_file, metadata)
            _append_ingestion_event(entity_dir, {"event_type": "DOCUMENT_INGESTED", **metadata})

            items.append(IngestedItem(
                entity_id=entity_id,
                display_name=entity.get("display_name", entity_id),
                source_path=str(source_file),
                target_path=str(target_file),
                source_system=str(source_system),
                category=str(category),
                document_type=str(document_type),
                snapshot_id=str(snapshot_id),
                sha256=sha,
                size_bytes=target_file.stat().st_size,
                status=status,
            ).to_dict())
        except Exception as exc:
            failed += 1
            items.append({"status": "failed", "message": str(exc), "record": raw})

    completed = utc_now_iso()
    return IngestionRun(
        run_id=run_id,
        mode=mode,
        started_at=started,
        completed_at=completed,
        source=str(input_root or "event-stream"),
        target_source_root=str(source_root),
        total_items=len(items),
        ingested_items=ingested,
        skipped_items=skipped,
        failed_items=failed,
        items=items,
    )


def bulk_ingest(input_root: Path, source_root: Path, *, manifest: Path | None = None, defaults: dict[str, Any] | None = None, overwrite: bool = True) -> IngestionRun:
    input_root = Path(input_root)
    manifest_records = _load_manifest(manifest)
    records = manifest_records or discover_bulk_records(input_root, defaults=defaults)
    return ingest_records(records, source_root=source_root, input_root=input_root, overwrite=overwrite, mode="bulk")


def ingest_event(event: dict[str, Any], *, source_root: Path, overwrite: bool = True) -> IngestionRun:
    record = dict(event)
    if "payload" in record and "file_path" not in record:
        raise NotImplementedError("Inline payload ingestion is not enabled in this POC. Use file_path.")
    return ingest_records([record], source_root=source_root, input_root=None, overwrite=overwrite, mode="continuous")


def process_event_queue(queue_dir: Path, source_root: Path, *, processed_dir: Path | None = None, failed_dir: Path | None = None, overwrite: bool = True) -> IngestionRun:
    queue_dir = Path(queue_dir)
    processed_dir = Path(processed_dir) if processed_dir else queue_dir.parent / "processed"
    failed_dir = Path(failed_dir) if failed_dir else queue_dir.parent / "failed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)
    started = utc_now_iso()
    run_id = f"EVENTQ-{started.replace(':', '').replace('-', '')}"
    combined_items: list[dict[str, Any]] = []
    ingested = skipped = failed = 0

    for event_file in sorted(queue_dir.glob("*.json")):
        try:
            event = _read_json(event_file)
            result = ingest_event(event, source_root=source_root, overwrite=overwrite)
            combined_items.extend(result.items)
            ingested += result.ingested_items
            skipped += result.skipped_items
            failed += result.failed_items
            shutil.move(str(event_file), str(processed_dir / event_file.name))
        except Exception as exc:
            failed += 1
            combined_items.append({"status": "failed", "event_file": str(event_file), "message": str(exc)})
            shutil.move(str(event_file), str(failed_dir / event_file.name))

    completed = utc_now_iso()
    return IngestionRun(
        run_id=run_id,
        mode="continuous-queue",
        started_at=started,
        completed_at=completed,
        source=str(queue_dir),
        target_source_root=str(source_root),
        total_items=len(combined_items),
        ingested_items=ingested,
        skipped_items=skipped,
        failed_items=failed,
        items=combined_items,
    )


def write_ingestion_report(report: IngestionRun, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(output_path, report.to_dict())
    return output_path
