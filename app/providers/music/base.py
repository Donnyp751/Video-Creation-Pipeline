from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from app.providers.common import ProviderOutput


class MusicSection(BaseModel):
    name: str
    lines: list[str]


class MusicRequest(BaseModel):
    """Provider-neutral description of the song to produce (saved as music_request.json)."""

    title: str
    style: str
    tempo_bpm: int
    mood: str
    vocal_description: str
    duration_seconds: int
    languages: list[str]
    sections: list[MusicSection]
    avoid: list[str] = Field(default_factory=list)

    @property
    def all_lines(self) -> list[str]:
        return [line for s in self.sections for line in s.lines]


@dataclass
class GeneratedAudio(ProviderOutput):
    path: Path = Path()
    request_payload: dict | None = None


class MusicProvider(ABC):
    name: str
    model: str
    output_extension: str  # e.g. ".mp3"; the music service converts to song.wav

    @abstractmethod
    async def compose(self, request: MusicRequest, output: Path, variant: int = 1) -> GeneratedAudio:
        """Produce a full sung track for ``request`` at ``output``."""
