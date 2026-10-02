from __future__ import annotations

import base64
from contextlib import ExitStack
from pathlib import Path

from openai import AsyncOpenAI

from app.providers.common import ProviderError, Usage
from app.providers.image.base import GeneratedImage, ImageProvider
from app.utils.files import write_bytes


def size_for_aspect(aspect_ratio: str) -> str:
    a, b = (int(x) for x in aspect_ratio.split(":"))
    if a > b:
        return "1536x1024"
    if a < b:
        return "1024x1536"
    return "1024x1024"


class OpenAIImage(ImageProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str, quality: str = "medium"):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model
        self.quality = quality

    async def generate(
        self,
        prompt: str,
        references: list[Path],
        aspect_ratio: str,
        output: Path,
        variant: int = 1,
    ) -> GeneratedImage:
        size = size_for_aspect(aspect_ratio)
        if references:
            # Reference images (character bible, environment) steer identity and style.
            with ExitStack() as stack:
                files = [stack.enter_context(p.open("rb")) for p in references]
                resp = await self.client.images.edit(
                    model=self.model, image=files, prompt=prompt, size=size,
                    quality=self.quality, input_fidelity="high",
                )
        else:
            resp = await self.client.images.generate(
                model=self.model, prompt=prompt, size=size, quality=self.quality
            )
        if not resp.data or not resp.data[0].b64_json:
            raise ProviderError("image API returned no image data")
        write_bytes(output, base64.b64decode(resp.data[0].b64_json))
        usage = Usage(units=1, unit_type="images")
        if getattr(resp, "usage", None):
            usage.input_tokens = resp.usage.input_tokens or 0
            usage.output_tokens = resp.usage.output_tokens or 0
        return GeneratedImage(model=self.model, usage=usage, path=output,
                              raw={"size": size, "references": [str(p) for p in references]})
