from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Sequence

from .semantic import cosine_score

FILTER_COLUMNS = {
    "entity_id": "o.entity_id",
    "container_id": "o.container_id",
    "snapshot_id": "o.snapshot_id",
    "snapshot_type": "o.snapshot_type",
    "category": "o.category",
    "document_type": "o.document_type",
    "source_system": "o.source_system",
    "retention_class": "o.retention_class",
    "retention_until": "o.retention_until",
    "legal_hold_status": "o.legal_hold_status",
    "deletion_eligible": "o.deletion_eligible",
    "sensitivity": "o.sensitivity",
    "risk_rating": "e.risk_rating",
    "jurisdiction": "e.jurisdiction",
    "ocr_source": "o.ocr_source",
}


def _rows_to_dicts(rows):
    return [dict(row) for row in rows]


def _base_select() -> str:
    return """
        SELECT s.object_id, s.entity_id, s.container_id, s.snapshot_id, s.snapshot_type, s.display_name, s.category, s.document_type, s.filename, s.relative_path,
               s.source_system, s.retention_class, s.retention_until, s.legal_hold_status, s.deletion_eligible, s.sensitivity, s.risk_rating, s.jurisdiction, s.ocr_source,
               snippet(object_search, 20, '[', ']', ' ... ', 22) AS snippet,
               o.container_path, o.hdu_name, o.size_bytes, o.mime_type, o.search_text,
               e.occupation
        FROM object_search s
        JOIN objects o ON o.object_id = s.object_id
        JOIN entities e ON e.entity_id = o.entity_id
    """


def _build_filter_sql(filters: Dict[str, Sequence[str]] | None) -> tuple[str, list[Any]]:
    if not filters:
        return "", []
    clauses: list[str] = []
    params: list[Any] = []
    for name, values in filters.items():
        clean_values = [v for v in (values or []) if v]
        if not clean_values or name not in FILTER_COLUMNS:
            continue
        placeholders = ",".join("?" for _ in clean_values)
        clauses.append(f"{FILTER_COLUMNS[name]} IN ({placeholders})")
        params.extend(clean_values)
    if not clauses:
        return "", []
    return " AND " + " AND ".join(clauses), params


def search_index(sqlite_path: Path, query: str, limit: int = 20) -> List[Dict]:
    return advanced_search_index(sqlite_path, query=query, limit=limit, mode="keyword")


def advanced_search_index(sqlite_path: Path, query: str = "", filters: Dict[str, Sequence[str]] | None = None, limit: int = 50, mode: str = "keyword") -> List[Dict[str, Any]]:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        filter_sql, filter_params = _build_filter_sql(filters)
        if mode == "semantic" and query.strip():
            candidate_limit = max(limit * 10, 500)
            sql = _base_select() + f" WHERE 1=1 {filter_sql} LIMIT ?"
            params: list[Any] = [*filter_params, candidate_limit]
            rows = _rows_to_dicts(conn.execute(sql, params).fetchall())
            for row in rows:
                score_text = " ".join(str(row.get(k, "")) for k in ["display_name", "risk_rating", "snapshot_type", "category", "document_type", "filename", "source_system", "retention_class", "legal_hold_status", "search_text"])
                row["semantic_score"] = cosine_score(query, score_text)
            rows.sort(key=lambda r: r.get("semantic_score", 0.0), reverse=True)
            return rows[:limit]

        if query.strip():
            sql = _base_select() + f" WHERE object_search MATCH ? {filter_sql} LIMIT ?"
            params = [query, *filter_params, limit]
        else:
            sql = _base_select() + f" WHERE 1=1 {filter_sql} LIMIT ?"
            params = [*filter_params, limit]
        try:
            return _rows_to_dicts(conn.execute(sql, params).fetchall())
        except sqlite3.OperationalError as exc:
            if "no such column" in str(exc).lower():
                raise RuntimeError(
                    "The SQLite evidence index appears to be out of date for this version of the application. "
                    "Rebuild it with: python scripts\\rebuild_index.py --containers <root>\\containers --sqlite <root>\\index\\evidence_index.db "
                    "and then rebuild the vector index with: python scripts\\build_vector_index.py --sqlite <root>\\index\\evidence_index.db --output <root>\\index\\evidence_vector.pkl"
                ) from exc
            raise
    finally:
        conn.close()


def get_facets(sqlite_path: Path) -> Dict[str, List[str]]:
    if not sqlite_path.exists():
        return {}
    conn = sqlite3.connect(sqlite_path)
    try:
        facets: Dict[str, List[str]] = {}
        queries = {
            "entity_id": "SELECT DISTINCT entity_id FROM entities ORDER BY entity_id",
            "container_id": "SELECT DISTINCT container_id FROM containers ORDER BY container_id",
            "snapshot_id": "SELECT DISTINCT snapshot_id FROM containers WHERE snapshot_id IS NOT NULL ORDER BY snapshot_id",
            "snapshot_type": "SELECT DISTINCT snapshot_type FROM containers WHERE snapshot_type IS NOT NULL ORDER BY snapshot_type",
            "risk_rating": "SELECT DISTINCT risk_rating FROM entities WHERE risk_rating IS NOT NULL ORDER BY risk_rating",
            "jurisdiction": "SELECT DISTINCT jurisdiction FROM entities WHERE jurisdiction IS NOT NULL ORDER BY jurisdiction",
            "category": "SELECT DISTINCT category FROM objects WHERE category IS NOT NULL ORDER BY category",
            "document_type": "SELECT DISTINCT document_type FROM objects WHERE document_type IS NOT NULL ORDER BY document_type",
            "source_system": "SELECT DISTINCT source_system FROM objects WHERE source_system IS NOT NULL ORDER BY source_system",
            "retention_class": "SELECT DISTINCT retention_class FROM objects WHERE retention_class IS NOT NULL ORDER BY retention_class",
            "retention_until": "SELECT DISTINCT retention_until FROM objects WHERE retention_until IS NOT NULL AND retention_until != '' ORDER BY retention_until",
            "legal_hold_status": "SELECT DISTINCT legal_hold_status FROM objects WHERE legal_hold_status IS NOT NULL ORDER BY legal_hold_status",
            "deletion_eligible": "SELECT DISTINCT deletion_eligible FROM objects WHERE deletion_eligible IS NOT NULL ORDER BY deletion_eligible",
            "sensitivity": "SELECT DISTINCT sensitivity FROM objects WHERE sensitivity IS NOT NULL ORDER BY sensitivity",
            "ocr_source": "SELECT DISTINCT ocr_source FROM objects WHERE ocr_source IS NOT NULL ORDER BY ocr_source",
        }
        for name, sql in queries.items():
            facets[name] = [row[0] for row in conn.execute(sql).fetchall() if row[0]]
        return facets
    finally:
        conn.close()
