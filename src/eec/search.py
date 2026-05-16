from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, List


def search_index(sqlite_path: Path, query: str, limit: int = 20) -> List[Dict]:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT s.object_id, s.entity_id, s.display_name, s.category, s.document_type, s.filename, s.relative_path,
                   s.source_system, s.retention_class, s.sensitivity,
                   snippet(object_search, 10, '[', ']', ' ... ', 18) AS snippet,
                   o.container_path, o.hdu_name, o.size_bytes
            FROM object_search s
            JOIN objects o ON o.object_id = s.object_id
            WHERE object_search MATCH ?
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
