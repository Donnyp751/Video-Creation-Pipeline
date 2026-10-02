"""Filesystem helpers: atomic writes, hashing and versioned file names."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def write_bytes(path: Path, data: bytes) -> None:
    _atomic_write_bytes(path, data)


def write_json(path: Path, data: Any) -> None:
    write_text(path, json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_json(obj: Any) -> str:
    canonical = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return sha256_bytes(canonical.encode("utf-8"))


def list_versions(directory: Path, prefix: str, suffix: str) -> list[tuple[int, Path]]:
    """Return ``[(n, path)]`` for files named ``{prefix}_v{n}{suffix}``, sorted by n."""
    pattern = re.compile(rf"^{re.escape(prefix)}_v(\d+){re.escape(suffix)}$")
    found = []
    if directory.is_dir():
        for p in directory.iterdir():
            m = pattern.match(p.name)
            if m:
                found.append((int(m.group(1)), p))
    return sorted(found)


def next_version(directory: Path, prefix: str, suffix: str) -> tuple[int, Path]:
    """Next free ``{prefix}_v{n}{suffix}`` path. Existing versions are never overwritten."""
    versions = list_versions(directory, prefix, suffix)
    n = versions[-1][0] + 1 if versions else 1
    return n, directory / f"{prefix}_v{n}{suffix}"


def safe_join(root: Path, relative: str) -> Path:
    """Join ``relative`` onto ``root`` and refuse anything that escapes ``root``."""
    root = root.resolve()
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"path escapes project directory: {relative}")
    return candidate
