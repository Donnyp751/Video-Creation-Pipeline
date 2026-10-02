from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app.providers.common import ProviderOutput


@dataclass
class GeneratedImage(ProviderOutput):
    path: Path = Path()


class ImageProvider(ABC):
    name: str
    model: str

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        references: list[Path],
        aspect_ratio: str,
        output: Path,
        variant: int = 1,
    ) -> GeneratedImage:
        """Generate one image into ``output`` (PNG).

        ``variant`` distinguishes deliberate regenerations of the same prompt; it is part of the
        cache key so a regeneration is a new request rather than a cache hit.
        """
