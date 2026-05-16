from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def safe_rel_path(path: Path) -> str:
    return str(path).replace(os.sep, "/")


def guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def slug(value: str, max_len: int = 48) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return value[:max_len] or "item"


def deterministic_bytes(size: int, seed_text: str) -> bytes:
    """Generate deterministic pseudo-random-ish bytes without relying on random state."""
    out = bytearray()
    counter = 0
    base = seed_text.encode("utf-8")
    while len(out) < size:
        counter_bytes = counter.to_bytes(8, "big")
        out.extend(hashlib.sha256(base + counter_bytes).digest())
        counter += 1
    return bytes(out[:size])
