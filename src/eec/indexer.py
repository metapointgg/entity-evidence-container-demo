from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict

from .container_reader import read_entity, read_manifest
from .semantic import expand_query


SCHEMA_VERSION = 3


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS schema_info;
        DROP TABLE IF EXISTS entities;
        DROP TABLE IF EXISTS containers;
        DROP TABLE IF EXISTS objects;
        DROP TABLE IF EXISTS object_search;

        CREATE TABLE schema_info (version INTEGER NOT NULL);
        INSERT INTO schema_info(version) VALUES (3);

        CREATE TABLE entities (
            entity_id TEXT PRIMARY KEY,
            display_name TEXT,
            jurisdiction TEXT,
            risk_rating TEXT,
            occupation TEXT,
            container_path TEXT
        );

        CREATE TABLE containers (
            container_id TEXT PRIMARY KEY,
            entity_id TEXT NOT NULL,
            snapshot_id TEXT,
            snapshot_type TEXT,
            container_version INTEGER,
            container_path TEXT,
            object_count INTEGER,
            payload_bytes INTEGER,
            container_bytes INTEGER
        );

        CREATE TABLE objects (
            object_id TEXT PRIMARY KEY,
            entity_id TEXT NOT NULL,
            container_id TEXT,
            snapshot_id TEXT,
            snapshot_type TEXT,
            container_version INTEGER,
            category TEXT,
            document_type TEXT,
            filename TEXT,
            relative_path TEXT,
            mime_type TEXT,
            source_system TEXT,
            retention_class TEXT,
            retention_until TEXT,
            legal_hold_status TEXT,
            deletion_eligible TEXT,
            sensitivity TEXT,
            captured_at TEXT,
            sha256 TEXT,
            size_bytes INTEGER,
            container_path TEXT,
            hdu_name TEXT,
            ocr_source TEXT,
            ocr_text TEXT,
            search_text TEXT
        );

        CREATE VIRTUAL TABLE object_search USING fts5(
            object_id UNINDEXED,
            entity_id UNINDEXED,
            container_id UNINDEXED,
            snapshot_id,
            snapshot_type,
            display_name,
            jurisdiction,
            risk_rating,
            occupation,
            category,
            document_type,
            filename,
            relative_path,
            source_system,
            retention_class,
            retention_until,
            legal_hold_status,
            deletion_eligible,
            sensitivity,
            ocr_source,
            search_text,
            semantic_text
        );
        """
    )


def _upsert_entity(conn: sqlite3.Connection, entity: Dict, container: Path) -> None:
    conn.execute(
        """
        INSERT INTO entities(entity_id, display_name, jurisdiction, risk_rating, occupation, container_path)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(entity_id) DO UPDATE SET
            display_name=excluded.display_name,
            jurisdiction=excluded.jurisdiction,
            risk_rating=excluded.risk_rating,
            occupation=excluded.occupation
        """,
        (entity.get("entity_id"), entity.get("display_name"), entity.get("jurisdiction"), entity.get("risk_rating"), entity.get("occupation"), str(container)),
    )


def rebuild_index(containers_dir: Path, sqlite_path: Path) -> int:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sqlite_path)
    try:
        create_schema(conn)
        count = 0
        for container in sorted(containers_dir.glob("*.fits")):
            if "corrupt" in container.stem.lower():
                continue
            entity = read_entity(container)
            entity_id = entity.get("entity_id")
            snapshot_id = entity.get("snapshot_id", "FULL")
            snapshot_type = entity.get("snapshot_type", "Full Entity Archive")
            container_version = int(entity.get("container_version", 1) or 1)
            container_id = f"{entity_id}:{snapshot_id}:v{container_version}"
            manifest = read_manifest(container)
            _upsert_entity(conn, entity, container)
            conn.execute(
                """
                INSERT INTO containers(container_id, entity_id, snapshot_id, snapshot_type, container_version, container_path, object_count, payload_bytes, container_bytes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (container_id, entity_id, snapshot_id, snapshot_type, container_version, str(container), len(manifest), sum(int(i.get("size_bytes", 0)) for i in manifest), container.stat().st_size),
            )
            entity_text = " ".join(str(entity.get(k, "")) for k in ["entity_id", "display_name", "jurisdiction", "risk_rating", "occupation"])
            for item in manifest:
                search_text = item.get("search_text", "") or item.get("ocr_text", "") or ""
                item_snapshot_id = item.get("snapshot_id", snapshot_id)
                item_snapshot_type = item.get("snapshot_type", snapshot_type)
                semantic_text = " ".join([
                    entity_text,
                    str(item_snapshot_id), str(item_snapshot_type),
                    str(item.get("category", "")), str(item.get("document_type", "")), str(item.get("filename", "")),
                    str(item.get("source_system", "")), str(item.get("retention_class", "")), str(item.get("legal_hold_status", "")),
                    str(item.get("sensitivity", "")), search_text,
                ])
                conn.execute(
                    """
                    INSERT INTO objects(object_id, entity_id, container_id, snapshot_id, snapshot_type, container_version,
                    category, document_type, filename, relative_path, mime_type, source_system, retention_class, retention_until,
                    legal_hold_status, deletion_eligible, sensitivity, captured_at, sha256, size_bytes, container_path, hdu_name,
                    ocr_source, ocr_text, search_text)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["object_id"], item["entity_id"], container_id, item_snapshot_id, item_snapshot_type, item.get("container_version", container_version),
                        item.get("category"), item.get("document_type"), item.get("filename"), item.get("relative_path"), item.get("mime_type"),
                        item.get("source_system"), item.get("retention_class"), item.get("retention_until", ""), item.get("legal_hold_status", "None"),
                        item.get("deletion_eligible", "No"), item.get("sensitivity"), item.get("captured_at"), item.get("sha256"), item.get("size_bytes"),
                        str(container), item.get("hdu_name"), item.get("ocr_source", "none"), item.get("ocr_text", search_text), search_text,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO object_search(object_id, entity_id, container_id, snapshot_id, snapshot_type, display_name, jurisdiction, risk_rating, occupation,
                    category, document_type, filename, relative_path, source_system, retention_class, retention_until, legal_hold_status, deletion_eligible,
                    sensitivity, ocr_source, search_text, semantic_text)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["object_id"], item["entity_id"], container_id, item_snapshot_id, item_snapshot_type,
                        entity.get("display_name"), entity.get("jurisdiction"), entity.get("risk_rating"), entity.get("occupation"),
                        item.get("category"), item.get("document_type"), item.get("filename"), item.get("relative_path"), item.get("source_system"),
                        item.get("retention_class"), item.get("retention_until", ""), item.get("legal_hold_status", "None"), item.get("deletion_eligible", "No"),
                        item.get("sensitivity"), item.get("ocr_source", "none"), search_text,
                        semantic_text + " " + expand_query(semantic_text[:1000]),
                    ),
                )
                count += 1
        conn.commit()
        return count
    finally:
        conn.close()
