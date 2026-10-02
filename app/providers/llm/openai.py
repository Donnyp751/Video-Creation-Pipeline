from __future__ import annotations

from openai import AsyncOpenAI

from app.providers.common import Usage, data_uri
from app.providers.llm.base import ChatMessage, LLMProvider, LLMResponse


class OpenAILLM(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        json_mode: bool = True,
        schema_name: str | None = None,
    ) -> LLMResponse:
        payload = []
        for m in messages:
            if m.images:
                content: object = [{"type": "text", "text": m.text}] + [
                    {"type": "image_url", "image_url": {"url": data_uri(p)}} for p in m.images
                ]
            else:
                content = m.text
            payload.append({"role": m.role, "content": content})

        kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
        resp = await self.client.chat.completions.create(
            model=self.model, messages=payload, **kwargs
        )
        usage = Usage()
        if resp.usage:
            usage = Usage(resp.usage.prompt_tokens or 0, resp.usage.completion_tokens or 0)
        return LLMResponse(
            model=resp.model or self.model,
            usage=usage,
            raw={"id": resp.id, "finish_reason": resp.choices[0].finish_reason},
            text=resp.choices[0].message.content or "",
        )
