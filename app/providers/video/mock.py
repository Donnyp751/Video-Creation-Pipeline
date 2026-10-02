from __future__ import annotations

from pathlib import Path

from app.providers.common import Usage
from app.providers.video.base import GeneratedVideo, VideoProvider
from app.providers.video.runway import supported_duration
from app.utils.ffmpeg import run_ffmpeg


class MockVideo(VideoProvider):
    """Turns the still into a short clip with a slow zoom, mimicking a 5s/10s video model."""

    name = "mock"

    def __init__(self, model: str = "mock-video", width: int = 640):
        self.model = model
        self.width = width

    async def image_to_video(
        self,
        image: Path,
        prompt: str,
        duration: float,
        aspect_ratio: str,
        output: Path,
        variant: int = 1,
    ) -> GeneratedVideo:
        seconds = supported_duration(duration)
        output.parent.mkdir(parents=True, exist_ok=True)
        w = self.width
        # Slow horizontal pan across a slightly enlarged frame.
        vf = (
            f"scale={round(w * 1.15 / 2) * 2}:-2,"
            f"crop={w}:floor(ih/1.15/2)*2:x='(iw-ow)*t/{seconds}':y='(ih-oh)/2',"
            "setsar=1,format=yuv420p"
        )
        await run_ffmpeg([
            "-loop", "1", "-framerate", "24", "-i", str(image), "-t", str(seconds),
            "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", str(output),
        ])
        return GeneratedVideo(model=self.model, usage=Usage(units=seconds, unit_type="seconds"),
                              path=output, duration=float(seconds))
