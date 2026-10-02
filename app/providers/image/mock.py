from __future__ import annotations

import hashlib
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.providers.common import Usage
from app.providers.image.base import GeneratedImage, ImageProvider


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _size(aspect_ratio: str) -> tuple[int, int]:
    a, b = (int(x) for x in aspect_ratio.split(":"))
    return (1280, round(1280 * b / a / 2) * 2) if a >= b else (round(1280 * a / b / 2) * 2, 1280)


class MockImage(ImageProvider):
    """Draws a placeholder card containing the scene section of the prompt."""

    name = "mock"

    def __init__(self, model: str = "mock-image"):
        self.model = model

    async def generate(
        self,
        prompt: str,
        references: list[Path],
        aspect_ratio: str,
        output: Path,
        variant: int = 1,
    ) -> GeneratedImage:
        w, h = _size(aspect_ratio)
        digest = hashlib.sha256(f"{prompt}|{variant}".encode()).digest()
        top = (80 + digest[0] % 150, 80 + digest[1] % 150, 80 + digest[2] % 150)
        img = Image.new("RGB", (w, h), top)
        draw = ImageDraw.Draw(img)
        for y in range(h):  # simple vertical gradient
            k = y / h
            draw.line([(0, y), (w, y)], fill=tuple(int(c * (1 - 0.5 * k)) for c in top))
        scene = prompt.split("SCENE:", 1)[-1].split("\n\n", 1)[0].strip() or prompt[:200]
        text = "\n".join(textwrap.wrap(scene, 48)[:6]) + f"\n\n[mock v{variant}]"
        draw.multiline_text((40, 40), text, fill=(255, 255, 255), font=_font(max(18, h // 24)))
        output.parent.mkdir(parents=True, exist_ok=True)
        img.save(output, "PNG")
        return GeneratedImage(model=self.model, usage=Usage(units=1, unit_type="images"),
                              path=output)
