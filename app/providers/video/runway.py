"""Runway image-to-video (async task API: create, poll, download)."""

from __future__ import annotations

import asyncio
import base64
import io
import time
from pathlib import Path

import httpx
from PIL import Image

from app.core.progress import report
from app.providers.common import ProviderError, Usage
from app.providers.video.base import GeneratedVideo, VideoProvider
from app.utils.files import write_bytes

API_BASE = "https://api.dev.runwayml.com"
API_VERSION = "2024-11-06"


def ratio_for_aspect(aspect_ratio: str) -> str:
    a, b = (int(x) for x in aspect_ratio.split(":"))
    if a > b:
        return "1280:720"
    if a < b:
        return "720:1280"
    return "960:960"


def supported_duration(duration: float) -> int:
    return 5 if duration <= 5 else 10


def image_data_uri(path: Path, max_side: int = 1920) -> str:
    """JPEG data URI (keeps the upload well under API size limits)."""
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


class RunwayVideo(VideoProvider):
    name = "runway"

    def __init__(self, api_key: str, model: str, poll_interval: float = 5.0,
                 timeout: float = 900.0):
        self.api_key = api_key
        self.model = model
        self.poll_interval = poll_interval
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "X-Runway-Version": API_VERSION}

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
        body = {
            "model": self.model,
            "promptImage": image_data_uri(image),
            "promptText": prompt[:1000],
            "ratio": ratio_for_aspect(aspect_ratio),
            "duration": seconds,
        }
        async with httpx.AsyncClient(base_url=API_BASE, timeout=120.0,
                                     headers=self._headers()) as client:
            report("GENERATING", "submitting image-to-video task")
            resp = await client.post("/v1/image_to_video", json=body)
            if resp.status_code >= 400:
                raise ProviderError(f"Runway error {resp.status_code}: {resp.text[:500]}")
            task_id = resp.json()["id"]

            deadline = time.monotonic() + self.timeout
            while True:
                task = (await client.get(f"/v1/tasks/{task_id}")).json()
                status = task.get("status")
                if status == "SUCCEEDED":
                    break
                if status in ("FAILED", "CANCELLED"):
                    raise ProviderError(f"Runway task {task_id} {status}: {task.get('failure')}")
                if time.monotonic() > deadline:
                    raise ProviderError(f"Runway task {task_id} timed out (last status {status})")
                report("GENERATING", f"runway task {status} {task.get('progress', '')}")
                await asyncio.sleep(self.poll_interval)

        report("DOWNLOADING", "downloading animation")
        # Output URLs are pre-signed; don't send the API key to the CDN.
        async with httpx.AsyncClient(timeout=300.0, follow_redirects=True) as cdn:
            video = await cdn.get(task["output"][0])
            video.raise_for_status()
            write_bytes(output, video.content)

        return GeneratedVideo(
            model=self.model,
            usage=Usage(units=seconds, unit_type="seconds"),
            path=output,
            duration=float(seconds),
            raw={"task_id": task_id, "ratio": body["ratio"], "duration": seconds},
        )
