from __future__ import annotations

from pathlib import Path

from app.retrieval.fastembed_cache import dereference_model_symlinks


def test_dereference_model_symlinks_replaces_blob_links(tmp_path: Path) -> None:
    blob = tmp_path / "blobs" / "aa" / "weights.onnx_data"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"weights")

    model = tmp_path / "models--example" / "snapshots" / "rev"
    model.mkdir(parents=True)
    link = model / "weights.onnx_data"
    link.symlink_to(blob)

    fixed = dereference_model_symlinks(tmp_path)

    assert fixed == 1
    assert not link.is_symlink()
    assert link.read_bytes() == b"weights"
    assert link.stat().st_ino == blob.stat().st_ino
