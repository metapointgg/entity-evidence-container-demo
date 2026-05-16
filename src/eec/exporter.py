from __future__ import annotations

from pathlib import Path

from .container_reader import extract_container, inspect_container, validate_container, read_manifest, read_entity, read_provenance
from .utils import write_json


def export_evidence_pack(container: Path, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    payload_dir = output / "payloads"
    extract_container(container, payload_dir)

    entity = read_entity(container)
    manifest = read_manifest(container)
    provenance = read_provenance(container)
    validation = validate_container(container)
    summary = inspect_container(container)

    write_json(output / "entity_metadata.json", entity)
    write_json(output / "manifest.json", manifest)
    write_json(output / "provenance.json", provenance)
    write_json(output / "validation_report.json", validation.to_dict())

    md = [
        f"# Evidence Pack: {entity.get('display_name')} / {entity.get('entity_id')}",
        "",
        f"- Jurisdiction: {entity.get('jurisdiction')}",
        f"- Risk rating: {entity.get('risk_rating')}",
        f"- Payload count: {summary['payload_count']}",
        f"- Integrity status: {validation.status}",
        "",
        "## Contents",
        "",
        "| Object ID | Category | Document Type | File | Retention | SHA-256 |",
        "|---|---|---|---|---|---|",
    ]
    for item in manifest:
        md.append(f"| {item['object_id']} | {item['category']} | {item['document_type']} | {item['relative_path']} | {item['retention_class']} | `{item['sha256'][:16]}...` |")
    (output / "EVIDENCE_PACK_SUMMARY.md").write_text("\n".join(md), encoding="utf-8")
    return output
