from __future__ import annotations

from pathlib import Path

from openai import AsyncOpenAI

from app.models.timing import Transcript, Word
from app.providers.common import Usage
from app.providers.speech.base import SpeechProvider, TranscriptionResult


class OpenAISpeech(SpeechProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str = "whisper-1"):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def transcribe(
        self, audio: Path, *, language: str | None = None, prompt: str | None = None
    ) -> TranscriptionResult:
        kwargs: dict = {}
        if language:
            kwargs["language"] = language
        if prompt:
            kwargs["prompt"] = prompt[:800]  # whisper only uses the last ~224 tokens anyway
        with audio.open("rb") as fh:
            resp = await self.client.audio.transcriptions.create(
                model=self.model,
                file=fh,
                response_format="verbose_json",
                timestamp_granularities=["word", "segment"],
                **kwargs,
            )
        words = [Word(text=w.word, start=w.start, end=w.end) for w in (resp.words or [])]
        duration = float(getattr(resp, "duration", 0) or 0)
        transcript = Transcript(text=resp.text, language=getattr(resp, "language", None),
                                duration=duration, words=words)
        return TranscriptionResult(
            model=self.model,
            usage=Usage(units=duration / 60, unit_type="minutes"),
            transcript=transcript,
        )
