from __future__ import annotations

import pickle
import sqlite3
from pathlib import Path
from typing import Any, Dict, List


def _load_rows(sqlite_path: Path) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT o.object_id, o.entity_id, o.container_id, o.snapshot_id, o.snapshot_type, e.display_name, e.risk_rating, e.jurisdiction,
                   o.category, o.document_type, o.filename, o.relative_path, o.source_system, o.retention_class,
                   o.retention_until, o.legal_hold_status, o.deletion_eligible, o.sensitivity, o.ocr_source,
                   o.container_path, o.hdu_name, o.size_bytes, o.mime_type, o.search_text
            FROM objects o
            JOIN entities e ON e.entity_id = o.entity_id
            ORDER BY o.object_id
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _row_text(row: Dict[str, Any]) -> str:
    fields = [
        "display_name", "risk_rating", "jurisdiction", "snapshot_type", "category", "document_type", "filename",
        "source_system", "retention_class", "legal_hold_status", "sensitivity", "search_text",
    ]
    return " ".join(str(row.get(f, "")) for f in fields)


def build_vector_index(sqlite_path: Path, output_path: Path) -> int:
    """Build a local offline vector index using scikit-learn TF-IDF vectors.

    This is intentionally dependency-light compared with transformer embeddings, but it is a genuine
    vector-space retrieval layer: documents and queries are embedded into a sparse vector space and
    ranked using cosine similarity. The interface is deliberately swappable for FAISS/Qdrant or
    sentence-transformers later.
    """
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.neighbors import NearestNeighbors
    except Exception as exc:  # pragma: no cover - depends on optional local install
        raise RuntimeError("Vector search requires scikit-learn. Install with: python -m pip install scikit-learn") from exc

    rows = _load_rows(sqlite_path)
    texts = [_row_text(row).strip() for row in rows]

    if not rows or not any(texts):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("wb") as f:
            pickle.dump({"rows": [], "vectorizer": None, "matrix": None, "nn": None}, f)
        return 0

    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=50000)
    matrix = vectorizer.fit_transform(texts)
    nn = NearestNeighbors(metric="cosine", algorithm="brute")
    nn.fit(matrix)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as f:
        pickle.dump({"rows": rows, "vectorizer": vectorizer, "matrix": matrix, "nn": nn}, f)
    return len(rows)


def vector_search(index_path: Path, query: str, limit: int = 50) -> List[Dict[str, Any]]:
    if not index_path.exists():
        return []
    with index_path.open("rb") as f:
        payload = pickle.load(f)
    rows = payload["rows"]
    if not rows or not query.strip():
        return rows[:limit]
    vectorizer = payload.get("vectorizer")
    nn = payload.get("nn")
    if vectorizer is None or nn is None:
        return []
    q = vectorizer.transform([query])
    k = min(limit, len(rows))
    distances, indices = nn.kneighbors(q, n_neighbors=k)
    out: List[Dict[str, Any]] = []
    for distance, idx in zip(distances[0], indices[0]):
        row = dict(rows[int(idx)])
        row["vector_score"] = float(1.0 - distance)
        row["snippet"] = (row.get("search_text") or "")[:300]
        out.append(row)
    return out
