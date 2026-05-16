from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .ui_data import read_payload
from .utils import sha256_bytes, write_json


def export_search_results(rows: Iterable[Dict[str, Any]], output: Path, pack_name: str = "search-results-evidence-pack") -> Path:
    """Export selected search result payloads into a regulator-friendly folder pack."""
    rows = list(rows)
    output.mkdir(parents=True, exist_ok=True)
    payloads = output / "payloads"
    payloads.mkdir(parents=True, exist_ok=True)

    exported: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        item, data = read_payload(Path(row["container_path"]), row["object_id"])
        entity_dir = payloads / item["entity_id"]
        entity_dir.mkdir(parents=True, exist_ok=True)
        safe_name = f"{idx:04d}_{item['object_id']}_{item['filename']}".replace("/", "_").replace("\\", "_")
        out = entity_dir / safe_name
        out.write_bytes(data)
        record = dict(row)
        record.update({
            "exported_path": str(out.relative_to(output)),
            "exported_sha256": sha256_bytes(data),
            "manifest_sha256": item.get("sha256"),
        })
        exported.append(record)

    write_json(output / "search_results_manifest.json", exported)
    md = [
        f"# Evidence Pack: {pack_name}",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Result count: {len(exported)}",
        "",
        "| # | Entity | Object ID | Category | Type | File | Source | SHA-256 |",
        "|---:|---|---|---|---|---|---|---|",
    ]
    for idx, row in enumerate(exported, start=1):
        md.append(
            f"| {idx} | {row.get('entity_id')} | {row.get('object_id')} | {row.get('category')} | "
            f"{row.get('document_type')} | {row.get('filename')} | {row.get('source_system')} | "
            f"`{str(row.get('exported_sha256'))[:16]}...` |"
        )
    (output / "EVIDENCE_PACK_SUMMARY.md").write_text("\n".join(md), encoding="utf-8")
    return output
