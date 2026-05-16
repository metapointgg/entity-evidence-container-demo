from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, List

from .container_reader import read_entity, read_manifest


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS entities;
        DROP TABLE IF EXISTS objects;
        DROP TABLE IF EXISTS object_search;

        CREATE TABLE entities (
            entity_id TEXT PRIMARY KEY,
            display_name TEXT,
            jurisdiction TEXT,
            risk_rating TEXT,
            occupation TEXT,
            container_path TEXT
        );

        CREATE TABLE objects (
            object_id TEXT PRIMARY KEY,
            entity_id TEXT NOT NULL,
            category TEXT,
            document_type TEXT,
            filename TEXT,
            relative_path TEXT,
            mime_type TEXT,
            source_system TEXT,
            retention_class TEXT,
            sensitivity TEXT,
            sha256 TEXT,
            size_bytes INTEGER,
            container_path TEXT,
            hdu_name TEXT
        );

        CREATE VIRTUAL TABLE object_search USING fts5(
            object_id UNINDEXED,
            entity_id UNINDEXED,
            display_name,
            category,
            document_type,
            filename,
            relative_path,
            source_system,
            retention_class,
            sensitivity,
            search_text
        );
        """
    )


def rebuild_index(containers_dir: Path, sqlite_path: Path) -> int:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sqlite_path)
    try:
        create_schema(conn)
        count = 0
        for container in sorted(containers_dir.glob("*.fits")):
            entity = read_entity(container)
            manifest = read_manifest(container)
            conn.execute(
                "INSERT INTO entities(entity_id, display_name, jurisdiction, risk_rating, occupation, container_path) VALUES (?, ?, ?, ?, ?, ?)",
                (entity.get("entity_id"), entity.get("display_name"), entity.get("jurisdiction"), entity.get("risk_rating"), entity.get("occupation"), str(container)),
            )
            for item in manifest:
                conn.execute(
                    """
                    INSERT INTO objects(object_id, entity_id, category, document_type, filename, relative_path, mime_type,
                    source_system, retention_class, sensitivity, sha256, size_bytes, container_path, hdu_name)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["object_id"], item["entity_id"], item["category"], item["document_type"], item["filename"], item["relative_path"], item["mime_type"],
                        item["source_system"], item["retention_class"], item["sensitivity"], item["sha256"], item["size_bytes"], str(container), item["hdu_name"],
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO object_search(object_id, entity_id, display_name, category, document_type, filename, relative_path,
                    source_system, retention_class, sensitivity, search_text)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["object_id"], item["entity_id"], entity.get("display_name"), item["category"], item["document_type"], item["filename"], item["relative_path"],
                        item["source_system"], item["retention_class"], item["sensitivity"], item.get("search_text", ""),
                    ),
                )
                count += 1
        conn.commit()
        return count
    finally:
        conn.close()
