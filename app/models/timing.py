"""Song timing (from alignment) and the timed storyboard derived from it."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.models.creative import LyricLine, ScenePlan


class Word(BaseModel):
    text: str
    start: float
    end: float


class Transcript(BaseModel):
    text: str = ""
    language: str | None = None
    duration: float | None = None
    words: list[Word] = Field(default_factory=list)


class TimedLine(BaseModel):
    line_id: int
    text: str
    start: float
    end: float
    confidence: float = Field(ge=0.0, le=1.0)
    source: Literal["aligned", "interpolated", "manual"]


class SongTiming(BaseModel):
    duration: float
    method: str
    lines: list[TimedLine]

    def line(self, line_id: int) -> TimedLine:
        for line in self.lines:
            if line.line_id == line_id:
                return line
        raise KeyError(line_id)


class StoryboardScene(ScenePlan):
    start: float
    end: float
    lyrics: list[LyricLine]

    @property
    def duration(self) -> float:
        return self.end - self.start


class Storyboard(BaseModel):
    duration: float
    scenes: list[StoryboardScene]

    def scene(self, scene_id: int) -> StoryboardScene:
        for s in self.scenes:
            if s.id == scene_id:
                return s
        raise KeyError(scene_id)
