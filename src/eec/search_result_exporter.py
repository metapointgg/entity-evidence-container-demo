from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .ui_data import read_payload
from .utils import sha256_bytes, write_json, slug


def _jsonable(value: Any) -> Any:
    """Return a best-effort JSON-serialisable representation."""
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(k): _jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [_jsonable(v) for v in value]
        return str(value)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _short(value: Any, length: int = 16) -> str:
    text = str(value or "")
    return f"{text[:length]}..." if len(text) > length else text


def _source_system_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_source = Counter(str(row.get("source_system") or "Unknown") for row in rows)
    by_entity_source: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        entity_id = str(row.get("entity_id") or "Unknown")
        source = str(row.get("source_system") or "Unknown")
        by_entity_source[entity_id][source] += 1
    return {
        "total_source_systems": len(by_source),
        "source_system_counts": dict(by_source),
        "by_entity": {entity_id: dict(counter) for entity_id, counter in by_entity_source.items()},
    }


def _retention_legal_hold_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    legal_hold_rows = [row for row in rows if str(row.get("legal_hold_status") or "").lower() not in {"", "none", "not on hold", "false"}]
    deletion_eligible_rows = [row for row in rows if row.get("deletion_eligible") in {True, "True", "true", "Yes", "yes", 1}]
    retention_classes = Counter(str(row.get("retention_class") or "Unclassified") for row in rows)
    return {
        "total_records": len(rows),
        "legal_hold_count": len(legal_hold_rows),
        "deletion_eligible_count": len(deletion_eligible_rows),
        "retention_class_counts": dict(retention_classes),
        "legal_hold_records": [
            {
                "entity_id": row.get("entity_id"),
                "object_id": row.get("object_id"),
                "filename": row.get("filename"),
                "retention_class": row.get("retention_class"),
                "retention_until": row.get("retention_until"),
                "legal_hold_status": row.get("legal_hold_status"),
            }
            for row in legal_hold_rows
        ],
    }


def _hash_report(exported: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    mismatches = []
    for row in exported:
        exported_hash = row.get("exported_sha256")
        manifest_hash = row.get("manifest_sha256") or row.get("sha256")
        match = bool(exported_hash and manifest_hash and exported_hash == manifest_hash)
        record = {
            "entity_id": row.get("entity_id"),
            "object_id": row.get("object_id"),
            "filename": row.get("filename"),
            "exported_path": row.get("exported_path"),
            "exported_sha256": exported_hash,
            "manifest_sha256": manifest_hash,
            "match": match,
        }
        rows.append(record)
        if not match:
            mismatches.append(record)
    return {
        "total_files": len(rows),
        "matched": len(rows) - len(mismatches),
        "mismatched": len(mismatches),
        "status": "PASS" if not mismatches else "FAIL",
        "rows": rows,
        "mismatches": mismatches,
    }


def _write_markdown_summary(
    output: Path,
    *,
    pack_name: str,
    query: str | None,
    exported: list[dict[str, Any]],
    hash_report: dict[str, Any],
    source_report: dict[str, Any],
    retention_report: dict[str, Any],
) -> None:
    entity_count = len({row.get("entity_id") for row in exported})
    category_counts = Counter(str(row.get("category") or "Uncategorised") for row in exported)
    document_counts = Counter(str(row.get("document_type") or "Unknown") for row in exported)
    source_counts = source_report.get("source_system_counts", {})

    md = [
        f"# Evidence Pack: {pack_name}",
        "",
        f"Generated: {_now()}",
        f"Query: `{query or pack_name}`",
        f"Evidence files: {len(exported)}",
        f"Customers/entities: {entity_count}",
        f"Hash status: {hash_report.get('status')}",
        "",
        "## What this pack contains",
        "",
        "This pack contains recovered original evidence payloads from the FITS preservation containers, "
        "together with the interpreted query, manifest, source-system summary, retention/legal-hold summary "
        "and SHA-256 hash report.",
        "",
        "## Included files",
        "",
        "| File | Purpose |",
        "|---|---|",
        "| `README.md` | Human-readable overview of the evidence pack structure. |",
        "| `EVIDENCE_PACK_SUMMARY.md` | This summary. |",
        "| `AI_SUMMARY.md` | Optional local-AI summary generated from retrieved evidence. |",
        "| `QUERY.json` | Original query, generation timestamp and result counts. |",
        "| `STRUCTURED_QUERY.json` | Controlled structured query used by the application. |",
        "| `RULESET_USED.json` | Ruleset context where applicable. |",
        "| `COMPLETENESS_REPORT.json` | Completeness result where applicable. |",
        "| `MANIFEST.json` | Export manifest for every evidence payload. |",
        "| `HASH_REPORT.json` | SHA-256 verification of exported files against preserved manifest hashes. |",
        "| `SOURCE_SYSTEMS.json` | Source-system counts and source-system contribution by customer. |",
        "| `RETENTION_LEGAL_HOLD_REPORT.json` | Retention, deletion and legal-hold context for exported evidence. |",
        "| `files/` | Recovered original evidence payloads grouped by entity. |",
        "",
        "## Category summary",
        "",
        "| Category | Count |",
        "|---|---:|",
    ]
    for category, count in sorted(category_counts.items()):
        md.append(f"| {category} | {count} |")

    md.extend(["", "## Document type summary", "", "| Document type | Count |", "|---|---:|"])
    for doc_type, count in sorted(document_counts.items()):
        md.append(f"| {doc_type} | {count} |")

    md.extend(["", "## Source-system summary", "", "| Source system | Count |", "|---|---:|"])
    for source, count in sorted(source_counts.items()):
        md.append(f"| {source} | {count} |")

    md.extend([
        "",
        "## Evidence manifest",
        "",
        "| # | Entity | Object ID | Snapshot | Category | Type | File | Source | SHA-256 |",
        "|---:|---|---|---|---|---|---|---|---|",
    ])
    for idx, row in enumerate(exported, start=1):
        md.append(
            f"| {idx} | {row.get('entity_id')} | {row.get('object_id')} | {row.get('snapshot_id') or ''} | "
            f"{row.get('category')} | {row.get('document_type')} | {row.get('filename')} | "
            f"{row.get('source_system')} | `{_short(row.get('exported_sha256'))}` |"
        )

    (output / "EVIDENCE_PACK_SUMMARY.md").write_text("\n".join(md), encoding="utf-8")


def _write_readme(output: Path, pack_name: str) -> None:
    (output / "README.md").write_text(
        "\n".join(
            [
                f"# {pack_name}",
                "",
                "This is a portable evidence pack exported from the Entity Evidence Container proof of concept.",
                "",
                "The `files/` directory contains recovered original evidence payloads. The JSON and Markdown files "
                "around it describe why those files were exported, how they map to the archive metadata, and whether "
                "their SHA-256 hashes match the preserved manifest values.",
                "",
                "The AI summary, when present, is assistive only. The manifest, hash report and original files remain the evidence of record.",
            ]
        ),
        encoding="utf-8",
    )


def export_search_results(
    rows: Iterable[Dict[str, Any]],
    output: Path,
    pack_name: str = "search-results-evidence-pack",
    *,
    query: str | None = None,
    structured_query: dict[str, Any] | None = None,
    ruleset: dict[str, Any] | None = None,
    completeness_report: dict[str, Any] | None = None,
    ai_summary: str | None = None,
) -> Path:
    """Export retrieved evidence rows into a regulator-friendly portable pack.

    The pack is intentionally self-describing: it includes original recovered payloads,
    the natural-language query, the validated structured query, hashes, retention/legal-hold
    metadata and source-system provenance. This makes the export useful for audit,
    regulatory requests, complaints, SARs and remediation exercises.
    """
    rows = [dict(row) for row in rows]
    output.mkdir(parents=True, exist_ok=True)
    files_dir = output / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    exported: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        item, data = read_payload(Path(row["container_path"]), row["object_id"])
        entity_id = str(item.get("entity_id") or row.get("entity_id") or "unknown_entity")
        entity_dir = files_dir / slug(entity_id)
        entity_dir.mkdir(parents=True, exist_ok=True)
        safe_name = slug(f"{idx:04d}_{item.get('object_id')}_{item.get('filename')}", max_len=140)
        # Preserve the original extension where slugging has stripped punctuation.
        original_name = str(item.get("filename") or row.get("filename") or "payload.bin")
        suffix = Path(original_name).suffix
        if suffix and not safe_name.lower().endswith(suffix.lower().lstrip(".")):
            safe_name = f"{safe_name}{suffix}"
        out = entity_dir / safe_name
        out.write_bytes(data)
        record = dict(row)
        record.update(
            {
                "export_sequence": idx,
                "exported_path": str(out.relative_to(output)),
                "exported_sha256": sha256_bytes(data),
                "manifest_sha256": item.get("sha256") or row.get("sha256"),
                "payload_size_bytes": len(data),
            }
        )
        exported.append(_jsonable(record))

    hash_report = _hash_report(exported)
    source_report = _source_system_summary(exported)
    retention_report = _retention_legal_hold_report(exported)

    query_payload = {
        "pack_name": pack_name,
        "query": query or pack_name,
        "generated_at": _now(),
        "result_count": len(exported),
        "entity_count": len({row.get("entity_id") for row in exported}),
    }

    write_json(output / "QUERY.json", _jsonable(query_payload))
    write_json(output / "STRUCTURED_QUERY.json", _jsonable(structured_query or {}))
    write_json(output / "RULESET_USED.json", _jsonable(ruleset or {}))
    write_json(output / "COMPLETENESS_REPORT.json", _jsonable(completeness_report or {}))
    write_json(output / "MANIFEST.json", _jsonable(exported))
    write_json(output / "HASH_REPORT.json", _jsonable(hash_report))
    write_json(output / "SOURCE_SYSTEMS.json", _jsonable(source_report))
    write_json(output / "RETENTION_LEGAL_HOLD_REPORT.json", _jsonable(retention_report))

    (output / "AI_SUMMARY.md").write_text(
        ai_summary.strip() if ai_summary and ai_summary.strip() else "No AI summary was supplied or generated for this evidence pack.\n",
        encoding="utf-8",
    )
    _write_readme(output, pack_name)
    _write_markdown_summary(
        output,
        pack_name=pack_name,
        query=query or pack_name,
        exported=exported,
        hash_report=hash_report,
        source_report=source_report,
        retention_report=retention_report,
    )
    return output
