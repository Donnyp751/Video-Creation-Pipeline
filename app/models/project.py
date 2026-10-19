"""ProjectSpec: the machine-readable specification every video starts from (project.yaml)."""

from __future__ import annotations

from math import isclose
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SLUG = r"^[a-z0-9][a-z0-9_-]*$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectInfo(_Strict):
    id: str = Field(pattern=SLUG)
    title: str = Field(min_length=1)
    target_age_min: int = Field(ge=0, le=18)
    target_age_max: int = Field(ge=0, le=18)
    aspect_ratio: str = "16:9"
    resolution: str = "1920x1080"
    fps: int = Field(default=30, ge=12, le=60)

    @field_validator("aspect_ratio")
    @classmethod
    def _aspect(cls, v: str) -> str:
        a, _, b = v.partition(":")
        if not (a.isdigit() and b.isdigit() and int(a) > 0 and int(b) > 0):
            raise ValueError("aspect_ratio must look like '16:9'")
        return v

    @field_validator("resolution")
    @classmethod
    def _resolution(cls, v: str) -> str:
        w, _, h = v.partition("x")
        if not (w.isdigit() and h.isdigit()) or int(w) % 2 or int(h) % 2:
            raise ValueError("resolution must be WIDTHxHEIGHT with even numbers, e.g. 1920x1080")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> ProjectInfo:
        if self.target_age_min > self.target_age_max:
            raise ValueError("target_age_min must be <= target_age_max")
        w, h = self.size
        a, b = (int(x) for x in self.aspect_ratio.split(":"))
        if not isclose(w / h, a / b, rel_tol=0.02):
            raise ValueError(f"resolution {self.resolution} does not match aspect {self.aspect_ratio}")
        return self

    @property
    def size(self) -> tuple[int, int]:
        w, h = self.resolution.split("x")
        return int(w), int(h)


class Languages(_Strict):
    primary: str = Field(min_length=2, max_length=8)
    secondary: str = Field(min_length=2, max_length=8)
    # Chinese only: which characters to write, and whether to add a pinyin line to subtitles.
    script: Literal["simplified", "traditional"] = "simplified"
    romanization: bool = False

    @model_validator(mode="after")
    def _distinct(self) -> Languages:
        if self.primary == self.secondary:
            raise ValueError("primary and secondary languages must differ")
        return self

    @property
    def codes(self) -> tuple[str, str]:
        return self.primary, self.secondary


class Creative(_Strict):
    topic: str = Field(min_length=1)
    learning_goal: str = Field(min_length=1)
    tone: str = "cheerful"
    duration_target_seconds: int = Field(default=120, ge=10, le=600)
    music_style: str | None = None
    tempo_bpm: int | None = Field(default=None, ge=50, le=220)
    vocal_description: str | None = None


class CharacterRef(_Strict):
    id: str = Field(pattern=SLUG)
    reference: Path | None = None
    description: str = Field(min_length=1)


class EnvironmentSpec(_Strict):
    default: str = Field(min_length=1)
    reference: Path | None = None
    description: str | None = None


class StyleSpec(_Strict):
    description: str = Field(min_length=1)
    negative: list[str] = Field(default_factory=list)


class ProvidersSpec(_Strict):
    llm: str = "openai"
    image: str = "openai"
    music: str = "elevenlabs"
    video: str = "runway"
    speech: str = "openai"
    vision: str | None = None  # defaults to llm

    @property
    def vision_provider(self) -> str:
        return self.vision or self.llm


class ProjectSpec(_Strict):
    project: ProjectInfo
    languages: Languages
    creative: Creative
    characters: list[CharacterRef] = Field(min_length=1)
    environment: EnvironmentSpec
    style: StyleSpec
    providers: ProvidersSpec = Field(default_factory=ProvidersSpec)

    @model_validator(mode="after")
    def _unique_characters(self) -> ProjectSpec:
        ids = [c.id for c in self.characters]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate character ids: {', '.join(dupes)}")
        return self

    def character(self, character_id: str) -> CharacterRef:
        for c in self.characters:
            if c.id == character_id:
                return c
        raise KeyError(character_id)

    @property
    def character_ids(self) -> list[str]:
        return [c.id for c in self.characters]

    @classmethod
    def load(cls, path: Path) -> ProjectSpec:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path} does not contain a YAML mapping")
        return cls.model_validate(data)

    def to_yaml(self) -> str:
        data = self.model_dump(mode="json", exclude_none=True)
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
