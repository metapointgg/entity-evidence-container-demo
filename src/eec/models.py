from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List


@dataclass
class PayloadRecord:
    object_id: str
    entity_id: str
    category: str
    document_type: str
    filename: str
    relative_path: str
    mime_type: str
    source_system: str
    captured_at: str
    retention_class: str
    sensitivity: str
    sha256: str
    size_bytes: int
    hdu_name: str
    search_text: str = ""
    ocr_text: str = ""
    ocr_source: str = "none"
    description: str = ""
    snapshot_id: str = "FULL"
    snapshot_type: str = "Full Entity Archive"
    container_version: int = 1
    retention_until: str = ""
    legal_hold_status: str = "None"
    deletion_eligible: str = "No"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProvenanceRecord:
    event_id: str
    entity_id: str
    event_type: str
    source_system: str
    actor: str
    timestamp: str
    details: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationResult:
    container_path: str
    entity_id: str
    status: str
    checked_payloads: int
    failed_payloads: int
    failures: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
