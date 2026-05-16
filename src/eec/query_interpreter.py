from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .local_llm import get_lm_studio_client, get_query_model, lm_studio_status
from .search import advanced_search_index

ALLOWED_INTENTS = {
    "customer_evidence_question",
    "customer_evidence_retrieval",
    "customer_discovery",
    "cohort_evidence_retrieval",
    "regulatory_pack_request",
    "retention_legal_hold_review",
    "archive_health_query",
    "general_archive_search",
    "missing_evidence_review",
    "evidence_completeness_review",
}

ALLOWED_RESULT_TYPES = {
    "evidence",
    "customers",
    "evidence_grouped_by_customer",
    "retention_report",
    "archive_health",
    "completeness_report",
}

JURISDICTION_MAP = {
    "guernsey": "Guernsey",
    "jersey": "Jersey",
    "uk": "United Kingdom",
    "united kingdom": "United Kingdom",
    "isle of man": "Isle of Man",
}

RISK_MAP = {
    "high risk": "High",
    "high-risk": "High",
    "medium risk": "Medium",
    "medium-risk": "Medium",
    "low risk": "Low",
    "low-risk": "Low",
}

CATEGORY_KEYWORDS = {
    "Due Diligence": ["cdd", "due diligence", "kyc", "source of wealth", "source of funds", "screening", "pep", "sanctions"],
    "Identity": ["passport", "identity", "id verification", "who the customer is"],
    "Address": ["proof of address", "utility bill", "address"],
    "Statements": ["statement", "monthly statement", "bank statement"],
    "Transactions": ["transaction", "payment", "transfer", "money flow", "money trail"],
    "Correspondence": ["email", "correspondence", "communications", "follow up", "letter"],
    "Complaints": ["complaint", "dispute"],
    "Legal": ["legal", "legal hold", "disclosure", "sar", "subject access"],
}

DOCUMENT_HINTS = {
    "Source of Wealth": ["source of wealth", "wealth", "where did the customer money come from"],
    "Source of Funds": ["source of funds", "funds", "funding", "money come from"],
    "CDD Review": ["cdd", "due diligence", "kyc", "review"],
    "Passport": ["passport", "identity"],
    "Proof of Address": ["proof of address", "utility bill", "address"],
    "Bank Statement": ["statement", "bank statement", "monthly statement"],
}


SNAPSHOT_HINTS = {
    "ONBOARDING": ["onboarding", "account opening", "opening documentation", "application pack"],
    "CDD_REVIEW_2026": ["cdd", "due diligence", "kyc", "aml", "source of wealth", "source of funds", "screening"],
    "STATEMENTS_2026_Q1": ["statement", "statements", "bank statement", "monthly statement"],
    "CORRESPONDENCE_2026": ["email", "correspondence", "communications", "letter"],
    "TRANSACTIONS_2026_Q1": ["transaction", "transactions", "payment", "transfer", "money flow", "money trail"],
    "LEGAL_DISCLOSURE": ["legal", "disclosure", "complaint", "dispute", "sar", "subject access"],
}

DOCUMENT_TYPE_ALIASES = {
    "Proof of Address": ["Proof of Address", "utility bill", "address evidence"],
    "Source of Wealth": ["Source of Wealth / CDD", "source of wealth", "wealth evidence"],
    "Source of Funds": ["Source of Wealth / CDD", "source of funds", "funding evidence"],
    "CDD Review": ["Source of Wealth / CDD", "CDD", "cdd_risk_review"],
    "Passport": ["Identity Evidence", "passport", "identity evidence"],
    "Bank Statement": ["Monthly Statement", "statement"],
}

CATEGORY_ALIASES = {
    "Address": ["Address", "Due Diligence"],
    "Identity": ["Identity", "Due Diligence"],
    "Due Diligence": ["Due Diligence"],
    "Statements": ["Statement", "Statements"],
    "Transactions": ["Transaction Extract", "Transactions"],
    "Correspondence": ["Correspondence"],
    "Complaints": ["Complaints", "Correspondence"],
    "Legal": ["Legal", "Correspondence", "Due Diligence"],
}


SUPPORTED_QUERY_CAPABILITIES: dict[str, dict[str, Any]] = {
    "customer_evidence_question": {
        "description": "Answer a question about one selected customer using retrieved evidence.",
        "intent": "customer_evidence_question",
        "result_type": "evidence",
        "requires_selected_entity": True,
        "supports_filters": ["entity_id", "evidence_category", "document_type", "snapshot_id", "source_system"],
        "default_summary": True,
    },
    "customer_evidence_retrieval": {
        "description": "Retrieve evidence for one selected customer without necessarily producing an answer.",
        "intent": "customer_evidence_retrieval",
        "result_type": "evidence",
        "requires_selected_entity": True,
        "supports_filters": ["entity_id", "evidence_category", "document_type", "snapshot_id", "source_system"],
        "default_summary": False,
    },
    "customer_discovery": {
        "description": "Find customers matching risk, jurisdiction or other customer-level filters.",
        "intent": "customer_discovery",
        "result_type": "customers",
        "requires_selected_entity": False,
        "supports_filters": ["risk_rating", "jurisdiction"],
        "default_summary": False,
    },
    "missing_evidence_review": {
        "description": "Find customers in a cohort who are missing a required evidence type.",
        "intent": "missing_evidence_review",
        "result_type": "customers",
        "requires_selected_entity": False,
        "supports_filters": ["risk_rating", "jurisdiction", "evidence_category", "document_type", "snapshot_id"],
        "default_summary": False,
    },

    "evidence_completeness_review": {
        "description": "Evaluate customer files against an evidence completeness ruleset and show missing mandatory evidence.",
        "intent": "evidence_completeness_review",
        "result_type": "completeness_report",
        "requires_selected_entity": False,
        "supports_filters": ["entity_id", "risk_rating", "jurisdiction", "document_type"],
        "default_summary": True,
    },
    "cohort_evidence_retrieval": {
        "description": "Find evidence for a cohort and group it by customer.",
        "intent": "cohort_evidence_retrieval",
        "result_type": "evidence_grouped_by_customer",
        "requires_selected_entity": False,
        "supports_filters": ["risk_rating", "jurisdiction", "evidence_category", "document_type", "snapshot_id", "source_system"],
        "default_summary": False,
        "group_by": "entity_id",
    },
    "regulatory_pack_request": {
        "description": "Find evidence intended for export as a regulatory or audit evidence pack.",
        "intent": "regulatory_pack_request",
        "result_type": "evidence_grouped_by_customer",
        "requires_selected_entity": False,
        "supports_filters": ["entity_id", "risk_rating", "jurisdiction", "evidence_category", "document_type", "snapshot_id", "source_system"],
        "default_summary": True,
        "group_by": "entity_id",
    },
    "retention_legal_hold_review": {
        "description": "Review records by retention, legal hold or deletion eligibility.",
        "intent": "retention_legal_hold_review",
        "result_type": "retention_report",
        "requires_selected_entity": False,
        "supports_filters": ["risk_rating", "jurisdiction", "retention_class", "legal_hold_status"],
        "default_summary": False,
    },
    "archive_health_query": {
        "description": "Review archive integrity and validation failures.",
        "intent": "archive_health_query",
        "result_type": "archive_health",
        "requires_selected_entity": False,
        "supports_filters": [],
        "default_summary": False,
    },
    "general_archive_search": {
        "description": "Fallback evidence search across the archive.",
        "intent": "general_archive_search",
        "result_type": "evidence",
        "requires_selected_entity": False,
        "supports_filters": ["entity_id", "risk_rating", "jurisdiction", "evidence_category", "document_type", "snapshot_id", "source_system"],
        "default_summary": False,
    },
}


def query_capability_matrix() -> dict[str, dict[str, Any]]:
    """Return the supported query capability matrix used by the interpreter and UI."""
    return SUPPORTED_QUERY_CAPABILITIES


def _capability_from_intent(intent: str, *, missing_evidence: bool = False) -> str:
    if missing_evidence:
        return "missing_evidence_review"
    if intent in SUPPORTED_QUERY_CAPABILITIES:
        return intent
    return "general_archive_search"


def _apply_capability_defaults(structured: "StructuredArchiveQuery") -> "StructuredArchiveQuery":
    """Align interpreted intent, result type and summary behaviour to supported capabilities."""
    capability_id = _capability_from_intent(structured.intent, missing_evidence=structured.missing_evidence)
    capability = SUPPORTED_QUERY_CAPABILITIES.get(capability_id, SUPPORTED_QUERY_CAPABILITIES["general_archive_search"])

    structured.capability = capability_id
    structured.intent = str(capability["intent"])
    structured.result_type = str(capability["result_type"])
    structured.requires_summary = bool(structured.requires_summary or capability.get("default_summary", False))
    if capability.get("group_by") and not structured.group_by:
        structured.group_by = str(capability["group_by"])

    # A selected customer should always scope customer-level evidence questions/retrieval.
    if capability.get("requires_selected_entity") and not structured.entity_id:
        structured.intent = "customer_evidence_question"
        structured.result_type = "evidence"
        structured.capability = "customer_evidence_question"

    return structured


@dataclass
class StructuredArchiveQuery:
    raw_query: str
    capability: str = "general_archive_search"
    intent: str = "general_archive_search"
    result_type: str = "evidence"
    entity_id: str | None = None
    jurisdiction: str | None = None
    risk_rating: str | None = None
    evidence_category: str | None = None
    document_type: str | None = None
    snapshot_id: str | None = None
    snapshot_type: str | None = None
    missing_evidence: bool = False
    source_system: str | None = None
    retention_class: str | None = None
    legal_hold_status: str | None = None
    sensitivity: str | None = None
    semantic_query: str | None = None
    keyword_terms: list[str] = field(default_factory=list)
    requires_summary: bool = False
    requires_evidence: bool = True
    group_by: str | None = None
    limit: int = 25
    interpretation_source: str = "rules"
    confidence: float = 0.6

    def filters(self) -> dict[str, list[str]]:
        mapping = {
            "entity_id": self.entity_id,
            "jurisdiction": self.jurisdiction,
            "risk_rating": self.risk_rating,
            "category": self.evidence_category,
            "document_type": self.document_type,
            "snapshot_id": self.snapshot_id,
            "snapshot_type": self.snapshot_type,
            "source_system": self.source_system,
            "retention_class": self.retention_class,
            "legal_hold_status": self.legal_hold_status,
            "sensitivity": self.sensitivity,
        }
        return {key: [value] for key, value in mapping.items() if value}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalise_query_text(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip().lower())


def _first_match(text: str, mapping: dict[str, str]) -> str | None:
    for needle, value in mapping.items():
        if needle in text:
            return value
    return None


def _category_from_text(text: str) -> str | None:
    for category, needles in CATEGORY_KEYWORDS.items():
        if any(needle in text for needle in needles):
            return category
    return None


def _document_type_from_text(text: str) -> str | None:
    for document_type, needles in DOCUMENT_HINTS.items():
        if any(needle in text for needle in needles):
            return document_type
    return None


def _snapshot_id_from_text(text: str) -> str | None:
    for snapshot_id, needles in SNAPSHOT_HINTS.items():
        if any(needle in text for needle in needles):
            return snapshot_id
    return None


def _is_missing_evidence_query(text: str) -> bool:
    return any(phrase in text for phrase in [
        "do not have", "don't have", "does not have", "without", "missing",
        "no proof", "no evidence", "lacking", "not provided"
    ])


def _fallback_interpret(query: str, selected_entity_id: str | None = None, limit: int = 25) -> StructuredArchiveQuery:
    text = _normalise_query_text(query)
    risk = _first_match(text, RISK_MAP)
    jurisdiction = _first_match(text, JURISDICTION_MAP)
    category = _category_from_text(text)
    document_type = _document_type_from_text(text)
    snapshot_id = _snapshot_id_from_text(text)
    missing_evidence = _is_missing_evidence_query(text)

    asks_customer_list = any(phrase in text for phrase in [
        "show me customers", "show me customer", "find customers", "find customer",
        "which customers", "customer who", "customers who", "customers in",
        "clients who", "clients in", "high risk clients", "high-risk clients"
    ])
    asks_evidence = any(phrase in text for phrase in [
        "show me the", "show me cdd", "show me evidence", "documents", "documentation",
        "evidence", "cdd", "source of", "what is", "summarise", "summarize", "proof of"
    ])
    asks_retention = "retention" in text or "legal hold" in text or "deletion eligible" in text or "past retention" in text
    asks_health = "integrity" in text or "corrupt" in text or "archive health" in text or "failed container" in text
    asks_completeness = any(phrase in text for phrase in [
        "complete", "completeness", "incomplete", "mandatory evidence", "missing mandatory", "missing kyc", "missing cdd", "file complete", "onboarding file complete"
    ])

    if asks_health:
        return StructuredArchiveQuery(
            raw_query=query,
            intent="archive_health_query",
            result_type="archive_health",
            requires_evidence=False,
            requires_summary=False,
            semantic_query=query,
            keyword_terms=[query],
            limit=limit,
        )

    if asks_retention:
        return StructuredArchiveQuery(
            raw_query=query,
            intent="retention_legal_hold_review",
            result_type="retention_report",
            legal_hold_status="On Hold" if "legal hold" in text else None,
            requires_evidence=True,
            requires_summary=False,
            semantic_query=query,
            keyword_terms=[query],
            limit=limit,
        )

    if asks_completeness:
        return StructuredArchiveQuery(
            raw_query=query,
            intent="evidence_completeness_review",
            result_type="completeness_report",
            entity_id=selected_entity_id,
            jurisdiction=jurisdiction,
            risk_rating=risk,
            evidence_category=category,
            document_type=document_type,
            semantic_query=query,
            keyword_terms=[query, *(filter(None, [category, document_type]))],
            requires_summary=True,
            requires_evidence=False,
            limit=limit,
        )

    if selected_entity_id:
        intent = "customer_evidence_question" if ("?" in query or text.startswith(("what", "summarise", "summarize", "does", "is", "are", "where"))) else "customer_evidence_retrieval"
        return StructuredArchiveQuery(
            raw_query=query,
            intent=intent,
            result_type="evidence",
            entity_id=selected_entity_id,
            evidence_category=category,
            document_type=document_type,
            snapshot_id=snapshot_id,
            missing_evidence=missing_evidence,
            semantic_query=query,
            keyword_terms=[query, *(filter(None, [category, document_type]))],
            requires_summary=intent == "customer_evidence_question" or text.startswith(("what", "where", "summarise", "summarize")),
            requires_evidence=True,
            limit=limit,
        )

    if asks_customer_list and (missing_evidence or not (category or document_type or snapshot_id or "cdd" in text or "evidence" in text)):
        return StructuredArchiveQuery(
            raw_query=query,
            intent="customer_discovery",
            result_type="customers",
            jurisdiction=jurisdiction,
            risk_rating=risk,
            evidence_category=category,
            document_type=document_type,
            snapshot_id=snapshot_id,
            missing_evidence=missing_evidence,
            semantic_query=query,
            keyword_terms=[query],
            requires_summary=True,
            requires_evidence=False,
            limit=limit,
        )

    if asks_customer_list or ((risk or jurisdiction) and (category or document_type or snapshot_id or asks_evidence)):
        return StructuredArchiveQuery(
            raw_query=query,
            intent="cohort_evidence_retrieval",
            result_type="evidence_grouped_by_customer",
            jurisdiction=jurisdiction,
            risk_rating=risk,
            evidence_category=category,
            document_type=document_type,
            snapshot_id=snapshot_id,
            missing_evidence=missing_evidence,
            semantic_query=query,
            keyword_terms=[query, *(filter(None, [category, document_type]))],
            requires_summary=False,
            requires_evidence=True,
            group_by="entity_id",
            limit=limit,
        )

    return StructuredArchiveQuery(
        raw_query=query,
        intent="general_archive_search",
        result_type="evidence",
        jurisdiction=jurisdiction,
        risk_rating=risk,
        evidence_category=category,
        document_type=document_type,
        snapshot_id=snapshot_id,
        missing_evidence=missing_evidence,
        semantic_query=query,
        keyword_terms=[query, *(filter(None, [category, document_type]))],
        requires_summary=False,
        requires_evidence=True,
        limit=limit,
    )


def _extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _validate_interpreted_payload(payload: dict[str, Any], fallback: StructuredArchiveQuery, selected_entity_id: str | None, limit: int) -> StructuredArchiveQuery:
    intent = payload.get("intent") if payload.get("intent") in ALLOWED_INTENTS else fallback.intent
    result_type = payload.get("result_type") if payload.get("result_type") in ALLOWED_RESULT_TYPES else fallback.result_type
    scope = payload.get("scope") or {}
    evidence = payload.get("evidence") or {}
    keyword_terms = payload.get("keyword_terms") or payload.get("terms") or fallback.keyword_terms
    if isinstance(keyword_terms, str):
        keyword_terms = [keyword_terms]
    query = payload.get("semantic_query") or payload.get("question") or fallback.semantic_query or fallback.raw_query
    entity_id = scope.get("entity_id") or payload.get("entity_id") or selected_entity_id or fallback.entity_id

    out = StructuredArchiveQuery(
        raw_query=fallback.raw_query,
        intent=intent,
        result_type=result_type,
        entity_id=entity_id,
        jurisdiction=scope.get("jurisdiction") or payload.get("jurisdiction") or fallback.jurisdiction,
        risk_rating=scope.get("risk_rating") or payload.get("risk_rating") or fallback.risk_rating,
        evidence_category=evidence.get("category") or payload.get("evidence_category") or fallback.evidence_category,
        document_type=evidence.get("document_type") or payload.get("document_type") or fallback.document_type,
        snapshot_id=evidence.get("snapshot_id") or payload.get("snapshot_id") or fallback.snapshot_id,
        snapshot_type=evidence.get("snapshot_type") or payload.get("snapshot_type") or fallback.snapshot_type,
        missing_evidence=bool(payload.get("missing_evidence", fallback.missing_evidence)),
        source_system=evidence.get("source_system") or payload.get("source_system") or fallback.source_system,
        retention_class=evidence.get("retention_class") or payload.get("retention_class") or fallback.retention_class,
        legal_hold_status=evidence.get("legal_hold_status") or payload.get("legal_hold_status") or fallback.legal_hold_status,
        sensitivity=evidence.get("sensitivity") or payload.get("sensitivity") or fallback.sensitivity,
        semantic_query=query,
        keyword_terms=[str(term) for term in keyword_terms if str(term).strip()][:12],
        requires_summary=bool(payload.get("requires_summary", fallback.requires_summary)),
        requires_evidence=bool(payload.get("requires_evidence", fallback.requires_evidence)),
        group_by=payload.get("group_by") or fallback.group_by,
        limit=int(payload.get("limit") or limit or fallback.limit),
        interpretation_source="local_llm",
        confidence=float(payload.get("confidence") or 0.8),
    )

    # Keep common language variants aligned with generated demo data.
    if out.jurisdiction:
        out.jurisdiction = JURISDICTION_MAP.get(out.jurisdiction.lower(), out.jurisdiction)
    if out.risk_rating:
        out.risk_rating = RISK_MAP.get(out.risk_rating.lower(), out.risk_rating)
    return out


def interpret_archive_query(query: str, selected_entity_id: str | None = None, *, use_local_ai: bool = True, limit: int = 25) -> StructuredArchiveQuery:
    fallback = _fallback_interpret(query, selected_entity_id=selected_entity_id, limit=limit)
    fallback = _apply_capability_defaults(fallback)
    if not use_local_ai or not query.strip():
        return fallback
    status = lm_studio_status()
    if not status.get("available"):
        return fallback
    try:
        client = get_lm_studio_client()
        prompt = {
            "user_query": query,
            "selected_entity_id": selected_entity_id,
            "allowed_capabilities": query_capability_matrix(),
            "allowed_intents": sorted(ALLOWED_INTENTS),
            "allowed_result_types": sorted(ALLOWED_RESULT_TYPES),
            "allowed_risk_ratings": ["Low", "Medium", "High"],
            "allowed_jurisdictions": ["Guernsey", "Jersey", "United Kingdom", "Isle of Man", "Other"],
            "allowed_evidence_categories": sorted(CATEGORY_KEYWORDS.keys()),
            "instructions": (
                "Return only valid JSON. Do not include prose. The LLM must not generate SQL. For questions about complete files, incomplete onboarding, missing mandatory evidence or evidence checklists, use intent=evidence_completeness_review and result_type=completeness_report. "
                "Set entity_id to the selected_entity_id when a selected customer is in scope. "
                "Use result_type=customers for customer lists, evidence for customer-specific evidence, "
                "and evidence_grouped_by_customer for cohort evidence retrieval. "
                "For requests such as 'customers who do not have proof of address', set intent='missing_evidence_review', "
                "missing_evidence=true, result_type=customers, and evidence.document_type='Proof of Address'. "
                "For onboarding documentation, set evidence.snapshot_id='ONBOARDING'."
            ),
            "schema": {
                "intent": "customer_evidence_question | customer_evidence_retrieval | customer_discovery | missing_evidence_review | evidence_completeness_review | cohort_evidence_retrieval | regulatory_pack_request | retention_legal_hold_review | archive_health_query | general_archive_search",
                "result_type": "evidence | customers | evidence_grouped_by_customer | retention_report | archive_health",
                "scope": {"entity_id": None, "jurisdiction": None, "risk_rating": None},
                "evidence": {"category": None, "document_type": None, "snapshot_id": None, "snapshot_type": None, "source_system": None, "retention_class": None, "legal_hold_status": None},
                "missing_evidence": False,
                "semantic_query": query,
                "keyword_terms": [],
                "requires_summary": False,
                "requires_evidence": True,
                "group_by": None,
                "limit": limit,
                "confidence": 0.0,
            },
        }
        response = client.chat.completions.create(
            model=get_query_model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You convert natural-language regulated archive searches into strict JSON. "
                        "Return only valid JSON. Never generate SQL."
                    ),
                },
                {"role": "user", "content": json.dumps(prompt, indent=2)},
            ],
            temperature=0.1,
            max_tokens=900,
        )
        message = response.choices[0].message
        text = getattr(message, "content", None) or getattr(message, "reasoning_content", None) or ""
        payload = _extract_json(text)
        if not payload:
            return fallback
        return _apply_capability_defaults(_validate_interpreted_payload(payload, fallback, selected_entity_id, limit))
    except Exception:
        return fallback


def _base_evidence_query() -> str:
    return """
        SELECT o.object_id, o.entity_id, o.container_id, o.snapshot_id, o.snapshot_type,
               e.display_name, e.jurisdiction, e.risk_rating, e.occupation,
               o.category, o.document_type, o.filename, o.relative_path, o.mime_type,
               o.source_system, o.retention_class, o.retention_until, o.legal_hold_status,
               o.deletion_eligible, o.sensitivity, o.captured_at, o.sha256, o.size_bytes,
               o.container_path, o.hdu_name, o.ocr_source, o.search_text,
               substr(o.search_text, 1, 300) AS snippet
        FROM objects o
        JOIN entities e ON e.entity_id = o.entity_id
    """


def _build_where(structured: StructuredArchiveQuery, *, include_text: bool = False) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    mapping = {
        "o.entity_id": structured.entity_id,
        "e.jurisdiction": structured.jurisdiction,
        "e.risk_rating": structured.risk_rating,
        "o.snapshot_id": structured.snapshot_id,
        "o.snapshot_type": structured.snapshot_type,
        "o.source_system": structured.source_system,
        "o.retention_class": structured.retention_class,
        "o.legal_hold_status": structured.legal_hold_status,
        "o.sensitivity": structured.sensitivity,
    }
    for column, value in mapping.items():
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)

    # Evidence categories and document types are interpreted from user language and
    # are intentionally broader than the stored demo taxonomy. For example,
    # "proof of address" is stored as category "Due Diligence" with document type
    # "Proof of Address", so applying category="Address" as an exact filter would
    # incorrectly return no rows.
    if structured.document_type:
        aliases = DOCUMENT_TYPE_ALIASES.get(structured.document_type, [structured.document_type])
        doc_clauses = []
        for alias in aliases:
            doc_clauses.append("(lower(o.document_type) LIKE ? OR lower(o.filename) LIKE ? OR lower(o.search_text) LIKE ?)")
            like = f"%{alias.lower()}%"
            params.extend([like, like, like])
        clauses.append("(" + " OR ".join(doc_clauses) + ")")
    elif structured.evidence_category:
        aliases = CATEGORY_ALIASES.get(structured.evidence_category, [structured.evidence_category])
        cat_clauses = []
        for alias in aliases:
            cat_clauses.append("(lower(o.category) LIKE ? OR lower(o.document_type) LIKE ? OR lower(o.search_text) LIKE ?)")
            like = f"%{alias.lower()}%"
            params.extend([like, like, like])
        clauses.append("(" + " OR ".join(cat_clauses) + ")")

    if include_text and structured.keyword_terms:
        text_clauses = []
        for term in structured.keyword_terms[:6]:
            term = str(term).strip()
            if term:
                text_clauses.append("(lower(o.search_text) LIKE ? OR lower(o.filename) LIKE ? OR lower(o.document_type) LIKE ?)")
                like = f"%{term.lower()}%"
                params.extend([like, like, like])
        if text_clauses:
            clauses.append("(" + " OR ".join(text_clauses) + ")")
    if not clauses:
        return "", params
    return " WHERE " + " AND ".join(clauses), params


def discover_customers(sqlite_path: Path, structured: StructuredArchiveQuery) -> list[dict[str, Any]]:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        clauses: list[str] = []
        params: list[Any] = []
        if structured.jurisdiction:
            clauses.append("e.jurisdiction = ?")
            params.append(structured.jurisdiction)
        if structured.risk_rating:
            clauses.append("e.risk_rating = ?")
            params.append(structured.risk_rating)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""

        having = ""
        join_params: list[Any] = []
        if structured.missing_evidence and (structured.document_type or structured.evidence_category or structured.snapshot_id):
            # Return customers in the cohort where no matching evidence exists.
            missing_clauses = ["mo.entity_id = e.entity_id"]
            if structured.snapshot_id:
                missing_clauses.append("mo.snapshot_id = ?")
                join_params.append(structured.snapshot_id)
            if structured.document_type:
                aliases = DOCUMENT_TYPE_ALIASES.get(structured.document_type, [structured.document_type])
                alias_clauses = []
                for alias in aliases:
                    # Missing-evidence checks must only consider evidence identity fields.
                    # Do not match against search_text here, because a CDD review can say
                    # "proof of address is missing" and would otherwise be mistaken for
                    # proof-of-address evidence.
                    alias_clauses.append("(lower(mo.document_type) LIKE ? OR lower(mo.filename) LIKE ?)")
                    like = f"%{alias.lower()}%"
                    join_params.extend([like, like])
                missing_clauses.append("(" + " OR ".join(alias_clauses) + ")")
            elif structured.evidence_category:
                aliases = CATEGORY_ALIASES.get(structured.evidence_category, [structured.evidence_category])
                alias_clauses = []
                for alias in aliases:
                    alias_clauses.append("(lower(mo.category) LIKE ? OR lower(mo.document_type) LIKE ?)")
                    like = f"%{alias.lower()}%"
                    join_params.extend([like, like])
                missing_clauses.append("(" + " OR ".join(alias_clauses) + ")")
            having = " AND NOT EXISTS (SELECT 1 FROM objects mo WHERE " + " AND ".join(missing_clauses) + ")"

        sql = f"""
            SELECT e.entity_id, e.display_name, e.jurisdiction, e.risk_rating, e.occupation,
                   COUNT(o.object_id) AS evidence_count,
                   COALESCE(SUM(o.size_bytes), 0) AS payload_bytes,
                   MAX(o.captured_at) AS last_evidence_date
            FROM entities e
            LEFT JOIN objects o ON o.entity_id = e.entity_id
            {where + having if where else (" WHERE 1=1" + having if having else "")}
            GROUP BY e.entity_id, e.display_name, e.jurisdiction, e.risk_rating, e.occupation
            ORDER BY e.risk_rating DESC, e.entity_id
            LIMIT ?
        """
        rows = conn.execute(sql, [*params, *join_params, structured.limit]).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def retrieve_structured_evidence(sqlite_path: Path, structured: StructuredArchiveQuery) -> list[dict[str, Any]]:
    # First use deterministic filters and text hints. Fall back to semantic/FTS if useful.
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        where, params = _build_where(structured, include_text=True)
        sql = _base_evidence_query() + where + " ORDER BY e.entity_id, o.snapshot_id, o.category, o.document_type LIMIT ?"
        rows = [dict(row) for row in conn.execute(sql, [*params, structured.limit]).fetchall()]
    finally:
        conn.close()
    if rows:
        return _dedupe_rows(rows, structured.limit)

    filters = structured.filters()
    query = structured.semantic_query or structured.raw_query
    try:
        rows = advanced_search_index(sqlite_path, query=query, filters=filters, limit=structured.limit, mode="semantic")
        if rows:
            return _dedupe_rows(rows, structured.limit)
    except Exception:
        pass
    try:
        rows = advanced_search_index(sqlite_path, query=query, filters=filters, limit=structured.limit, mode="keyword")
        return _dedupe_rows(rows, structured.limit)
    except Exception:
        return []


def retention_structured_rows(sqlite_path: Path, structured: StructuredArchiveQuery) -> list[dict[str, Any]]:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        clauses = []
        params: list[Any] = []
        if structured.legal_hold_status:
            clauses.append("o.legal_hold_status = ?")
            params.append(structured.legal_hold_status)
        if structured.risk_rating:
            clauses.append("e.risk_rating = ?")
            params.append(structured.risk_rating)
        if structured.jurisdiction:
            clauses.append("e.jurisdiction = ?")
            params.append(structured.jurisdiction)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = conn.execute(
            _base_evidence_query() + where + " ORDER BY o.retention_until, e.entity_id LIMIT ?",
            [*params, structured.limit],
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _dedupe_rows(rows: Iterable[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = (str(row.get("entity_id", "")), str(row.get("filename", "")), str(row.get("document_type", "")))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def group_evidence_by_customer(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("entity_id")), []).append(row)
    return grouped


def execute_structured_query(sqlite_path: Path, structured: StructuredArchiveQuery) -> dict[str, Any]:
    if structured.result_type == "completeness_report" or structured.intent == "evidence_completeness_review":
        from .rulesets import evaluate_completeness
        report = evaluate_completeness(
            sqlite_path,
            root=sqlite_path.parent.parent,
            entity_id=structured.entity_id,
            risk_rating=structured.risk_rating,
            jurisdiction=structured.jurisdiction,
            missing_item=structured.document_type if structured.missing_evidence else None,
        )
        return {"type": "completeness_report", "rows": report.get("rows", []), "grouped": None, "summary": report.get("summary", {}), "ruleset": report.get("ruleset", {})}
    if structured.missing_evidence:
        rows = discover_customers(sqlite_path, structured)
        return {"type": "customers", "rows": rows, "grouped": None}
    if structured.result_type == "customers" or structured.intent == "customer_discovery":
        rows = discover_customers(sqlite_path, structured)
        return {"type": "customers", "rows": rows, "grouped": None}
    if structured.result_type == "retention_report" or structured.intent == "retention_legal_hold_review":
        rows = retention_structured_rows(sqlite_path, structured)
        return {"type": "retention_report", "rows": rows, "grouped": None}
    rows = retrieve_structured_evidence(sqlite_path, structured)
    if structured.result_type == "evidence_grouped_by_customer" or structured.group_by == "entity_id":
        return {"type": "evidence_grouped_by_customer", "rows": rows, "grouped": group_evidence_by_customer(rows)}
    return {"type": "evidence", "rows": rows, "grouped": None}
