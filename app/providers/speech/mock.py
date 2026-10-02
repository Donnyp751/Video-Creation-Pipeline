from __future__ import annotations

from pathlib import Path

from app.models.timing import Transcript, Word
from app.providers.common import Usage
from app.providers.speech.base import SpeechProvider, TranscriptionResult
from app.utils.ffmpeg import media_duration


class MockSpeech(SpeechProvider):
    """Pretends the expected lyrics (the prompt) were sung evenly after a short intro."""

    name = "mock"

    def __init__(self, model: str = "mock-speech", intro: float = 1.0):
        self.model = model
        self.intro = intro

    async def transcribe(
        self, audio: Path, *, language: str | None = None, prompt: str | None = None
    ) -> TranscriptionResult:
        duration = await media_duration(audio)
        tokens = (prompt or "").split()
        words: list[Word] = []
        if tokens:
            span = max(duration - self.intro - 1.0, 1.0)
            step = span / len(tokens)
            for i, tok in enumerate(tokens):
                start = self.intro + i * step
                words.append(Word(text=tok, start=round(start, 3),
                                  end=round(start + step * 0.8, 3)))
        return TranscriptionResult(
            model=self.model,
            usage=Usage(units=duration / 60, unit_type="minutes"),
            transcript=Transcript(text=" ".join(tokens), duration=duration, words=words),
        )
