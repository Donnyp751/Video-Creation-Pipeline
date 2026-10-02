"""YouTube metadata (youtube.json)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TitleOption(BaseModel):
    title: str = Field(max_length=100)
    description: str


class YouTubeMetadataDraft(BaseModel):
    """What the LLM produces."""

    title: str = Field(max_length=100)
    description: str
    tags: list[str] = Field(default_factory=list)
    playlist: str = ""
    alternates: list[TitleOption] = Field(default_factory=list)


class YouTubeMetadata(BaseModel):
    """What we write: the draft plus fields we set deterministically."""

    title: str
    description: str
    tags: list[str]
    language: str
    playlist: str
    made_for_kids: bool = True
    alternates: list[TitleOption] = Field(default_factory=list)
