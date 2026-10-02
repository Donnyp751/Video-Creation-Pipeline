from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app.providers.common import ProviderOutput


@dataclass
class GeneratedVideo(ProviderOutput):
    path: Path = Path()
    duration: float = 0.0


class VideoProvider(ABC):
    name: str
    model: str

    @abstractmethod
    async def image_to_video(
        self,
        image: Path,
        prompt: str,
        duration: float,
        aspect_ratio: str,
        output: Path,
        variant: int = 1,
    ) -> GeneratedVideo:
        """Animate ``image``. Providers may return a clip of a different (supported) length;
        the renderer trims or holds frames to fit the scene."""
