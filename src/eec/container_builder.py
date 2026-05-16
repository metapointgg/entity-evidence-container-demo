from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

import numpy as np
from astropy.io import fits

from .models import PayloadRecord, ProvenanceRecord
from .ocr import extract_search_text
from .utils import guess_mime, read_json, safe_rel_path, sha256_bytes, utc_now_iso


def _json_hdu(name: str, value) -> fits.ImageHDU:
    data = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
    arr = np.frombuffer(data, dtype=np.uint8)
    hdu = fits.ImageHDU(data=arr, name=name)
    hdu.header["MIMETYPE"] = "application/json"
    hdu.header["ENCODING"] = "utf-8"
    hdu.header["SHA256"] = sha256_bytes(data)
    return hdu


def _payload_hdu(name: str, data: bytes, record: PayloadRecord) -> fits.ImageHDU:
    arr = np.frombuffer(data, dtype=np.uint8)
    hdu = fits.ImageHDU(data=arr, name=name)
    hdu.header["OBJID"] = record.object_id[:68]
    hdu.header["MIMETYPE"] = record.mime_type[:68]
    hdu.header["SHA256"] = record.sha256
    hdu.header["SIZE"] = record.size_bytes
    hdu.header["FILENAME"] = Path(record.filename).name[:68]
    hdu.header["SNAPSHOT"] = record.snapshot_id[:68]
    hdu.header["LEGALHLD"] = record.legal_hold_status[:68]
    return hdu


def _categorise(path: Path) -> Dict[str, str]:
    parts = set(p.lower() for p in path.parts)
    name = path.name.lower()
    if "statements" in parts:
        return {"category": "Statement", "document_type": "Monthly Statement", "retention_class": "Statements", "source_system": "Statement Engine", "sensitivity": "Confidential"}
    if "emails" in parts:
        return {"category": "Correspondence", "document_type": "Email", "retention_class": "Correspondence", "source_system": "Email Archive", "sensitivity": "Confidential"}
    if "extracts" in parts:
        return {"category": "Transaction Extract", "document_type": "Transaction CSV", "retention_class": "Transactional", "source_system": "Core Banking", "sensitivity": "Confidential"}
    if "metadata" in parts:
        return {"category": "Metadata", "document_type": "Structured Metadata", "retention_class": "Governance", "source_system": "Salesforce FSC", "sensitivity": "Internal"}
    if "large_evidence" in parts:
        return {"category": "Large Evidence", "document_type": "Bulk Binary Evidence", "retention_class": "Archive", "source_system": "Legacy Archive", "sensitivity": "Confidential"}
    if "passport" in name:
        return {"category": "Due Diligence", "document_type": "Identity Evidence", "retention_class": "CDD", "source_system": "Salesforce FSC", "sensitivity": "Restricted"}
    if "source_of_wealth" in name or "cdd" in name:
        return {"category": "Due Diligence", "document_type": "Source of Wealth / CDD", "retention_class": "CDD", "source_system": "AML Screening Platform", "sensitivity": "Restricted"}
    if "proof_of_address" in name:
        return {"category": "Due Diligence", "document_type": "Proof of Address", "retention_class": "CDD", "source_system": "Salesforce FSC", "sensitivity": "Restricted"}
    return {"category": "Document", "document_type": "Business Document", "retention_class": "Customer File", "source_system": "Salesforce FSC", "sensitivity": "Confidential"}


def _retention_metadata(retention_class: str, sensitivity: str, snapshot_id: str) -> Dict[str, str]:
    today = date.today()
    years = {
        "CDD": 7,
        "Statements": 6,
        "Correspondence": 6,
        "Transactional": 7,
        "Governance": 10,
        "Archive": 25,
        "Customer File": 7,
    }.get(retention_class, 7)
    legal_hold = "Active" if retention_class in {"CDD", "Correspondence"} and (snapshot_id.endswith("COMPLAINT") or snapshot_id.endswith("LEGAL")) else "None"
    retention_until = today.replace(year=today.year + years).isoformat()
    deletion_eligible = "No" if legal_hold == "Active" else "No"
    return {"retention_until": retention_until, "legal_hold_status": legal_hold, "deletion_eligible": deletion_eligible}


def _slug(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")[:40] or "SNAPSHOT"


def _files_for_snapshot(source_dir: Path, snapshot_id: str) -> List[Path]:
    all_files = [p for p in sorted(source_dir.rglob("*")) if p.is_file() and not p.name.endswith(".search.txt")]
    if snapshot_id == "FULL":
        return all_files
    selected: List[Path] = []
    for path in all_files:
        rel = path.relative_to(source_dir)
        parts = set(p.lower() for p in rel.parts)
        name = path.name.lower()
        if snapshot_id == "ONBOARDING" and ("documents" in parts or "scans" in parts or "metadata" in parts):
            selected.append(path)
        elif snapshot_id == "CDD_REVIEW_2026" and ("cdd" in name or "source_of_wealth" in name or "passport" in name or "proof_of_address" in name or "audit_events" in name):
            selected.append(path)
        elif snapshot_id == "STATEMENTS_2026_Q1" and "statements" in parts and any(m in name for m in ["_01", "_02", "_03"]):
            selected.append(path)
        elif snapshot_id == "CORRESPONDENCE_2026" and "emails" in parts:
            selected.append(path)
        elif snapshot_id == "TRANSACTIONS_2026_Q1" and "extracts" in parts:
            selected.append(path)
        elif snapshot_id == "LEGAL_DISCLOSURE" and ("complaint" in name or "email" in name or "cdd" in name or "source_of_wealth" in name):
            selected.append(path)
    return selected


def build_container(source_dir: Path, output_path: Path, *, snapshot_id: str = "FULL", snapshot_type: str = "Full Entity Archive", container_version: int = 1, files: Sequence[Path] | None = None) -> Path:
    source_dir = Path(source_dir)
    output_path = Path(output_path)
    customer_path = source_dir / "metadata" / "customer.json"
    if not customer_path.exists():
        raise FileNotFoundError(f"Missing customer metadata: {customer_path}")
    entity = read_json(customer_path)
    entity_id = entity["entity_id"]

    source_files = list(files) if files is not None else _files_for_snapshot(source_dir, snapshot_id)

    primary = fits.PrimaryHDU()
    primary.header["EECVER"] = "0.2"
    primary.header["ENTITY"] = entity_id
    primary.header["ETYPE"] = entity.get("entity_type", "Entity")[:68]
    primary.header["NAME"] = entity.get("display_name", "")[:68]
    primary.header["CREATED"] = utc_now_iso()
    primary.header["SNAPSHOT"] = snapshot_id[:68]
    primary.header["SNAPTYPE"] = snapshot_type[:68]
    primary.header["VERSION"] = int(container_version)
    primary.header["PURPOSE"] = "Entity evidence preservation container"

    hdus: List[fits.hdu.base.ExtensionHDU] = []
    manifest: List[Dict] = []
    provenance: List[Dict] = []

    provenance.append(ProvenanceRecord(
        event_id=f"PROV-{entity_id}-{snapshot_id}-0001",
        entity_id=entity_id,
        event_type="CONTAINER_CREATED",
        source_system="Entity Evidence Container POC",
        actor="system",
        timestamp=utc_now_iso(),
        details=f"Created {snapshot_type} FITS evidence container from source folder {source_dir.name}",
    ).to_dict())

    payload_index = 1
    snapshot_slug = _slug(snapshot_id)
    for path in source_files:
        rel = path.relative_to(source_dir)
        data = path.read_bytes()
        hdu_name = f"PAYLOAD_{payload_index:06d}"
        cat = _categorise(rel)
        search_text, ocr_source = extract_search_text(path)
        retention = _retention_metadata(cat["retention_class"], cat["sensitivity"], snapshot_slug)
        rec = PayloadRecord(
            object_id=f"{entity_id}-{snapshot_slug}-OBJ-{payload_index:06d}",
            entity_id=entity_id,
            category=cat["category"],
            document_type=cat["document_type"],
            filename=path.name,
            relative_path=safe_rel_path(rel),
            mime_type=guess_mime(path),
            source_system=cat["source_system"],
            captured_at=utc_now_iso(),
            retention_class=cat["retention_class"],
            sensitivity=cat["sensitivity"],
            sha256=sha256_bytes(data),
            size_bytes=len(data),
            hdu_name=hdu_name,
            search_text=search_text,
            ocr_text=search_text,
            ocr_source=ocr_source,
            description=f"Preserved source file {safe_rel_path(rel)}",
            snapshot_id=snapshot_slug,
            snapshot_type=snapshot_type,
            container_version=container_version,
            **retention,
        )
        manifest.append(rec.to_dict())
        hdus.append(_payload_hdu(hdu_name, data, rec))
        payload_index += 1

    summary = {
        "entity_id": entity_id,
        "display_name": entity.get("display_name"),
        "payload_count": len(manifest),
        "total_payload_bytes": sum(item["size_bytes"] for item in manifest),
        "created_at": utc_now_iso(),
        "container_model": "FITS with JSON metadata HDUs and uint8 payload HDUs",
        "snapshot_id": snapshot_slug,
        "snapshot_type": snapshot_type,
        "container_version": container_version,
    }
    entity_with_snapshot = {**entity, "snapshot_id": snapshot_slug, "snapshot_type": snapshot_type, "container_version": container_version}
    all_hdus = [primary, _json_hdu("ENTITY_METADATA", entity_with_snapshot), _json_hdu("SUMMARY", summary), _json_hdu("MANIFEST", manifest), _json_hdu("PROVENANCE", provenance)] + hdus
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fits.HDUList(all_hdus).writeto(output_path, overwrite=True, checksum=True)
    return output_path


def build_all_containers(source_root: Path, output_root: Path, *, snapshot_model: bool = False) -> List[Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    outputs: List[Path] = []
    snapshots = [
        ("ONBOARDING", "Onboarding Evidence Snapshot"),
        ("CDD_REVIEW_2026", "CDD / AML Review Snapshot"),
        ("STATEMENTS_2026_Q1", "Statement Snapshot 2026 Q1"),
        ("CORRESPONDENCE_2026", "Correspondence Snapshot 2026"),
        ("TRANSACTIONS_2026_Q1", "Transaction Extract Snapshot 2026 Q1"),
        ("LEGAL_DISCLOSURE", "Legal Hold / Disclosure Snapshot"),
    ]
    for entity_dir in sorted(p for p in source_root.iterdir() if p.is_dir()):
        customer_path = entity_dir / "metadata" / "customer.json"
        if not customer_path.exists():
            continue
        entity = read_json(customer_path)
        if snapshot_model:
            for snapshot_id, snapshot_type in snapshots:
                files = _files_for_snapshot(entity_dir, snapshot_id)
                if not files:
                    continue
                out = output_root / f"{entity['entity_id']}__{snapshot_id}.fits"
                outputs.append(build_container(entity_dir, out, snapshot_id=snapshot_id, snapshot_type=snapshot_type, files=files))
        else:
            out = output_root / f"{entity['entity_id']}.fits"
            outputs.append(build_container(entity_dir, out))
    return outputs
