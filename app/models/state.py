"""Workflow state persisted next to the artifacts: approvals and per-scene asset versions."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Gate(StrEnum):
    """Human approval gates of the build pipeline."""

    lyrics = "lyrics"
    storyboard = "storyboard"
    images = "images"
    videos = "videos"
    preview = "preview"


class Approval(BaseModel):
    approved_at: str
    # Hash of the artifact that was approved. If the artifact changes, the approval is stale.
    artifact_hash: str
    note: str = ""


class ProjectState(BaseModel):
    approvals: dict[str, Approval] = Field(default_factory=dict)


AssetStatus = Literal[
    "not_generated",  # nothing yet
    "generating",
    "generated",      # generated, not reviewed by AI yet
    "ai_passed",      # AI review passed, waiting for a human
    "needs_review",   # AI review flagged problems
    "approved",       # human approved
    "rejected",       # human rejected the selected version
    "failed",         # provider error
]


class AssetVersion(BaseModel):
    version: int
    file: str
    prompt: str
    created_at: str
    provider: str
    model: str
    cache_hit: bool = False
    duration: float | None = None
    review: dict[str, Any] | None = None


class AssetTrack(BaseModel):
    status: AssetStatus = "not_generated"
    selected: int | None = None
    versions: list[AssetVersion] = Field(default_factory=list)
    error: str | None = None
    approved_at: str | None = None

    def version(self, n: int) -> AssetVersion:
        for v in self.versions:
            if v.version == n:
                return v
        raise KeyError(n)

    @property
    def selected_version(self) -> AssetVersion | None:
        return self.version(self.selected) if self.selected is not None else None


class SceneState(BaseModel):
    scene_id: int
    image: AssetTrack = Field(default_factory=AssetTrack)
    video: AssetTrack = Field(default_factory=AssetTrack)
