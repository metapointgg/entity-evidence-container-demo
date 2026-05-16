from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from astropy.io import fits

from .container_reader import read_entity, read_manifest, validate_container


@dataclass(frozen=True)
class ArchivePaths:
    root: Path
    source: Path
    containers: Path
    index: Path
    exports: Path


def resolve_archive_paths(root: Path | str = Path("samples")) -> ArchivePaths:
    root_path = Path(root)
    return ArchivePaths(
        root=root_path,
        source=root_path / "source",
        containers=root_path / "containers",
        index=root_path / "index" / "evidence_index.db",
        exports=root_path / "exports",
    )


def list_container_paths(containers_dir: Path) -> List[Path]:
    return sorted(p for p in containers_dir.glob("*.fits") if p.is_file())


def get_archive_summary(paths: ArchivePaths) -> Dict[str, Any]:
    containers = list_container_paths(paths.containers)
    total_container_bytes = sum(p.stat().st_size for p in containers)

    entity_count = 0
    object_count = 0
    if paths.index.exists():
        conn = sqlite3.connect(paths.index)
        try:
            entity_count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            object_count = conn.execute("SELECT COUNT(*) FROM objects").fetchone()[0]
        finally:
            conn.close()

    return {
        "container_count": len(containers),
        "entity_count": entity_count,
        "object_count": object_count,
        "total_container_bytes": total_container_bytes,
        "index_exists": paths.index.exists(),
        "index_path": str(paths.index),
    }


def list_entities(sqlite_path: Path) -> List[Dict[str, Any]]:
    if not sqlite_path.exists():
        return []
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT e.entity_id, e.display_name, e.jurisdiction, e.risk_rating, e.occupation,
                   e.container_path, COUNT(o.object_id) AS object_count, COALESCE(SUM(o.size_bytes), 0) AS payload_bytes
            FROM entities e
            LEFT JOIN objects o ON o.entity_id = e.entity_id
            GROUP BY e.entity_id, e.display_name, e.jurisdiction, e.risk_rating, e.occupation, e.container_path
            ORDER BY e.entity_id
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_objects_for_entity(sqlite_path: Path, entity_id: str) -> List[Dict[str, Any]]:
    if not sqlite_path.exists():
        return []
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT object_id, entity_id, category, document_type, filename, relative_path, mime_type,
                   source_system, retention_class, sensitivity, sha256, size_bytes, container_path, hdu_name
            FROM objects
            WHERE entity_id = ?
            ORDER BY category, document_type, filename
            """,
            (entity_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_entity_by_id(sqlite_path: Path, entity_id: str) -> Optional[Dict[str, Any]]:
    if not sqlite_path.exists():
        return None
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM entities WHERE entity_id = ?", (entity_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def read_payload(container: Path, object_id: str) -> tuple[Dict[str, Any], bytes]:
    manifest = read_manifest(container)
    item = next((entry for entry in manifest if entry["object_id"] == object_id), None)
    if item is None:
        raise KeyError(f"Object {object_id} was not found in {container}")
    with fits.open(container, memmap=True) as hdul:
        data = bytes(hdul[item["hdu_name"]].data.tolist())
    return item, data


def validate_all_containers(containers_dir: Path) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for container in list_container_paths(containers_dir):
        result = validate_container(container)
        row = result.to_dict()
        row["container_name"] = container.name
        row["container_path"] = str(container)
        results.append(row)
    return results


def format_bytes(value: int | float | None) -> str:
    if value is None:
        return "0 B"
    size = float(value)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024
