from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List

from .container_reader import validate_container
from .ui_data import format_bytes


def integrity_health(containers_dir: Path) -> Dict[str, Any]:
    containers = sorted(p for p in containers_dir.glob("*.fits") if p.is_file())
    rows: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    total_payloads = 0
    failed_containers = 0
    for container in containers:
        result = validate_container(container).to_dict()
        result["container_name"] = container.name
        result["container_size_bytes"] = container.stat().st_size
        total_payloads += result.get("checked_payloads", 0)
        if result["status"] != "PASS":
            failed_containers += 1
            for failure in result.get("failures", []):
                failures.append({"container": container.name, **failure})
        rows.append(result)
    return {
        "container_count": len(containers),
        "passed_containers": len(containers) - failed_containers,
        "failed_containers": failed_containers,
        "checked_payloads": total_payloads,
        "failed_payloads": len(failures),
        "total_container_bytes": sum(p.stat().st_size for p in containers),
        "total_container_size": format_bytes(sum(p.stat().st_size for p in containers)),
        "rows": rows,
        "failures": failures,
    }


def indexed_health(sqlite_path: Path) -> Dict[str, Any]:
    if not sqlite_path.exists():
        return {"index_exists": False}
    conn = sqlite3.connect(sqlite_path)
    try:
        def one(sql: str):
            return conn.execute(sql).fetchone()[0]
        return {
            "index_exists": True,
            "entities": one("SELECT COUNT(*) FROM entities"),
            "containers": one("SELECT COUNT(*) FROM containers"),
            "objects": one("SELECT COUNT(*) FROM objects"),
            "legal_hold_objects": one("SELECT COUNT(*) FROM objects WHERE legal_hold_status = 'Active'"),
            "restricted_objects": one("SELECT COUNT(*) FROM objects WHERE sensitivity = 'Restricted'"),
            "snapshot_types": conn.execute("SELECT snapshot_type, COUNT(*) FROM containers GROUP BY snapshot_type ORDER BY snapshot_type").fetchall(),
            "retention_classes": conn.execute("SELECT retention_class, COUNT(*) FROM objects GROUP BY retention_class ORDER BY retention_class").fetchall(),
        }
    finally:
        conn.close()
