"""Types shared by all provider families."""

from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

UnitType = Literal["images", "seconds", "minutes", "calls"]


class ProviderError(RuntimeError):
    pass


class ProviderNotConfigured(ProviderError):
    pass


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    units: float = 0.0
    unit_type: UnitType | None = None

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.units + other.units,
            self.unit_type or other.unit_type,
        )


@dataclass
class ProviderOutput:
    """Base for anything a provider returns."""

    model: str
    usage: Usage = field(default_factory=Usage)
    raw: dict[str, Any] = field(default_factory=dict)
    cache_hit: bool = False


def data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def require_key(value: Any, name: str) -> str:
    secret = value.get_secret_value() if value is not None else ""
    if not secret:
        raise ProviderNotConfigured(f"{name} is not set (add it to .env)")
    return secret
