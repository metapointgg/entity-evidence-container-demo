from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .container_reader import read_extracted_fields, read_extraction_events, read_manifest, read_ocr_text


def extraction_dashboard(sqlite_path: Path) -> dict[str, Any]:
    if not sqlite_path.exists():
        return {
            "object_count": 0,
            "with_search_text": 0,
            "with_extracted_fields": 0,
            "low_confidence_objects": 0,
            "ocr_sources": [],
            "field_counts": {},
            "low_confidence_rows": [],
        }

    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        totals = conn.execute(
            """
            SELECT
                COUNT(*) AS object_count,
                SUM(CASE WHEN COALESCE(search_text, '') != '' THEN 1 ELSE 0 END) AS with_search_text,
                SUM(CASE WHEN COALESCE(extracted_fields_count, 0) > 0 THEN 1 ELSE 0 END) AS with_extracted_fields,
                SUM(CASE WHEN COALESCE(extraction_confidence, 0) > 0 AND COALESCE(extraction_confidence, 0) < 0.7 THEN 1 ELSE 0 END) AS low_confidence_objects
            FROM objects
            """
        ).fetchone()
        ocr_sources = [dict(row) for row in conn.execute(
            """
            SELECT COALESCE(ocr_source, 'none') AS ocr_source, COUNT(*) AS count
            FROM objects
            GROUP BY COALESCE(ocr_source, 'none')
            ORDER BY count DESC, ocr_source
            """
        ).fetchall()]
        rows = [dict(row) for row in conn.execute(
            """
            SELECT object_id, entity_id, snapshot_id, category, document_type, filename,
                   ocr_source, extraction_confidence, extracted_fields_count,
                   container_path, hdu_name
            FROM objects
            WHERE COALESCE(extraction_confidence, 0) > 0 AND COALESCE(extraction_confidence, 0) < 0.7
            ORDER BY extraction_confidence ASC, entity_id, filename
            LIMIT 250
            """
        ).fetchall()]
        all_rows = conn.execute(
            """
            SELECT extracted_fields_json FROM objects
            WHERE COALESCE(extracted_fields_json, '') NOT IN ('', '[]')
            """
        ).fetchall()
        field_counts: dict[str, int] = {}
        for row in all_rows:
            try:
                fields = json.loads(row[0] or "[]")
            except Exception:
                fields = []
            for field in fields if isinstance(fields, list) else []:
                if isinstance(field, dict):
                    name = str(field.get("field_name") or "unknown")
                    field_counts[name] = field_counts.get(name, 0) + 1
        return {
            "object_count": int(totals["object_count"] or 0),
            "with_search_text": int(totals["with_search_text"] or 0),
            "with_extracted_fields": int(totals["with_extracted_fields"] or 0),
            "low_confidence_objects": int(totals["low_confidence_objects"] or 0),
            "ocr_sources": ocr_sources,
            "field_counts": field_counts,
            "low_confidence_rows": rows,
        }
    finally:
        conn.close()


def extracted_fields_for_entity(sqlite_path: Path, entity_id: str) -> list[dict[str, Any]]:
    if not sqlite_path.exists():
        return []
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT object_id, entity_id, snapshot_id, category, document_type, filename,
                   source_system, ocr_source, extraction_confidence, extracted_fields_json,
                   container_path, hdu_name
            FROM objects
            WHERE entity_id = ?
            ORDER BY snapshot_id, category, document_type, filename
            """,
            (entity_id,),
        ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            base = dict(row)
            try:
                fields = json.loads(base.get("extracted_fields_json") or "[]")
            except Exception:
                fields = []
            for field in fields if isinstance(fields, list) else []:
                if not isinstance(field, dict):
                    continue
                results.append({
                    **{k: v for k, v in base.items() if k != "extracted_fields_json"},
                    "field_name": field.get("field_name"),
                    "field_value": field.get("field_value"),
                    "field_type": field.get("field_type"),
                    "field_confidence": field.get("confidence"),
                    "field_source": field.get("source"),
                })
        return results
    finally:
        conn.close()


def extraction_report_for_container(container: Path) -> dict[str, Any]:
    manifest = read_manifest(container)
    fields = read_extracted_fields(container)
    events = read_extraction_events(container)
    ocr_rows = read_ocr_text(container)
    field_counts: dict[str, int] = {}
    for field in fields:
        name = str(field.get("field_name") or "unknown")
        field_counts[name] = field_counts.get(name, 0) + 1
    return {
        "container": str(container),
        "object_count": len(manifest),
        "ocr_rows": len(ocr_rows),
        "extracted_field_count": len(fields),
        "extraction_event_count": len(events),
        "field_counts": field_counts,
        "events": events,
        "fields": fields,
    }
