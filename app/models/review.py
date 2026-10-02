"""Structured results from the AI reviewers (language, image, video)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["low", "medium", "high"]
Verdict = Literal["pass", "warn", "fail"]


class LanguageIssue(BaseModel):
    line: int = Field(ge=0, description="Lyric line id, 0 for song-wide issues")
    category: Literal[
        "grammar", "vocabulary", "translation", "age_appropriateness", "pronunciation",
        "concept_mismatch", "repetition", "other",
    ]
    severity: Severity
    reason: str
    suggestion: str


class LanguageReview(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    passed: bool = Field(alias="pass")
    summary: str = ""
    issues: list[LanguageIssue] = Field(default_factory=list)


class VisualChecks(BaseModel):
    character_identity: bool
    clothing: bool
    hairstyle: bool
    objects: bool
    object_count: bool
    no_text: bool
    anatomy: bool
    toddler_appropriate: bool
    action_matches: bool
    style_matches: bool


class VisualReview(BaseModel):
    overall: Verdict
    checks: VisualChecks
    problems: list[str] = Field(default_factory=list)


class VideoChecks(BaseModel):
    character_consistency: bool
    face_stable: bool
    anatomy: bool
    objects_stable: bool
    no_unexpected_characters: bool
    camera_ok: bool
    no_artifacts: bool
    characters_in_frame: bool
    matches_source_image: bool


class VideoReview(BaseModel):
    overall: Verdict
    checks: VideoChecks
    problems: list[str] = Field(default_factory=list)
