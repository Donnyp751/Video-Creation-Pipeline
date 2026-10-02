from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from app.models.timing import Transcript
from app.providers.common import ProviderOutput


@dataclass
class TranscriptionResult(ProviderOutput):
    transcript: Transcript = field(default_factory=Transcript)


class SpeechProvider(ABC):
    """Speech-to-text with word timestamps (used to align sung lyrics).

    Text-to-speech (narration) can be added to this family later.
    """

    name: str
    model: str

    @abstractmethod
    async def transcribe(
        self, audio: Path, *, language: str | None = None, prompt: str | None = None
    ) -> TranscriptionResult:
        """``prompt`` carries the expected lyrics, which improves recognition of sung words."""
