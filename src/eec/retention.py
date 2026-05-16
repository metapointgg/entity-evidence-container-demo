from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Dict, List


def retention_report(sqlite_path: Path) -> Dict[str, Any]:
    if not sqlite_path.exists():
        return {"rows": [], "summary": {}}
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(row) for row in conn.execute(
            """
            SELECT o.object_id, o.entity_id, e.display_name, e.risk_rating, o.snapshot_id, o.category, o.document_type,
                   o.filename, o.retention_class, o.retention_until, o.legal_hold_status, o.deletion_eligible,
                   o.sensitivity, o.source_system, o.container_path
            FROM objects o
            JOIN entities e ON e.entity_id = o.entity_id
            ORDER BY o.retention_until, o.entity_id, o.filename
            """
        ).fetchall()]
        today = date.today().isoformat()
        expired = [r for r in rows if r.get("retention_until") and r["retention_until"] < today]
        legal_hold = [r for r in rows if r.get("legal_hold_status") == "Active"]
        eligible = [r for r in rows if r.get("deletion_eligible") == "Yes"]
        summary = {
            "total_objects": len(rows),
            "expired_retention": len(expired),
            "legal_hold": len(legal_hold),
            "deletion_eligible": len(eligible),
        }
        return {"rows": rows, "expired": expired, "legal_hold": legal_hold, "eligible": eligible, "summary": summary}
    finally:
        conn.close()
