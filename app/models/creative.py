"""CreativePlan: structured output of the AI Creative Director (lyrics + storyboard)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.project import ProjectSpec

Section = Literal["intro", "verse", "pre_chorus", "chorus", "bridge", "outro"]


class MusicDirection(BaseModel):
    style: str = Field(description="Genre / arrangement, e.g. 'bouncy ukulele pop for toddlers'")
    tempo_bpm: int = Field(ge=50, le=220)
    mood: str
    vocal_description: str = Field(description="Singer(s), e.g. 'bright female child-friendly voice'")


class LyricLine(BaseModel):
    id: int = Field(ge=1, description="1-based, in sung order. Repeated choruses get new ids.")
    section: Section
    sung: str = Field(min_length=1, description="Exactly what is sung, mixing languages as sung")
    primary: str = Field(min_length=1, description="The line in the primary language")
    secondary: str = Field(min_length=1, description="The line in the secondary language")


class ObjectSpec(BaseModel):
    name: str
    count: int = Field(default=1, ge=0)
    description: str = ""


class ScenePlan(BaseModel):
    id: int = Field(ge=1)
    lyric_line_ids: list[int] = Field(min_length=1, description="Consecutive lyric ids covered")
    characters: list[str] = Field(default_factory=list, description="Character ids visible")
    environment: str | None = Field(default=None, description="Override of the default setting")
    action: str = Field(min_length=1, description="What happens, concretely and visually")
    composition: str = Field(default="", description="Shot framing, e.g. 'medium two-shot'")
    objects: list[ObjectSpec] = Field(default_factory=list)
    motion_prompt: str = Field(min_length=1, description="Gentle motion for image-to-video")
    camera: str = Field(default="static", description="e.g. 'slow push in'")


class CreativePlan(BaseModel):
    title: str
    title_secondary: str = ""
    summary: str = ""
    music: MusicDirection
    lyrics: list[LyricLine] = Field(min_length=1)
    scenes: list[ScenePlan] = Field(min_length=1)

    @model_validator(mode="after")
    def _structure(self) -> CreativePlan:
        line_ids = [line.id for line in self.lyrics]
        if line_ids != list(range(1, len(line_ids) + 1)):
            raise ValueError("lyrics ids must be 1..N in sung order")
        scene_ids = [s.id for s in self.scenes]
        if scene_ids != list(range(1, len(scene_ids) + 1)):
            raise ValueError("scene ids must be 1..N in order")

        covered: list[int] = []
        for scene in self.scenes:
            ids = scene.lyric_line_ids
            if ids != list(range(ids[0], ids[0] + len(ids))):
                raise ValueError(f"scene {scene.id}: lyric_line_ids must be consecutive")
            covered.extend(ids)
        if covered != line_ids:
            raise ValueError(
                "scenes must cover every lyric line exactly once, in order "
                f"(covered {covered}, expected {line_ids})"
            )
        return self

    def line(self, line_id: int) -> LyricLine:
        return self.lyrics[line_id - 1]

    def scene(self, scene_id: int) -> ScenePlan:
        for s in self.scenes:
            if s.id == scene_id:
                return s
        raise KeyError(scene_id)


def validate_plan_against_spec(plan: CreativePlan, spec: ProjectSpec) -> list[str]:
    """Semantic checks that need the project (fed back to the LLM on retry)."""
    errors: list[str] = []
    known = set(spec.character_ids)
    for scene in plan.scenes:
        unknown = [c for c in scene.characters if c not in known]
        if unknown:
            errors.append(
                f"scene {scene.id}: unknown character ids {unknown}; use only {sorted(known)}"
            )
        if len(set(scene.characters)) != len(scene.characters):
            errors.append(f"scene {scene.id}: duplicate characters")
    if len(plan.scenes) < 4:
        errors.append("plan must have at least 4 scenes")
    return errors
