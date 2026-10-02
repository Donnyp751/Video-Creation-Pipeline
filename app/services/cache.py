"""Content-addressed cache of provider results.

The key is a hash of provider + model + operation + prompt + parameters + reference image
content. An identical request is served from disk instead of paying for it again.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.utils.files import read_json, sha256_file, sha256_json, write_json


class ProviderCache:
    def __init__(self, root: Path):
        self.root = root

    @staticmethod
    def key(material: dict[str, Any]) -> str:
        return sha256_json(material)

    @staticmethod
    def file_fingerprints(paths: list[Path]) -> list[str]:
        return [sha256_file(p) for p in paths]

    def _path(self, key: str, suffix: str) -> Path:
        return self.root / key[:2] / f"{key}{suffix}"

    def get_file(self, key: str, suffix: str) -> Path | None:
        p = self._path(key, suffix)
        return p if p.is_file() else None

    def put_file(self, key: str, src: Path) -> Path:
        dst = self._path(key, src.suffix)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return dst

    def get_json(self, key: str) -> Any | None:
        p = self._path(key, ".json")
        return read_json(p) if p.is_file() else None

    def put_json(self, key: str, data: Any) -> None:
        write_json(self._path(key, ".json"), data)
