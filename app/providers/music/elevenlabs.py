"""ElevenLabs Music API (composition plan with per-section lyrics)."""

from __future__ import annotations

from pathlib import Path

import httpx

from app.core.progress import report
from app.providers.common import ProviderError, Usage
from app.providers.music.base import GeneratedAudio, MusicProvider, MusicRequest
from app.utils.files import write_bytes

API_BASE = "https://api.elevenlabs.io"
MIN_SECTION_MS = 3_000
MAX_SECTION_MS = 120_000


def build_composition_plan(request: MusicRequest) -> dict:
    total_ms = request.duration_seconds * 1000
    total_lines = max(1, len(request.all_lines))
    sections = []
    for s in request.sections:
        share = round(total_ms * max(1, len(s.lines)) / total_lines)
        sections.append({
            "section_name": s.name,
            "positive_local_styles": [],
            "negative_local_styles": [],
            "duration_ms": max(MIN_SECTION_MS, min(MAX_SECTION_MS, share)),
            "lines": s.lines,
        })
    return {
        "positive_global_styles": [
            request.style,
            request.mood,
            f"{request.tempo_bpm} bpm",
            request.vocal_description,
            f"sung in {' and '.join(request.languages)}",
            "clear diction for young children",
        ],
        "negative_global_styles": request.avoid,
        "sections": sections,
    }


class ElevenLabsMusic(MusicProvider):
    name = "elevenlabs"
    output_extension = ".mp3"

    def __init__(self, api_key: str, model: str, timeout: float = 600.0):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def compose(self, request: MusicRequest, output: Path, variant: int = 1) -> GeneratedAudio:
        payload = {"model_id": self.model, "composition_plan": build_composition_plan(request)}
        report("GENERATING", "composing song")
        async with httpx.AsyncClient(base_url=API_BASE, timeout=self.timeout) as client:
            resp = await client.post(
                "/v1/music",
                params={"output_format": "mp3_44100_192"},
                headers={"xi-api-key": self.api_key},
                json=payload,
            )
        if resp.status_code >= 400:
            raise ProviderError(f"ElevenLabs music error {resp.status_code}: {resp.text[:500]}")
        report("DOWNLOADING", "saving audio")
        write_bytes(output, resp.content)
        return GeneratedAudio(
            model=self.model,
            usage=Usage(units=request.duration_seconds / 60, unit_type="minutes"),
            path=output,
            request_payload=payload,
            raw={"headers": {k: v for k, v in resp.headers.items() if k.startswith(("song", "x-"))}},
        )
