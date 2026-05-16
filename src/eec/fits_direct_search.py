from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Sequence

from .container_reader import read_entity, read_manifest, read_snapshots
from .semantic import cosine_score, expand_query


DOCUMENT_TYPE_ALIASES = {
    "Proof of Address": ["proof of address", "utility bill", "address evidence"],
    "Source of Wealth": ["source of wealth", "wealth evidence", "property sale", "investment income"],
    "Source of Funds": ["source of funds", "funding evidence", "origin of funds", "initial deposit"],
    "CDD Review": ["cdd", "due diligence", "kyc", "risk review"],
    "Passport": ["passport", "identity evidence", "identity verification"],
    "Bank Statement": ["statement", "bank statement", "monthly statement"],
}

CATEGORY_ALIASES = {
    "Address": ["address", "proof of address", "utility bill", "due diligence"],
    "Identity": ["identity", "passport", "id", "due diligence"],
    "Due Diligence": ["due diligence", "cdd", "kyc", "source of wealth", "source of funds", "screening"],
    "Statements": ["statement", "statements", "bank statement"],
    "Transactions": ["transaction", "transactions", "payment", "transfer"],
    "Correspondence": ["correspondence", "email", "communications", "letter"],
    "Complaints": ["complaint", "dispute"],
    "Legal": ["legal", "disclosure", "legal hold", "sar", "subject access"],
}


def _normalise(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _contains_any(haystack: str, needles: Iterable[str]) -> bool:
    return any(_normalise(needle) in haystack for needle in needles if str(needle).strip())


def _row_text(entity: dict[str, Any], item: dict[str, Any]) -> str:
    return " ".join(
        str(part or "")
        for part in [
            entity.get("entity_id"),
            entity.get("display_name"),
            entity.get("jurisdiction"),
            entity.get("risk_rating"),
            entity.get("occupation"),
            item.get("snapshot_id"),
            item.get("snapshot_type"),
            item.get("category"),
            item.get("document_type"),
            item.get("filename"),
            item.get("relative_path"),
            item.get("source_system"),
            item.get("retention_class"),
            item.get("legal_hold_status"),
            item.get("sensitivity"),
            item.get("ocr_text"),
            item.get("search_text"),
        ]
    )


def _make_snippet(text: str, terms: Sequence[str], radius: int = 140) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean:
        return ""
    lower = clean.lower()
    for term in terms:
        term = str(term or "").strip().lower()
        if not term:
            continue
        idx = lower.find(term)
        if idx >= 0:
            start = max(0, idx - radius)
            end = min(len(clean), idx + len(term) + radius)
            return ("..." if start else "") + clean[start:end] + ("..." if end < len(clean) else "")
    return clean[: radius * 2] + ("..." if len(clean) > radius * 2 else "")


def _passes_filters(item: dict[str, Any], entity: dict[str, Any], filters: dict[str, Sequence[str]] | None) -> bool:
    if not filters:
        return True
    lookup = {
        "entity_id": entity.get("entity_id"),
        "jurisdiction": entity.get("jurisdiction"),
        "risk_rating": entity.get("risk_rating"),
        "snapshot_id": item.get("snapshot_id"),
        "snapshot_type": item.get("snapshot_type"),
        "category": item.get("category"),
        "document_type": item.get("document_type"),
        "source_system": item.get("source_system"),
        "retention_class": item.get("retention_class"),
        "legal_hold_status": item.get("legal_hold_status"),
        "deletion_eligible": item.get("deletion_eligible"),
        "sensitivity": item.get("sensitivity"),
        "ocr_source": item.get("ocr_source"),
    }
    for key, values in filters.items():
        values = [str(v) for v in values or [] if str(v).strip()]
        if not values:
            continue
        actual = str(lookup.get(key, ""))
        if actual not in values:
            return False
    return True


def _structured_matches(item: dict[str, Any], entity: dict[str, Any], structured: Any | None) -> bool:
    if structured is None:
        return True
    if getattr(structured, "entity_id", None) and entity.get("entity_id") != structured.entity_id:
        return False
    for attr, entity_key in [("jurisdiction", "jurisdiction"), ("risk_rating", "risk_rating")]:
        wanted = getattr(structured, attr, None)
        if wanted and entity.get(entity_key) != wanted:
            return False
    for attr, item_key in [
        ("snapshot_id", "snapshot_id"),
        ("snapshot_type", "snapshot_type"),
        ("source_system", "source_system"),
        ("retention_class", "retention_class"),
        ("legal_hold_status", "legal_hold_status"),
        ("sensitivity", "sensitivity"),
    ]:
        wanted = getattr(structured, attr, None)
        if wanted and item.get(item_key) != wanted:
            return False

    text = _normalise(_row_text(entity, item))
    document_type = getattr(structured, "document_type", None)
    evidence_category = getattr(structured, "evidence_category", None)
    if document_type:
        aliases = DOCUMENT_TYPE_ALIASES.get(document_type, [document_type])
        identity_text = _normalise(" ".join([str(item.get("document_type", "")), str(item.get("filename", "")), str(item.get("relative_path", "")), str(item.get("category", ""))]))
        if not _contains_any(identity_text, aliases) and not _contains_any(text, aliases):
            return False
    elif evidence_category:
        aliases = CATEGORY_ALIASES.get(evidence_category, [evidence_category])
        if not _contains_any(text, aliases):
            return False
    return True


def _score_item(query: str, entity: dict[str, Any], item: dict[str, Any], keyword_terms: Sequence[str] | None = None) -> float:
    query = query or ""
    terms = [query, *(keyword_terms or [])]
    row_text = _row_text(entity, item)
    row_lower = _normalise(row_text)
    score = 0.0
    for term in terms:
        term_norm = _normalise(term)
        if not term_norm:
            continue
        if term_norm in row_lower:
            score += 5.0
        for token in term_norm.split():
            if len(token) > 2 and token in row_lower:
                score += 0.3
    if query.strip():
        score += cosine_score(query, row_text + " " + expand_query(row_text[:1000])) * 3.0
    return score


def direct_search_container(
    container: Path,
    query: str = "",
    *,
    structured: Any | None = None,
    filters: dict[str, Sequence[str]] | None = None,
    limit: int = 50,
    include_all_when_empty: bool = True,
) -> list[dict[str, Any]]:
    """Search a single FITS container directly, without SQLite or vector indexes.

    This proves that the entity archive object is self-describing and searchable.
    The returned row shape intentionally mirrors indexed search rows so the UI,
    preview, validation and export paths can be reused.
    """
    container = Path(container)
    entity = read_entity(container)
    manifest = read_manifest(container)
    snapshots = {item.get("snapshot_id"): item for item in read_snapshots(container)}
    query_terms = [query]
    if structured is not None:
        query_terms.extend(getattr(structured, "keyword_terms", []) or [])
        query_text = getattr(structured, "semantic_query", None) or getattr(structured, "raw_query", None) or query
    else:
        query_text = query

    rows: list[dict[str, Any]] = []
    for item in manifest:
        if not _passes_filters(item, entity, filters):
            continue
        if not _structured_matches(item, entity, structured):
            continue
        text = _row_text(entity, item)
        score = _score_item(query_text or query, entity, item, keyword_terms=query_terms)
        if query.strip() or query_text:
            # Keep strong structured matches even if free text score is low, but drop obviously unrelated rows.
            if score <= 0 and structured is None:
                continue
        snapshot_id = item.get("snapshot_id")
        snapshot = snapshots.get(snapshot_id, {})
        rows.append(
            {
                "object_id": item.get("object_id"),
                "entity_id": entity.get("entity_id"),
                "container_id": f"{entity.get('entity_id')}:ENTITY_ARCHIVE:v{entity.get('container_version', 1)}",
                "snapshot_id": snapshot_id,
                "snapshot_type": item.get("snapshot_type") or snapshot.get("snapshot_type"),
                "display_name": entity.get("display_name"),
                "jurisdiction": entity.get("jurisdiction"),
                "risk_rating": entity.get("risk_rating"),
                "occupation": entity.get("occupation"),
                "category": item.get("category"),
                "document_type": item.get("document_type"),
                "filename": item.get("filename"),
                "relative_path": item.get("relative_path"),
                "mime_type": item.get("mime_type"),
                "source_system": item.get("source_system"),
                "retention_class": item.get("retention_class"),
                "retention_until": item.get("retention_until", ""),
                "legal_hold_status": item.get("legal_hold_status", "None"),
                "deletion_eligible": item.get("deletion_eligible", "No"),
                "sensitivity": item.get("sensitivity"),
                "captured_at": item.get("captured_at"),
                "sha256": item.get("sha256"),
                "size_bytes": item.get("size_bytes"),
                "container_path": str(container),
                "hdu_name": item.get("hdu_name"),
                "ocr_source": item.get("ocr_source", "none"),
                "ocr_text": item.get("ocr_text", item.get("search_text", "")),
                "search_text": item.get("search_text", "") or item.get("ocr_text", ""),
                "snippet": _make_snippet(text, [str(t) for t in query_terms if t]),
                "direct_fits_score": round(score, 4),
                "search_source": "direct_fits",
            }
        )

    if not rows and include_all_when_empty and structured is not None and not query.strip():
        return []

    rows.sort(key=lambda row: (float(row.get("direct_fits_score") or 0), str(row.get("captured_at") or "")), reverse=True)
    return rows[:limit]


def direct_search_entity(
    containers_dir: Path,
    entity_id: str,
    query: str = "",
    *,
    structured: Any | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    container = Path(containers_dir) / f"{entity_id}.fits"
    if not container.exists():
        # Backwards compatibility for split-snapshot archives: search all matching files.
        rows: list[dict[str, Any]] = []
        for path in sorted(Path(containers_dir).glob(f"{entity_id}*.fits")):
            rows.extend(direct_search_container(path, query, structured=structured, limit=limit))
        rows.sort(key=lambda row: float(row.get("direct_fits_score") or 0), reverse=True)
        return rows[:limit]
    return direct_search_container(container, query, structured=structured, limit=limit)
