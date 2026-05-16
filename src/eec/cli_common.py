from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def fmt_bytes(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
