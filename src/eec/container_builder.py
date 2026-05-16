from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List

import numpy as np
from astropy.io import fits

from .models import PayloadRecord, ProvenanceRecord
from .utils import guess_mime, read_json, safe_rel_path, sha256_bytes, sha256_file, slug, utc_now_iso


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
    hdu.header["OBJID"] = record.object_id
    hdu.header["MIMETYPE"] = record.mime_type[:68]
    hdu.header["SHA256"] = record.sha256
    hdu.header["SIZE"] = record.size_bytes
    # Filename can exceed safe FITS card lengths, so the full value lives in the manifest.
    hdu.header["FILENAME"] = Path(record.filename).name[:68]
    return hdu


def _search_text_for(path: Path) -> str:
    sidecar = path.with_suffix(".search.txt")
    if sidecar.exists():
        return sidecar.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in {".txt", ".json", ".csv", ".eml", ".md"}:
        return path.read_text(encoding="utf-8", errors="replace")[:200000]
    return ""


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


def build_container(source_dir: Path, output_path: Path) -> Path:
    source_dir = Path(source_dir)
    output_path = Path(output_path)
    customer_path = source_dir / "metadata" / "customer.json"
    if not customer_path.exists():
        raise FileNotFoundError(f"Missing customer metadata: {customer_path}")
    entity = read_json(customer_path)
    entity_id = entity["entity_id"]

    files = [p for p in sorted(source_dir.rglob("*")) if p.is_file() and not p.name.endswith(".search.txt")]

    primary = fits.PrimaryHDU()
    primary.header["EECVER"] = "0.1"
    primary.header["ENTITY"] = entity_id
    primary.header["ETYPE"] = entity.get("entity_type", "Entity")[:68]
    primary.header["NAME"] = entity.get("display_name", "")[:68]
    primary.header["CREATED"] = utc_now_iso()
    primary.header["PURPOSE"] = "Entity evidence preservation container"

    hdus: List[fits.hdu.base.ExtensionHDU] = []
    manifest: List[Dict] = []
    provenance: List[Dict] = []

    provenance.append(ProvenanceRecord(
        event_id=f"PROV-{entity_id}-0001",
        entity_id=entity_id,
        event_type="CONTAINER_CREATED",
        source_system="Entity Evidence Container POC",
        actor="system",
        timestamp=utc_now_iso(),
        details=f"Created FITS evidence container from source folder {source_dir.name}",
    ).to_dict())

    payload_index = 1
    for path in files:
        rel = path.relative_to(source_dir)
        data = path.read_bytes()
        hdu_name = f"PAYLOAD_{payload_index:06d}"
        cat = _categorise(rel)
        rec = PayloadRecord(
            object_id=f"{entity_id}-OBJ-{payload_index:06d}",
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
            search_text=_search_text_for(path),
            description=f"Preserved source file {safe_rel_path(rel)}",
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
    }

    all_hdus = [primary, _json_hdu("ENTITY_METADATA", entity), _json_hdu("SUMMARY", summary), _json_hdu("MANIFEST", manifest), _json_hdu("PROVENANCE", provenance)] + hdus
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fits.HDUList(all_hdus).writeto(output_path, overwrite=True, checksum=True)
    return output_path


def build_all_containers(source_root: Path, output_root: Path) -> List[Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    outputs: List[Path] = []
    for entity_dir in sorted(p for p in source_root.iterdir() if p.is_dir()):
        customer_path = entity_dir / "metadata" / "customer.json"
        if not customer_path.exists():
            continue
        entity = read_json(customer_path)
        out = output_root / f"{entity['entity_id']}.fits"
        outputs.append(build_container(entity_dir, out))
    return outputs
