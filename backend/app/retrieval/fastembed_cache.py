"""FastEmbed cache helpers.

Hugging Face snapshots use symlinks into a shared ``blobs`` directory. ONNX
Runtime rejects external-data weights whose resolved path escapes the model
directory, so replace cache symlinks with hard links (or copies) before loading.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


def cache_directory() -> Path:
    default = Path(tempfile.gettempdir()) / "fastembed_cache"
    return Path(os.getenv("FASTEMBED_CACHE_PATH", default))


def dereference_model_symlinks(cache_dir: Path) -> int:
    fixed = 0
    if not cache_dir.is_dir():
        return fixed
    for root, _dirs, files in os.walk(cache_dir):
        parts = Path(root).parts
        if "blobs" in parts:
            continue
        for name in files:
            path = Path(root) / name
            if not path.is_symlink():
                continue
            target = path.resolve()
            if "blobs" not in target.parts:
                continue
            path.unlink()
            try:
                os.link(target, path)
            except OSError:
                shutil.copyfile(target, path)
            fixed += 1
    return fixed


def is_external_data_error(error: Exception) -> bool:
    return "External data path" in str(error)
