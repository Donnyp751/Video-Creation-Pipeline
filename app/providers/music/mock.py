from __future__ import annotations

from pathlib import Path

from app.providers.common import Usage
from app.providers.music.base import GeneratedAudio, MusicProvider, MusicRequest
from app.utils.ffmpeg import run_ffmpeg


class MockMusic(MusicProvider):
    """Synthesises a simple stepped melody of the requested length with ffmpeg."""

    name = "mock"
    output_extension = ".wav"

    def __init__(self, model: str = "mock-music"):
        self.model = model

    async def compose(self, request: MusicRequest, output: Path, variant: int = 1) -> GeneratedAudio:
        beat = 60 / request.tempo_bpm
        expr = (
            f"0.25*sin(2*PI*(262+66*mod(floor(t/{beat:.4f}),5)+{variant}*3)*t)"
            f"*(0.6+0.4*abs(sin(PI*t/{beat:.4f})))"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        await run_ffmpeg([
            "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d={request.duration_seconds}",
            "-ac", "2", "-c:a", "pcm_s16le", str(output),
        ])
        return GeneratedAudio(
            model=self.model,
            usage=Usage(units=request.duration_seconds / 60, unit_type="minutes"),
            path=output,
            request_payload=request.model_dump(),
        )
