from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ocr import extract_search_text


@dataclass
class ExtractedField:
    object_id: str
    field_name: str
    field_value: str
    field_type: str = "text"
    confidence: float = 0.5
    source: str = "rule_based"
    extracted_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if not data["extracted_at"]:
            data["extracted_at"] = utc_now_iso()
        return data


@dataclass
class ExtractionEvent:
    object_id: str
    event_type: str
    tool: str
    model: str
    status: str
    timestamp: str
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalise_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _first_match(patterns: list[str], text: str, flags: int = re.IGNORECASE | re.MULTILINE) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            if match.lastindex:
                return _normalise_whitespace(match.group(1))
            return _normalise_whitespace(match.group(0))
    return None


def _all_matches(pattern: str, text: str, flags: int = re.IGNORECASE | re.MULTILINE) -> list[str]:
    values: list[str] = []
    for match in re.finditer(pattern, text, flags):
        value = match.group(1) if match.lastindex else match.group(0)
        value = _normalise_whitespace(value)
        if value and value not in values:
            values.append(value)
    return values


def _field(object_id: str, name: str, value: str | None, field_type: str = "text", confidence: float = 0.7, source: str = "rule_based") -> dict[str, Any] | None:
    if not value:
        return None
    return ExtractedField(
        object_id=object_id,
        field_name=name,
        field_value=value,
        field_type=field_type,
        confidence=round(float(confidence), 2),
        source=source,
        extracted_at=utc_now_iso(),
    ).to_dict()


def extract_fields_from_text(
    *,
    object_id: str,
    text: str,
    filename: str = "",
    document_type: str = "",
    category: str = "",
) -> list[dict[str, Any]]:
    """Extract simple structured fields from OCR/search text.

    This intentionally uses deterministic rules for the POC. It gives us searchable
    structured fields inside the FITS file without making AI extraction a dependency.
    Later, this can be replaced or supplemented with AWS Textract, Azure Document
    Intelligence, local vision models, or a local LLM extraction pass.
    """
    fields: list[dict[str, Any]] = []
    source_text = text or ""
    combined = f"{filename}\n{document_type}\n{category}\n{source_text}"

    def add(name: str, value: str | None, field_type: str = "text", confidence: float = 0.7, source: str = "rule_based") -> None:
        item = _field(object_id, name, value, field_type, confidence, source)
        if item:
            fields.append(item)

    # Common dates in generated and ingested documents.
    dates = _all_matches(r"\b(20\d{2}[-/][01]?\d[-/][0-3]?\d|[0-3]?\d[-/][01]?\d[-/]20\d{2}|[0-3]?\d\s+[A-Z][a-z]+\s+20\d{2})\b", combined)
    for value in dates[:6]:
        add("detected_date", value, "date", 0.72)

    # Guernsey/Jersey/UK style jurisdictions and addresses in demo documents.
    jurisdiction = _first_match([
        r"\b(Guernsey|Jersey|United Kingdom|Isle of Man)\b",
        r"Jurisdiction\s*[:\-]\s*([^\n\r]+)",
    ], combined)
    add("detected_jurisdiction", jurisdiction, "jurisdiction", 0.82)

    address = _first_match([
        r"Address\s*[:\-]\s*([^\n\r]+)",
        r"Proof of Address\s*[:\-]\s*([^\n\r]+)",
        r"Residential Address\s*[:\-]\s*([^\n\r]+)",
        r"([A-Za-z0-9 ,.'\-]+(?:Road|Lane|Street|Avenue|Close|Estate|Court|House)[^\n\r]*)",
    ], combined)
    add("detected_address", address, "address", 0.75)

    name = _first_match([
        r"Customer\s*Name\s*[:\-]\s*([^\n\r]+)",
        r"Name\s*[:\-]\s*([^\n\r]+)",
        r"Account Holder\s*[:\-]\s*([^\n\r]+)",
    ], combined)
    add("detected_name", name, "person", 0.72)

    # Source-of-wealth/funds signals.
    sow_phrases = []
    phrase_patterns = [
        r"\b(property sale|sale proceeds|investment income|inheritance|salary|dividend income|business sale|savings|pension income)\b",
        r"source of wealth\s*[:\-]\s*([^\n\r]+)",
        r"source of funds\s*[:\-]\s*([^\n\r]+)",
    ]
    for pattern in phrase_patterns:
        for value in _all_matches(pattern, combined):
            if value.lower() not in [v.lower() for v in sow_phrases]:
                sow_phrases.append(value)
    for value in sow_phrases[:10]:
        add("source_of_wealth_signal", value, "financial_source", 0.8)

    risk = _first_match([
        r"Risk Rating\s*[:\-]\s*(Low|Medium|High)",
        r"\b(Low|Medium|High)\s+risk\b",
    ], combined)
    add("detected_risk_rating", risk, "risk_rating", 0.78)

    # Screening/compliance flags.
    for label, pattern in [
        ("pep_screening_signal", r"\b(PEP|politically exposed person)\b"),
        ("sanctions_screening_signal", r"\b(sanctions?|sanction screening)\b"),
        ("edd_signal", r"\b(enhanced due diligence|EDD|manual review)\b"),
        ("missing_evidence_signal", r"\b(missing|not provided|outstanding|required|requested)\b"),
    ]:
        if re.search(pattern, combined, re.IGNORECASE):
            add(label, "true", "boolean", 0.75)

    # Account / transaction references. Keep conservative and masked-friendly.
    for value in _all_matches(r"\b(?:Account|IBAN|Reference|Customer ID)\s*[:#\-]?\s*([A-Z0-9\-*]{4,34})\b", combined):
        add("detected_reference", value, "identifier", 0.65)

    # Evidence quality flags.
    ocr_len = len(source_text.strip())
    add("ocr_character_count", str(ocr_len), "integer", 0.99, "system")
    if ocr_len < 40 and filename.lower().endswith((".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff")):
        add("low_text_extraction_signal", "true", "boolean", 0.9, "system")

    # Deduplicate same field/value.
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in fields:
        key = (str(item.get("field_name", "")).lower(), str(item.get("field_value", "")).lower())
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def extract_document(
    *,
    path: Path,
    object_id: str,
    filename: str,
    document_type: str,
    category: str,
) -> dict[str, Any]:
    """Extract searchable text and structured facts for a source document."""
    started_at = utc_now_iso()
    try:
        text, source = extract_search_text(path)
        fields = extract_fields_from_text(
            object_id=object_id,
            text=text,
            filename=filename,
            document_type=document_type,
            category=category,
        )
        confidence = 0.0
        if text.strip():
            confidence = 0.75
        if source.startswith("sidecar"):
            confidence = 0.9
        elif source.startswith("pdf-text"):
            confidence = 0.82
        elif source.startswith("ocr"):
            confidence = 0.68
        elif source == "direct-text":
            confidence = 0.88
        event = ExtractionEvent(
            object_id=object_id,
            event_type="DOCUMENT_EXTRACTION",
            tool=source,
            model="deterministic_rules_v1",
            status="PASS",
            timestamp=started_at,
            error="",
        ).to_dict()
        return {
            "object_id": object_id,
            "text": text,
            "ocr_source": source,
            "confidence": round(confidence, 2),
            "fields": fields,
            "event": event,
            "fields_json": json.dumps(fields, ensure_ascii=False),
        }
    except Exception as exc:  # pragma: no cover - defensive safety for demo ingestion
        event = ExtractionEvent(
            object_id=object_id,
            event_type="DOCUMENT_EXTRACTION",
            tool="unknown",
            model="deterministic_rules_v1",
            status="FAIL",
            timestamp=started_at,
            error=str(exc),
        ).to_dict()
        return {
            "object_id": object_id,
            "text": "",
            "ocr_source": "error",
            "confidence": 0.0,
            "fields": [],
            "event": event,
            "fields_json": "[]",
        }


def summarise_extraction_fields(fields: list[dict[str, Any]]) -> dict[str, Any]:
    by_name: dict[str, int] = {}
    low_confidence = 0
    for item in fields:
        name = str(item.get("field_name", "unknown"))
        by_name[name] = by_name.get(name, 0) + 1
        try:
            if float(item.get("confidence", 0)) < 0.7:
                low_confidence += 1
        except Exception:
            pass
    return {
        "field_count": len(fields),
        "field_counts": by_name,
        "low_confidence_field_count": low_confidence,
    }
