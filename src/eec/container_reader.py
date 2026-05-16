from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from astropy.io import fits

from .models import ValidationResult
from .utils import sha256_bytes, write_json


def _read_json_hdu(hdul: fits.HDUList, name: str) -> Any:
    data = bytes(hdul[name].data.tolist())
    return json.loads(data.decode("utf-8"))


def read_entity(container: Path) -> Dict[str, Any]:
    with fits.open(container, memmap=True) as hdul:
        return _read_json_hdu(hdul, "ENTITY_METADATA")


def read_manifest(container: Path) -> List[Dict[str, Any]]:
    with fits.open(container, memmap=True) as hdul:
        return _read_json_hdu(hdul, "MANIFEST")


def read_provenance(container: Path) -> List[Dict[str, Any]]:
    with fits.open(container, memmap=True) as hdul:
        return _read_json_hdu(hdul, "PROVENANCE")


def inspect_container(container: Path) -> Dict[str, Any]:
    with fits.open(container, memmap=True) as hdul:
        entity = _read_json_hdu(hdul, "ENTITY_METADATA")
        manifest = _read_json_hdu(hdul, "MANIFEST")
        retention = sorted(set(item["retention_class"] for item in manifest))
        sensitivity = sorted(set(item["sensitivity"] for item in manifest))
        return {
            "container": str(container),
            "entity_id": entity.get("entity_id"),
            "display_name": entity.get("display_name"),
            "jurisdiction": entity.get("jurisdiction"),
            "risk_rating": entity.get("risk_rating"),
            "payload_count": len(manifest),
            "container_size_bytes": Path(container).stat().st_size,
            "payload_size_bytes": sum(item["size_bytes"] for item in manifest),
            "retention_classes": retention,
            "sensitivities": sensitivity,
            "hdu_count": len(hdul),
        }


def validate_container(container: Path) -> ValidationResult:
    failures = []
    with fits.open(container, memmap=True, ignore_missing_simple=False) as hdul:
        entity = _read_json_hdu(hdul, "ENTITY_METADATA")
        manifest = _read_json_hdu(hdul, "MANIFEST")
        for item in manifest:
            hdu_name = item["hdu_name"]
            try:
                data = bytes(hdul[hdu_name].data.tolist())
            except Exception as exc:
                failures.append({"object_id": item["object_id"], "hdu_name": hdu_name, "reason": f"Unable to read HDU: {exc}"})
                continue
            actual = sha256_bytes(data)
            if actual != item["sha256"]:
                failures.append({
                    "object_id": item["object_id"],
                    "hdu_name": hdu_name,
                    "relative_path": item.get("relative_path"),
                    "expected_sha256": item["sha256"],
                    "actual_sha256": actual,
                    "reason": "SHA-256 mismatch",
                })
    return ValidationResult(
        container_path=str(container),
        entity_id=entity.get("entity_id", "UNKNOWN"),
        status="PASS" if not failures else "FAIL",
        checked_payloads=len(manifest),
        failed_payloads=len(failures),
        failures=failures,
    )


def extract_container(container: Path, output_dir: Path) -> List[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    extracted: List[Path] = []
    with fits.open(container, memmap=True) as hdul:
        manifest = _read_json_hdu(hdul, "MANIFEST")
        entity = _read_json_hdu(hdul, "ENTITY_METADATA")
        provenance = _read_json_hdu(hdul, "PROVENANCE")
        write_json(output_dir / "_entity_metadata.json", entity)
        write_json(output_dir / "_manifest.json", manifest)
        write_json(output_dir / "_provenance.json", provenance)
        for item in manifest:
            data = bytes(hdul[item["hdu_name"]].data.tolist())
            out = output_dir / item["relative_path"]
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            extracted.append(out)
    return extracted
