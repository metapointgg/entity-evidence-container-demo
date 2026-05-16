from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .container_reader import extract_container, inspect_container, validate_container, read_manifest, read_entity, read_provenance
from .utils import write_json, sha256_file


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _source_systems(manifest: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(item.get("source_system") or "Unknown") for item in manifest)
    return {"total_source_systems": len(counts), "source_system_counts": dict(counts)}


def _retention_report(manifest: list[dict[str, Any]]) -> dict[str, Any]:
    retention_counts = Counter(str(item.get("retention_class") or "Unclassified") for item in manifest)
    legal_hold = [item for item in manifest if str(item.get("legal_hold_status") or "").lower() not in {"", "none", "not on hold", "false"}]
    deletion_eligible = [item for item in manifest if item.get("deletion_eligible") in {True, "true", "True", "Yes", "yes", 1}]
    return {
        "total_records": len(manifest),
        "retention_class_counts": dict(retention_counts),
        "legal_hold_count": len(legal_hold),
        "deletion_eligible_count": len(deletion_eligible),
        "legal_hold_records": legal_hold,
    }


def export_evidence_pack(container: Path, output: Path) -> Path:
    """Export one FITS container into a self-describing evidence pack."""
    output.mkdir(parents=True, exist_ok=True)
    files_dir = output / "files"
    extract_container(container, files_dir)

    entity = read_entity(container)
    manifest = read_manifest(container)
    provenance = read_provenance(container)
    validation = validate_container(container)
    summary = inspect_container(container)
    source_report = _source_systems(manifest)
    retention_report = _retention_report(manifest)

    exported_manifest: list[dict[str, Any]] = []
    hash_rows = []
    for item in manifest:
        rel = item.get("relative_path") or item.get("filename")
        payload_path = files_dir / rel
        exported_hash = sha256_file(payload_path) if payload_path.exists() else None
        manifest_hash = item.get("sha256")
        hash_rows.append(
            {
                "object_id": item.get("object_id"),
                "filename": item.get("filename"),
                "exported_path": str(payload_path.relative_to(output)) if payload_path.exists() else None,
                "exported_sha256": exported_hash,
                "manifest_sha256": manifest_hash,
                "match": bool(exported_hash and manifest_hash and exported_hash == manifest_hash),
            }
        )
        exported_manifest.append({**item, "exported_path": str(payload_path.relative_to(output)) if payload_path.exists() else None})

    hash_report = {
        "status": "PASS" if all(row["match"] for row in hash_rows) else "FAIL",
        "total_files": len(hash_rows),
        "matched": sum(1 for row in hash_rows if row["match"]),
        "mismatched": sum(1 for row in hash_rows if not row["match"]),
        "rows": hash_rows,
        "mismatches": [row for row in hash_rows if not row["match"]],
    }

    write_json(output / "QUERY.json", {"pack_type": "single_container", "container": str(container), "generated_at": _now()})
    write_json(output / "STRUCTURED_QUERY.json", {})
    write_json(output / "RULESET_USED.json", {})
    write_json(output / "COMPLETENESS_REPORT.json", {})
    write_json(output / "MANIFEST.json", exported_manifest)
    write_json(output / "HASH_REPORT.json", hash_report)
    write_json(output / "SOURCE_SYSTEMS.json", source_report)
    write_json(output / "RETENTION_LEGAL_HOLD_REPORT.json", retention_report)
    write_json(output / "entity_metadata.json", entity)
    write_json(output / "provenance.json", provenance)
    write_json(output / "validation_report.json", validation.to_dict())

    (output / "AI_SUMMARY.md").write_text("No AI summary was supplied or generated for this single-container evidence pack.\n", encoding="utf-8")
    (output / "README.md").write_text(
        "\n".join(
            [
                f"# Evidence Pack: {entity.get('display_name')} / {entity.get('entity_id')}",
                "",
                "This pack was exported from one FITS preservation container.",
                "",
                "The `files/` directory contains recovered original payloads. JSON reports provide manifest, provenance, validation, hash, retention/legal-hold and source-system context.",
            ]
        ),
        encoding="utf-8",
    )

    category_counts = Counter(str(item.get("category") or "Uncategorised") for item in manifest)
    md = [
        f"# Evidence Pack: {entity.get('display_name')} / {entity.get('entity_id')}",
        "",
        f"Generated: {_now()}",
        f"- Container: `{container.name}`",
        f"- Jurisdiction: {entity.get('jurisdiction')}",
        f"- Risk rating: {entity.get('risk_rating')}",
        f"- Payload count: {summary['payload_count']}",
        f"- Integrity status: {validation.status}",
        f"- Hash report status: {hash_report['status']}",
        "",
        "## Category summary",
        "",
        "| Category | Count |",
        "|---|---:|",
    ]
    for category, count in sorted(category_counts.items()):
        md.append(f"| {category} | {count} |")
    md.extend(["", "## Contents", "", "| Object ID | Category | Document Type | File | Retention | SHA-256 |", "|---|---|---|---|---|---|"])
    for item in manifest:
        md.append(f"| {item['object_id']} | {item['category']} | {item['document_type']} | {item.get('relative_path') or item.get('filename')} | {item.get('retention_class')} | `{str(item.get('sha256'))[:16]}...` |")
    (output / "EVIDENCE_PACK_SUMMARY.md").write_text("\n".join(md), encoding="utf-8")
    return output
