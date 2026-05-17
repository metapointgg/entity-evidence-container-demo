from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from astropy.io import fits

from .container_reader import read_entity, read_manifest, read_provenance, read_snapshots
from .fits_direct_search import direct_search_container, direct_search_entity
from .query_interpreter import execute_structured_query, interpret_archive_query as _interpret_archive_query
from .rulesets import evaluate_completeness, load_rulesets
from .search import advanced_search_index
from .ui_data import (
    get_archive_summary,
    get_entity_by_id,
    list_container_paths,
    list_entities as _index_list_entities,
    list_objects_for_entity,
)


_SOURCE_OF_TRUTH_NOTE = (
    "TrustVault FITS containers remain the durable source of truth. "
    "SQLite, FTS and vector indexes are disposable acceleration layers and should be rebuilt from FITS when stale."
)


@dataclass(frozen=True)
class TrustVaultMcpConfig:
    """Runtime configuration for the TrustVault MCP tool layer.

    The MCP server deliberately avoids accepting arbitrary paths from clients.
    All archive locations are supplied by environment variables and then used
    internally by controlled query functions.
    """

    root: Path
    source_dir: Path
    containers_dir: Path
    index_path: Path
    vector_path: Path
    lmstudio_vector_path: Path
    exports_dir: Path
    read_only: bool = True
    enable_export: bool = False
    enable_payload_read: bool = False
    max_results: int = 25

    @classmethod
    def from_env(cls) -> "TrustVaultMcpConfig":
        root = Path(os.getenv("TRUSTVAULT_ROOT", "data"))
        max_results_raw = os.getenv("TRUSTVAULT_MCP_MAX_RESULTS", "25")
        try:
            max_results = max(1, int(max_results_raw))
        except ValueError:
            max_results = 25

        return cls(
            root=root,
            source_dir=Path(os.getenv("TRUSTVAULT_SOURCE_DIR", str(root / "source"))),
            containers_dir=Path(os.getenv("TRUSTVAULT_CONTAINERS_DIR", str(root / "containers"))),
            index_path=Path(os.getenv("TRUSTVAULT_INDEX_PATH", str(root / "index" / "evidence_index.db"))),
            vector_path=Path(os.getenv("TRUSTVAULT_VECTOR_PATH", str(root / "index" / "evidence_vector.pkl"))),
            lmstudio_vector_path=Path(
                os.getenv("TRUSTVAULT_LMSTUDIO_VECTOR_PATH", str(root / "index" / "evidence_lmstudio_vector.pkl"))
            ),
            exports_dir=Path(os.getenv("TRUSTVAULT_EXPORTS_DIR", str(root / "exports"))),
            read_only=_env_bool("TRUSTVAULT_MCP_READ_ONLY", default=True),
            enable_export=_env_bool("TRUSTVAULT_MCP_ENABLE_EXPORT", default=False),
            enable_payload_read=_env_bool("TRUSTVAULT_MCP_ENABLE_PAYLOAD_READ", default=False),
            max_results=max_results,
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "source_dir": str(self.source_dir),
            "containers_dir": str(self.containers_dir),
            "index_path": str(self.index_path),
            "vector_path": str(self.vector_path),
            "lmstudio_vector_path": str(self.lmstudio_vector_path),
            "exports_dir": str(self.exports_dir),
            "read_only": self.read_only,
            "export_enabled": self.enable_export,
            "payload_binary_read_enabled": self.enable_payload_read,
            "max_results": self.max_results,
        }


def _env_bool(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _cfg(config: TrustVaultMcpConfig | None = None) -> TrustVaultMcpConfig:
    return config or TrustVaultMcpConfig.from_env()


def _safe_limit(limit: int | None, config: TrustVaultMcpConfig) -> int:
    if limit is None:
        return config.max_results
    try:
        requested = int(limit)
    except (TypeError, ValueError):
        requested = config.max_results
    return max(1, min(requested, config.max_results))


def _now_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _safe_name(value: str | None, fallback: str = "trustvault_export") -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("._")
    return clean or fallback


def _validate_identifier(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", text):
        raise ValueError(f"{field_name} contains unsupported characters")
    return text


def _path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _short_preview(text: Any, max_chars: int = 1200) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(clean) <= max_chars:
        return clean
    return clean[:max_chars].rstrip() + "..."


def _format_bytes(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _infer_entity_type(entity: dict[str, Any]) -> str:
    explicit = entity.get("entity_type") or entity.get("customer_type")
    if explicit:
        return str(explicit)
    text = " ".join(str(entity.get(key, "")) for key in ["display_name", "occupation"]).lower()
    corporate_markers = [" ltd", " limited", " llc", " plc", " holdings", " company", " corporate"]
    return "Corporate" if any(marker in text for marker in corporate_markers) else "Individual"


def _entity_container_paths(config: TrustVaultMcpConfig, entity_id: str) -> list[Path]:
    entity_id = _validate_identifier(entity_id, "entity_id")
    containers_dir = config.containers_dir
    exact = containers_dir / f"{entity_id}.fits"
    paths: list[Path] = []
    if exact.exists() and exact.is_file():
        paths.append(exact)

    for candidate in sorted(containers_dir.glob(f"{entity_id}*.fits")):
        if candidate.is_file() and candidate not in paths and _path_within(candidate, containers_dir):
            paths.append(candidate)
    return paths


def _read_entity_from_fits(config: TrustVaultMcpConfig, entity_id: str) -> dict[str, Any] | None:
    for container in _entity_container_paths(config, entity_id):
        try:
            return read_entity(container)
        except Exception:
            continue
    return None


def _scan_entities_from_fits(config: TrustVaultMcpConfig, limit: int) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for container in list_container_paths(config.containers_dir):
        try:
            entity = read_entity(container)
            manifest = read_manifest(container)
        except Exception:
            continue
        entity_id = str(entity.get("entity_id") or container.stem)
        row = rows.setdefault(
            entity_id,
            {
                "entity_id": entity_id,
                "display_name": entity.get("display_name"),
                "entity_type": _infer_entity_type(entity),
                "jurisdiction": entity.get("jurisdiction"),
                "risk_rating": entity.get("risk_rating"),
                "object_count": 0,
                "payload_size_bytes": 0,
                "container_count": 0,
                "container_names": [],
            },
        )
        row["object_count"] += len(manifest)
        row["payload_size_bytes"] += sum(_format_bytes(item.get("size_bytes")) for item in manifest)
        row["container_count"] += 1
        row["container_names"].append(container.name)
    return sorted(rows.values(), key=lambda item: str(item.get("entity_id")))[:limit]


def _filter_entity_rows(
    rows: Iterable[dict[str, Any]],
    *,
    jurisdiction: str | None = None,
    risk_rating: str | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if jurisdiction and row.get("jurisdiction") != jurisdiction:
            continue
        if risk_rating and row.get("risk_rating") != risk_rating:
            continue
        out.append(row)
    return out


def _public_entity_row(row: dict[str, Any]) -> dict[str, Any]:
    payload_size = row.get("payload_size_bytes", row.get("payload_bytes"))
    return {
        "entity_id": row.get("entity_id"),
        "display_name": row.get("display_name"),
        "entity_type": row.get("entity_type") or _infer_entity_type(row),
        "jurisdiction": row.get("jurisdiction"),
        "risk_rating": row.get("risk_rating"),
        "object_count": row.get("object_count", row.get("evidence_count", 0)),
        "payload_size_bytes": _format_bytes(payload_size),
    }


def _public_evidence_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_id": row.get("entity_id"),
        "display_name": row.get("display_name"),
        "object_id": row.get("object_id"),
        "filename": row.get("filename"),
        "document_type": row.get("document_type"),
        "category": row.get("category"),
        "snapshot_id": row.get("snapshot_id"),
        "source_system": row.get("source_system"),
        "captured_at": row.get("captured_at"),
        "snippet": _short_preview(row.get("snippet") or row.get("search_text") or row.get("ocr_text"), 700),
        "sha256": row.get("sha256"),
        "container_path": row.get("container_path"),
        "container_name": Path(str(row.get("container_path"))).name if row.get("container_path") else row.get("container_id"),
    }


def _evidence_filters(
    *,
    jurisdiction: str | None = None,
    risk_rating: str | None = None,
    document_type: str | None = None,
    category: str | None = None,
    snapshot_id: str | None = None,
    source_system: str | None = None,
) -> dict[str, list[str]]:
    filters = {
        "jurisdiction": jurisdiction,
        "risk_rating": risk_rating,
        "document_type": document_type,
        "category": category,
        "snapshot_id": snapshot_id,
        "source_system": source_system,
    }
    return {key: [value] for key, value in filters.items() if value}


def _index_counts(index_path: Path) -> dict[str, Any]:
    if not index_path.exists():
        return {
            "index_exists": False,
            "entity_count": 0,
            "indexed_object_count": 0,
        }
    conn = sqlite3.connect(index_path)
    try:
        entity_count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        object_count = conn.execute("SELECT COUNT(*) FROM objects").fetchone()[0]
        return {
            "index_exists": True,
            "entity_count": entity_count,
            "indexed_object_count": object_count,
        }
    except sqlite3.Error as exc:
        return {
            "index_exists": True,
            "entity_count": 0,
            "indexed_object_count": 0,
            "index_error": str(exc),
        }
    finally:
        conn.close()


def archive_status(config: TrustVaultMcpConfig | None = None) -> dict[str, Any]:
    """Return configured archive paths and high-level TrustVault archive status."""

    config = _cfg(config)
    container_count = len(list_container_paths(config.containers_dir)) if config.containers_dir.exists() else 0
    container_bytes = sum(path.stat().st_size for path in list_container_paths(config.containers_dir)) if config.containers_dir.exists() else 0
    counts = _index_counts(config.index_path)
    return {
        "product": "TrustVault",
        "source_of_truth_note": _SOURCE_OF_TRUTH_NOTE,
        "configuration": config.to_public_dict(),
        "paths": {
            "source_folder": str(config.source_dir),
            "containers_folder": str(config.containers_dir),
            "index_path": str(config.index_path),
            "vector_path": str(config.vector_path),
            "lmstudio_vector_path": str(config.lmstudio_vector_path),
            "exports_dir": str(config.exports_dir),
        },
        "exists": {
            "source_folder": config.source_dir.exists(),
            "containers_folder": config.containers_dir.exists(),
            "index": config.index_path.exists(),
            "vector": config.vector_path.exists(),
            "lmstudio_vector": config.lmstudio_vector_path.exists(),
            "exports_folder": config.exports_dir.exists(),
        },
        "entity_count": counts.get("entity_count", 0),
        "container_count": container_count,
        "indexed_object_count": counts.get("indexed_object_count", 0),
        "total_container_bytes": container_bytes,
        "status": counts,
    }


def list_entities(
    jurisdiction: str | None = None,
    risk_rating: str | None = None,
    limit: int | None = None,
    config: TrustVaultMcpConfig | None = None,
) -> dict[str, Any]:
    """List customer/entity records from the rebuilt index, falling back to FITS metadata."""

    config = _cfg(config)
    safe_limit = _safe_limit(limit, config)
    source = "index"
    if config.index_path.exists():
        rows = _index_list_entities(config.index_path)
    else:
        rows = _scan_entities_from_fits(config, safe_limit)
        source = "fits"

    rows = _filter_entity_rows(rows, jurisdiction=jurisdiction, risk_rating=risk_rating)
    rows = [_public_entity_row(row) for row in rows[:safe_limit]]
    return {
        "source": source,
        "source_of_truth_note": _SOURCE_OF_TRUTH_NOTE,
        "count": len(rows),
        "rows": rows,
    }


def get_entity_summary(entity_id: str, config: TrustVaultMcpConfig | None = None) -> dict[str, Any]:
    """Return a controlled summary for a single TrustVault entity."""

    config = _cfg(config)
    entity_id = _validate_identifier(entity_id, "entity_id")
    containers = _entity_container_paths(config, entity_id)

    entity = get_entity_by_id(config.index_path, entity_id) if config.index_path.exists() else None
    if not entity:
        entity = _read_entity_from_fits(config, entity_id)

    if not entity:
        return {
            "entity_id": entity_id,
            "found": False,
            "source_of_truth_note": _SOURCE_OF_TRUTH_NOTE,
            "message": "Entity was not found in the configured index or FITS containers.",
        }

    if config.index_path.exists():
        evidence_rows = list_objects_for_entity(config.index_path, entity_id)
    else:
        evidence_rows = []
        for container in containers:
            try:
                evidence_rows.extend({**item, "container_path": str(container)} for item in read_manifest(container))
            except Exception:
                continue

    category_counts = Counter(str(row.get("category") or "Uncategorised") for row in evidence_rows)
    document_type_counts = Counter(str(row.get("document_type") or "Unclassified") for row in evidence_rows)
    snapshot_counts = Counter(str(row.get("snapshot_id") or "Unknown") for row in evidence_rows)
    source_systems = Counter(str(row.get("source_system") or "Unknown") for row in evidence_rows)
    legal_hold_rows = [
        row
        for row in evidence_rows
        if str(row.get("legal_hold_status") or "").lower() not in {"", "none", "not on hold", "false"}
    ]
    retention_classes = Counter(str(row.get("retention_class") or "Unclassified") for row in evidence_rows)

    completeness: dict[str, Any] | None = None
    if config.index_path.exists():
        try:
            report = evaluate_completeness(config.index_path, root=config.root, entity_id=entity_id)
            if report.get("rows"):
                row = report["rows"][0]
                completeness = {
                    "ruleset_id": row.get("ruleset_id"),
                    "ruleset_name": row.get("ruleset_name"),
                    "profile": row.get("profile"),
                    "complete": row.get("complete"),
                    "present_count": row.get("present_count"),
                    "missing_count": row.get("missing_count"),
                    "missing_evidence": row.get("missing_evidence", []),
                }
        except Exception as exc:
            completeness = {"available": False, "error": str(exc)}

    return {
        "found": True,
        "source_of_truth_note": _SOURCE_OF_TRUTH_NOTE,
        "entity": {
            **entity,
            "entity_type": entity.get("entity_type") or _infer_entity_type(entity),
        },
        "fits_containers": [
            {"name": path.name, "path": str(path), "size_bytes": path.stat().st_size}
            for path in containers
        ],
        "evidence_counts": {
            "total": len(evidence_rows),
            "by_category": dict(sorted(category_counts.items())),
            "by_document_type": dict(sorted(document_type_counts.items())),
            "by_snapshot": dict(sorted(snapshot_counts.items())),
        },
        "available_source_systems": dict(sorted(source_systems.items())),
        "retention_legal_hold_summary": {
            "retention_class_counts": dict(sorted(retention_classes.items())),
            "legal_hold_count": len(legal_hold_rows),
            "legal_hold_object_ids": [row.get("object_id") for row in legal_hold_rows[:20]],
        },
        "completeness_status": completeness,
    }


def search_entity_fits(
    entity_id: str,
    query: str,
    limit: int | None = None,
    document_type: str | None = None,
    category: str | None = None,
    snapshot_id: str | None = None,
    config: TrustVaultMcpConfig | None = None,
) -> dict[str, Any]:
    """Search one entity's FITS container(s) directly without using SQLite."""

    config = _cfg(config)
    entity_id = _validate_identifier(entity_id, "entity_id")
    safe_limit = _safe_limit(limit, config)
    filters = _evidence_filters(document_type=document_type, category=category, snapshot_id=snapshot_id)
    containers = _entity_container_paths(config, entity_id)

    rows: list[dict[str, Any]] = []
    for container in containers:
        rows.extend(direct_search_container(container, query, filters=filters, limit=safe_limit))
    rows.sort(key=lambda row: float(row.get("direct_fits_score") or 0), reverse=True)
    public_rows = [_public_evidence_row(row) for row in rows[:safe_limit]]

    return {
        "source": "direct_fits",
        "source_note": "Selected-entity search was executed directly against configured FITS containers.",
        "source_of_truth_note": _SOURCE_OF_TRUTH_NOTE,
        "entity_id": entity_id,
        "query": query,
        "count": len(public_rows),
        "rows": public_rows,
    }


def search_archive(
    query: str,
    jurisdiction: str | None = None,
    risk_rating: str | None = None,
    document_type: str | None = None,
    category: str | None = None,
    snapshot_id: str | None = None,
    source_system: str | None = None,
    limit: int | None = None,
    config: TrustVaultMcpConfig | None = None,
) -> dict[str, Any]:
    """Search across the TrustVault archive using the rebuilt index."""

    config = _cfg(config)
    safe_limit = _safe_limit(limit, config)
    if not config.index_path.exists():
        return {
            "source": "index",
            "source_of_truth_note": _SOURCE_OF_TRUTH_NOTE,
            "query": query,
            "count": 0,
            "rows": [],
            "grouped": {},
            "message": "The configured SQLite/FTS index does not exist. Rebuild the index from FITS before running cross-archive searches.",
        }

    filters = _evidence_filters(
        jurisdiction=jurisdiction,
        risk_rating=risk_rating,
        document_type=document_type,
        category=category,
        snapshot_id=snapshot_id,
        source_system=source_system,
    )

    try:
        rows = advanced_search_index(config.index_path, query=query, filters=filters, limit=safe_limit, mode="semantic")
        if not rows:
            rows = advanced_search_index(config.index_path, query=query, filters=filters, limit=safe_limit, mode="keyword")
    except Exception as exc:
        return {
            "source": "index",
            "source_of_truth_note": _SOURCE_OF_TRUTH_NOTE,
            "query": query,
            "count": 0,
            "rows": [],
            "grouped": {},
            "error": str(exc),
        }

    public_rows = [_public_evidence_row(row) for row in rows[:safe_limit]]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in public_rows:
        grouped[str(row.get("entity_id"))].append(row)

    return {
        "source": "index",
        "source_note": "Cross-customer search used the rebuilt SQLite/FTS index for performance.",
        "source_of_truth_note": _SOURCE_OF_TRUTH_NOTE,
        "query": query,
        "filters": filters,
        "count": len(public_rows),
        "rows": public_rows,
        "grouped": dict(grouped),
    }


def interpret_query(
    query: str,
    selected_entity_id: str | None = None,
    use_local_ai: bool = False,
    limit: int | None = None,
    config: TrustVaultMcpConfig | None = None,
) -> dict[str, Any]:
    """Convert a natural-language archive request into StructuredArchiveQuery JSON."""

    config = _cfg(config)
    safe_limit = _safe_limit(limit, config)
    structured = _interpret_archive_query(
        query,
        selected_entity_id=selected_entity_id,
        use_local_ai=bool(use_local_ai),
        limit=safe_limit,
    )
    return {
        "source_of_truth_note": _SOURCE_OF_TRUTH_NOTE,
        "structured_query": structured.to_dict(),
        "normalisation_notes": [
            "Onboarding/account-opening terms are normalised to snapshot_id='ONBOARDING', not document_type='ONBOARDING'.",
            "MCP defaults use_local_ai to false to avoid recursive local model calls unless explicitly requested.",
        ],
    }


def execute_query(
    query: str,
    selected_entity_id: str | None = None,
    use_local_ai: bool = False,
    limit: int | None = None,
    config: TrustVaultMcpConfig | None = None,
) -> dict[str, Any]:
    """Interpret and execute a natural-language TrustVault archive query."""

    config = _cfg(config)
    safe_limit = _safe_limit(limit, config)
    structured = _interpret_archive_query(
        query,
        selected_entity_id=selected_entity_id,
        use_local_ai=bool(use_local_ai),
        limit=safe_limit,
    )

    selected = selected_entity_id or structured.entity_id
    if selected and structured.requires_evidence and structured.result_type == "evidence":
        rows = direct_search_entity(
            config.containers_dir,
            selected,
            structured.semantic_query or structured.raw_query,
            structured=structured,
            limit=safe_limit,
        )
        return {
            "result_type": "evidence",
            "rows": [_public_evidence_row(row) for row in rows],
            "grouped": None,
            "structured_query_used": structured.to_dict(),
            "source_note": "Selected-customer evidence query used direct FITS search.",
            "source_of_truth_note": _SOURCE_OF_TRUTH_NOTE,
        }

    if not config.index_path.exists():
        return {
            "result_type": structured.result_type,
            "rows": [],
            "grouped": None,
            "structured_query_used": structured.to_dict(),
            "source_note": "Index search was required for this cross-customer/cohort query, but the configured index was not found.",
            "source_of_truth_note": _SOURCE_OF_TRUTH_NOTE,
        }

    result = execute_structured_query(config.index_path, structured)
    rows = result.get("rows") or []
    public_rows = [_public_evidence_row(row) if row.get("object_id") else row for row in rows]
    grouped = result.get("grouped")
    if grouped:
        grouped = {
            entity_id: [_public_evidence_row(row) if row.get("object_id") else row for row in entity_rows]
            for entity_id, entity_rows in grouped.items()
        }

    return {
        "result_type": result.get("type", structured.result_type),
        "rows": public_rows,
        "grouped": grouped,
        "summary": result.get("summary"),
        "ruleset": result.get("ruleset"),
        "structured_query_used": structured.to_dict(),
        "source_note": "Cross-customer/cohort query used the rebuilt index. Rebuild the index from FITS if results appear stale.",
        "source_of_truth_note": _SOURCE_OF_TRUTH_NOTE,
    }


def check_completeness(
    entity_id: str | None = None,
    jurisdiction: str | None = None,
    risk_rating: str | None = None,
    missing_only: bool | None = None,
    ruleset_id: str | None = None,
    config: TrustVaultMcpConfig | None = None,
) -> dict[str, Any]:
    """Check evidence completeness for one or more customers."""

    config = _cfg(config)
    if not config.index_path.exists():
        return {
            "source_of_truth_note": _SOURCE_OF_TRUTH_NOTE,
            "summary": {},
            "rows": [],
            "ruleset": {},
            "message": "Completeness checks require the rebuilt index. Rebuild the index from FITS first.",
        }

    report = evaluate_completeness(
        config.index_path,
        root=config.root,
        ruleset_id=ruleset_id,
        entity_id=entity_id,
        jurisdiction=jurisdiction,
        risk_rating=risk_rating,
    )
    rows = report.get("rows", [])
    if missing_only:
        rows = [row for row in rows if not row.get("complete")]
    summary = dict(report.get("summary", {}))
    summary["customers_returned"] = len(rows)
    return {
        "source_of_truth_note": _SOURCE_OF_TRUTH_NOTE,
        "summary": summary,
        "rows": rows,
        "ruleset": report.get("ruleset", {}),
    }


def get_evidence_payload_metadata(
    entity_id: str,
    object_id: str,
    config: TrustVaultMcpConfig | None = None,
) -> dict[str, Any]:
    """Return metadata and safe preview text for a specific evidence object.

    This function does not return full binary payload content. Binary payload reads
    remain disabled by default and are intentionally not exposed as an MCP tool.
    """

    config = _cfg(config)
    entity_id = _validate_identifier(entity_id, "entity_id")
    object_id = _validate_identifier(object_id, "object_id")

    for container in _entity_container_paths(config, entity_id):
        try:
            entity = read_entity(container)
            manifest = read_manifest(container)
        except Exception:
            continue
        item = next((entry for entry in manifest if str(entry.get("object_id")) == object_id), None)
        if not item:
            continue
        preview_text = item.get("search_text") or item.get("ocr_text") or ""
        return {
            "found": True,
            "source_of_truth_note": _SOURCE_OF_TRUTH_NOTE,
            "entity": {
                "entity_id": entity.get("entity_id"),
                "display_name": entity.get("display_name"),
                "jurisdiction": entity.get("jurisdiction"),
                "risk_rating": entity.get("risk_rating"),
            },
            "container": {
                "name": container.name,
                "path": str(container),
            },
            "payload_binary_read_enabled": config.enable_payload_read,
            "payload_binary_returned": False,
            "metadata": item,
            "filename": item.get("filename"),
            "document_type": item.get("document_type"),
            "category": item.get("category"),
            "source_system": item.get("source_system"),
            "retention_metadata": {
                "retention_class": item.get("retention_class"),
                "retention_until": item.get("retention_until"),
                "deletion_eligible": item.get("deletion_eligible"),
            },
            "legal_hold_status": item.get("legal_hold_status"),
            "sha256": item.get("sha256"),
            "size": item.get("size_bytes"),
            "mime_type": item.get("mime_type"),
            "safe_preview_text": _short_preview(preview_text),
        }

    return {
        "found": False,
        "source_of_truth_note": _SOURCE_OF_TRUTH_NOTE,
        "entity_id": entity_id,
        "object_id": object_id,
        "message": "Evidence object was not found in the configured FITS containers.",
    }


def _rows_for_object_ids(
    config: TrustVaultMcpConfig,
    object_ids: Sequence[str],
    entity_id: str | None = None,
) -> list[dict[str, Any]]:
    safe_object_ids = [_validate_identifier(object_id, "object_id") for object_id in object_ids]
    if not safe_object_ids:
        return []

    rows: list[dict[str, Any]] = []
    if config.index_path.exists():
        placeholders = ",".join("?" for _ in safe_object_ids)
        params: list[Any] = list(safe_object_ids)
        entity_clause = ""
        if entity_id:
            entity_clause = " AND o.entity_id = ?"
            params.append(entity_id)
        conn = sqlite3.connect(config.index_path)
        conn.row_factory = sqlite3.Row
        try:
            sql = f"""
                SELECT o.*, e.display_name, e.jurisdiction, e.risk_rating
                FROM objects o
                JOIN entities e ON e.entity_id = o.entity_id
                WHERE o.object_id IN ({placeholders}){entity_clause}
                ORDER BY o.entity_id, o.snapshot_id, o.filename
            """
            rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()
        if rows:
            return rows

    # FITS fallback
    candidate_entities = [entity_id] if entity_id else [row["entity_id"] for row in _scan_entities_from_fits(config, config.max_results * 100)]
    wanted = set(safe_object_ids)
    for candidate_entity_id in candidate_entities:
        if not candidate_entity_id:
            continue
        for container in _entity_container_paths(config, str(candidate_entity_id)):
            try:
                entity = read_entity(container)
                manifest = read_manifest(container)
            except Exception:
                continue
            for item in manifest:
                if item.get("object_id") in wanted:
                    rows.append(
                        {
                            **item,
                            "entity_id": entity.get("entity_id"),
                            "display_name": entity.get("display_name"),
                            "jurisdiction": entity.get("jurisdiction"),
                            "risk_rating": entity.get("risk_rating"),
                            "container_path": str(container),
                        }
                    )
    return rows


def _rows_for_entity(config: TrustVaultMcpConfig, entity_id: str) -> list[dict[str, Any]]:
    entity_id = _validate_identifier(entity_id, "entity_id")
    if config.index_path.exists():
        return list_objects_for_entity(config.index_path, entity_id)

    rows: list[dict[str, Any]] = []
    for container in _entity_container_paths(config, entity_id):
        try:
            entity = read_entity(container)
            manifest = read_manifest(container)
        except Exception:
            continue
        rows.extend(
            {
                **item,
                "entity_id": entity.get("entity_id"),
                "display_name": entity.get("display_name"),
                "jurisdiction": entity.get("jurisdiction"),
                "risk_rating": entity.get("risk_rating"),
                "container_path": str(container),
            }
            for item in manifest
        )
    return rows


def _container_path_for_row(config: TrustVaultMcpConfig, row: dict[str, Any]) -> Path | None:
    raw = row.get("container_path")
    if raw:
        path = Path(str(raw))
        if path.exists() and _path_within(path, config.containers_dir):
            return path
    entity_id = row.get("entity_id")
    object_id = row.get("object_id")
    if not entity_id or not object_id:
        return None
    for candidate in _entity_container_paths(config, str(entity_id)):
        try:
            if any(item.get("object_id") == object_id for item in read_manifest(candidate)):
                return candidate
        except Exception:
            continue
    return None


def _materialise_selected_export(config: TrustVaultMcpConfig, rows: list[dict[str, Any]], output_name: str | None) -> dict[str, Any]:
    export_name = _safe_name(output_name, f"trustvault_mcp_export_{_now_id()}")
    export_dir = config.exports_dir / export_name
    if not _path_within(export_dir, config.exports_dir):
        raise ValueError("Resolved export path is outside TRUSTVAULT_EXPORTS_DIR")

    export_dir.mkdir(parents=True, exist_ok=True)
    files_dir = export_dir / "files"
    files_dir.mkdir(exist_ok=True)

    exported_manifest: list[dict[str, Any]] = []
    hash_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    seen: set[tuple[str, str]] = set()
    for row in rows:
        entity_id = str(row.get("entity_id") or "UNKNOWN")
        object_id = str(row.get("object_id") or "")
        if not object_id or (entity_id, object_id) in seen:
            continue
        seen.add((entity_id, object_id))

        container = _container_path_for_row(config, row)
        if not container:
            failures.append({"entity_id": entity_id, "object_id": object_id, "reason": "Container could not be resolved"})
            continue

        try:
            manifest = read_manifest(container)
            item = next((entry for entry in manifest if str(entry.get("object_id")) == object_id), None)
            if not item:
                failures.append({"entity_id": entity_id, "object_id": object_id, "container": str(container), "reason": "Object not in manifest"})
                continue
            with fits.open(container, memmap=True) as hdul:
                data = bytes(hdul[item["hdu_name"]].data.tolist())
        except Exception as exc:
            failures.append({"entity_id": entity_id, "object_id": object_id, "container": str(container), "reason": str(exc)})
            continue

        snapshot = _safe_name(str(item.get("snapshot_id") or container.stem), "snapshot")
        filename = _safe_name(str(item.get("filename") or f"{object_id}.bin"), f"{object_id}.bin")
        output_rel = Path("files") / _safe_name(entity_id, "entity") / snapshot / f"{_safe_name(object_id, 'object')}_{filename}"
        output_path = export_dir / output_rel
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(data)

        exported_hash = hashlib.sha256(data).hexdigest()
        expected_hash = item.get("sha256")
        hash_rows.append(
            {
                "entity_id": entity_id,
                "object_id": object_id,
                "filename": item.get("filename"),
                "exported_path": str(output_rel),
                "exported_sha256": exported_hash,
                "manifest_sha256": expected_hash,
                "match": bool(expected_hash and exported_hash == expected_hash),
            }
        )
        exported_manifest.append(
            {
                **item,
                "entity_id": entity_id,
                "display_name": row.get("display_name"),
                "container_path": str(container),
                "container_name": container.name,
                "exported_path": str(output_rel),
            }
        )

    hash_report = {
        "status": "PASS" if hash_rows and all(row["match"] for row in hash_rows) and not failures else "FAIL",
        "total_files": len(hash_rows),
        "matched": sum(1 for row in hash_rows if row["match"]),
        "mismatched": sum(1 for row in hash_rows if not row["match"]),
        "failures": failures,
        "rows": hash_rows,
    }

    _write_json(export_dir / "MANIFEST.json", exported_manifest)
    _write_json(export_dir / "HASH_REPORT.json", hash_report)
    _write_json(
        export_dir / "QUERY.json",
        {
            "pack_type": "mcp_selected_evidence",
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "source_of_truth_note": _SOURCE_OF_TRUTH_NOTE,
        },
    )

    summary_lines = [
        "# TrustVault MCP Evidence Pack",
        "",
        _SOURCE_OF_TRUTH_NOTE,
        "",
        f"- Exported objects: {len(exported_manifest)}",
        f"- Hash report status: {hash_report['status']}",
        "",
        "| Entity | Object ID | Document Type | File | SHA-256 check |",
        "|---|---|---|---|---|",
    ]
    for item, hash_row in zip(exported_manifest, hash_rows):
        summary_lines.append(
            f"| {item.get('entity_id')} | {item.get('object_id')} | {item.get('document_type')} | "
            f"{item.get('filename')} | {'PASS' if hash_row.get('match') else 'FAIL'} |"
        )
    (export_dir / "EVIDENCE_PACK_SUMMARY.md").write_text("\n".join(summary_lines), encoding="utf-8")

    return {
        "export_path": str(export_dir),
        "manifest_summary": {
            "object_count": len(exported_manifest),
            "failure_count": len(failures),
            "hash_status": hash_report["status"],
        },
        "hash_report_path": str(export_dir / "HASH_REPORT.json"),
    }


def export_evidence_pack(
    query: str | None = None,
    entity_id: str | None = None,
    object_ids: Sequence[str] | None = None,
    output_name: str | None = None,
    config: TrustVaultMcpConfig | None = None,
) -> dict[str, Any]:
    """Export an evidence pack from selected object IDs or current query results.

    Disabled by default. To enable, set:
    - TRUSTVAULT_MCP_READ_ONLY=false
    - TRUSTVAULT_MCP_ENABLE_EXPORT=true
    """

    config = _cfg(config)
    if config.read_only or not config.enable_export:
        return {
            "enabled": False,
            "status": "disabled",
            "source_of_truth_note": _SOURCE_OF_TRUTH_NOTE,
            "message": (
                "Evidence pack export is disabled. Set TRUSTVAULT_MCP_READ_ONLY=false and "
                "TRUSTVAULT_MCP_ENABLE_EXPORT=true to allow MCP-triggered exports."
            ),
        }

    rows: list[dict[str, Any]]
    if object_ids:
        rows = _rows_for_object_ids(config, list(object_ids), entity_id=entity_id)
    elif query:
        if entity_id:
            search_result = search_entity_fits(entity_id, query, limit=config.max_results, config=config)
            object_ids_from_query = [row["object_id"] for row in search_result.get("rows", []) if row.get("object_id")]
            rows = _rows_for_object_ids(config, object_ids_from_query, entity_id=entity_id)
        else:
            search_result = search_archive(query, limit=config.max_results, config=config)
            object_ids_from_query = [row["object_id"] for row in search_result.get("rows", []) if row.get("object_id")]
            rows = _rows_for_object_ids(config, object_ids_from_query)
    elif entity_id:
        rows = _rows_for_entity(config, entity_id)
    else:
        return {
            "enabled": True,
            "status": "error",
            "source_of_truth_note": _SOURCE_OF_TRUTH_NOTE,
            "message": "Provide query, entity_id or object_ids to define the evidence pack scope.",
        }

    if not rows:
        return {
            "enabled": True,
            "status": "empty",
            "source_of_truth_note": _SOURCE_OF_TRUTH_NOTE,
            "message": "No evidence rows matched the requested export scope.",
        }

    result = _materialise_selected_export(config, rows[: config.max_results], output_name)
    return {
        "enabled": True,
        "status": "created",
        "source_of_truth_note": _SOURCE_OF_TRUTH_NOTE,
        **result,
    }


def list_rulesets(config: TrustVaultMcpConfig | None = None) -> dict[str, Any]:
    """Return configured completeness rulesets as a controlled MCP resource."""

    config = _cfg(config)
    rulesets = [ruleset.to_dict() for ruleset in load_rulesets(config.root)]
    return {
        "source_of_truth_note": _SOURCE_OF_TRUTH_NOTE,
        "rulesets": rulesets,
    }
