"""LLM provider interface plus validated structured generation with retry-on-error."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from app.providers.common import ProviderError, ProviderOutput, Usage


@dataclass
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    text: str
    images: list[Path] = field(default_factory=list)


@dataclass
class LLMResponse(ProviderOutput):
    text: str = ""


class StructuredOutputError(ProviderError):
    def __init__(self, errors: list[str], responses: list[LLMResponse]):
        self.errors = errors
        self.responses = responses
        super().__init__("LLM did not return valid data:\n- " + "\n- ".join(errors))


@dataclass
class StructuredResult[T: BaseModel]:
    value: T
    attempts: int
    responses: list[LLMResponse]

    @property
    def usage(self) -> Usage:
        total = Usage()
        for r in self.responses:
            total = total + r.usage
        return total


def parse_json_text(text: str) -> object:
    text = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    return json.loads(text)


def format_validation_error(err: ValidationError) -> list[str]:
    out = []
    for e in err.errors():
        loc = ".".join(str(p) for p in e["loc"]) or "<root>"
        out.append(f"{loc}: {e['msg']}")
    return out


def schema_instructions(model: type[BaseModel]) -> str:
    schema = json.dumps(model.model_json_schema(by_alias=True), ensure_ascii=False)
    return (
        "Respond with a single JSON object only (no markdown, no commentary) that validates "
        f"against this JSON Schema:\n{schema}"
    )


class LLMProvider(ABC):
    name: str
    model: str

    @abstractmethod
    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        json_mode: bool = True,
        schema_name: str | None = None,
    ) -> LLMResponse:
        """One chat completion. ``schema_name`` is a hint used only by offline mocks."""

    async def generate_structured[T: BaseModel](
        self,
        system: str,
        user: str,
        response_model: type[T],
        *,
        images: list[Path] | None = None,
        extra_validator: Callable[[T], list[str]] | None = None,
        max_attempts: int = 3,
    ) -> StructuredResult[T]:
        """Ask for JSON matching ``response_model``; on invalid output, retry with the errors."""
        messages = [
            ChatMessage("system", f"{system}\n\n{schema_instructions(response_model)}"),
            ChatMessage("user", user, list(images or [])),
        ]
        responses: list[LLMResponse] = []
        errors: list[str] = []
        for attempt in range(1, max_attempts + 1):
            resp = await self.complete(messages, json_mode=True,
                                       schema_name=response_model.__name__)
            responses.append(resp)
            try:
                value = response_model.model_validate(parse_json_text(resp.text))
                errors = extra_validator(value) if extra_validator else []
            except json.JSONDecodeError as e:
                errors = [f"response is not valid JSON: {e}"]
            except ValidationError as e:
                errors = format_validation_error(e)
            if not errors:
                return StructuredResult(value, attempt, responses)
            messages += [
                ChatMessage("assistant", resp.text),
                ChatMessage(
                    "user",
                    "Your previous response was invalid:\n- " + "\n- ".join(errors)
                    + "\nReturn the complete corrected JSON object.",
                ),
            ]
        raise StructuredOutputError(errors, responses)
