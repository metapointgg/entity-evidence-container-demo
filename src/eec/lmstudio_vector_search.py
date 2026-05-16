from __future__ import annotations

import math
import pickle
import sqlite3
from pathlib import Path
from typing import Any

from .local_llm import embed_texts, embedding_model


def _load_rows(sqlite_path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT o.object_id, o.entity_id, o.container_id, o.snapshot_id, o.snapshot_type,
                   e.display_name, e.risk_rating, e.jurisdiction, e.occupation,
                   o.category, o.document_type, o.filename, o.relative_path, o.source_system,
                   o.retention_class, o.retention_until, o.legal_hold_status, o.deletion_eligible,
                   o.sensitivity, o.ocr_source, o.container_path, o.hdu_name, o.size_bytes,
                   o.mime_type, o.search_text
            FROM objects o
            JOIN entities e ON e.entity_id = o.entity_id
            ORDER BY o.object_id
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _row_text(row: dict[str, Any]) -> str:
    fields = [
        "display_name",
        "risk_rating",
        "jurisdiction",
        "occupation",
        "snapshot_type",
        "category",
        "document_type",
        "filename",
        "source_system",
        "retention_class",
        "legal_hold_status",
        "sensitivity",
        "search_text",
    ]
    return "\n".join(str(row.get(f, "")) for f in fields if row.get(f) is not None)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def build_lmstudio_vector_index(sqlite_path: Path, output_path: Path, *, batch_size: int = 32, model: str | None = None) -> int:
    """Build a local embedding index using the LM Studio /v1/embeddings endpoint."""
    rows = _load_rows(sqlite_path)
    texts = [_row_text(row) for row in rows]
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        vectors.extend(embed_texts(texts[start : start + batch_size], model=model))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as f:
        pickle.dump(
            {
                "provider": "lmstudio",
                "embedding_model": model or embedding_model(),
                "rows": rows,
                "vectors": vectors,
            },
            f,
        )
    return len(rows)


def lmstudio_vector_search(index_path: Path, query: str, limit: int = 50, *, model: str | None = None) -> list[dict[str, Any]]:
    if not index_path.exists():
        return []
    with index_path.open("rb") as f:
        payload = pickle.load(f)
    rows: list[dict[str, Any]] = payload.get("rows", [])
    vectors: list[list[float]] = payload.get("vectors", [])
    if not rows or not query.strip():
        return rows[:limit]
    query_vector = embed_texts([query], model=model or payload.get("embedding_model"))[0]
    scored: list[dict[str, Any]] = []
    for row, vector in zip(rows, vectors):
        out = dict(row)
        out["lmstudio_vector_score"] = float(_cosine(query_vector, vector))
        out["snippet"] = (out.get("search_text") or "")[:300]
        scored.append(out)
    scored.sort(key=lambda row: row.get("lmstudio_vector_score", 0.0), reverse=True)
    return scored[:limit]
