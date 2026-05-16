from __future__ import annotations

import shutil
from pathlib import Path

from astropy.io import fits

from .container_reader import read_manifest


def corrupt_container_payload(container: Path, output: Path, object_index: int = 1) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(container, output)
    manifest = read_manifest(output)
    if object_index < 1 or object_index > len(manifest):
        raise ValueError(f"object_index must be between 1 and {len(manifest)}")
    target = manifest[object_index - 1]
    hdu_name = target["hdu_name"]
    with fits.open(output, mode="update", memmap=False) as hdul:
        arr = hdul[hdu_name].data
        if arr is None or len(arr) == 0:
            raise ValueError(f"Target HDU {hdu_name} has no data")
        idx = min(16, len(arr) - 1)
        arr[idx] = (int(arr[idx]) + 1) % 255
        hdul.flush()
    return output


def corrupt_container(container: Path, output: Path, object_index: int = 1) -> Path:
    """Backward-compatible wrapper used by the Streamlit UI.

    Creates a corrupted copy of ``container`` by modifying one payload HDU.
    ``object_index`` is 1-based and corresponds to the manifest row number.
    """
    return corrupt_container_payload(container, output, object_index)
