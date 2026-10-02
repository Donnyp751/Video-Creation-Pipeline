"""Canonical on-disk layout of a project. Every stage reads and writes through here."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    root: Path

    @property
    def project_id(self) -> str:
        return self.root.name

    # --- specification & state -------------------------------------------------------------
    @property
    def spec(self) -> Path:
        return self.root / "project.yaml"

    @property
    def state(self) -> Path:
        return self.root / "state.json"

    @property
    def history(self) -> Path:
        return self.root / "history"

    # --- creative ------------------------------------------------------------------------------
    @property
    def creative_plan(self) -> Path:
        return self.root / "creative_plan.json"

    @property
    def language_review(self) -> Path:
        return self.root / "language_review.json"

    # --- audio ---------------------------------------------------------------------------------
    @property
    def audio(self) -> Path:
        return self.root / "audio"

    @property
    def song(self) -> Path:
        return self.audio / "song.wav"

    @property
    def music_request(self) -> Path:
        return self.audio / "music_request.json"

    @property
    def music_response(self) -> Path:
        return self.audio / "music_response.json"

    @property
    def transcript(self) -> Path:
        return self.audio / "transcript.json"

    @property
    def timing(self) -> Path:
        return self.root / "timing.json"

    @property
    def storyboard(self) -> Path:
        return self.root / "storyboard.json"

    # --- scenes --------------------------------------------------------------------------------
    @property
    def scenes(self) -> Path:
        return self.root / "scenes"

    def scene_dir(self, scene_id: int) -> Path:
        return self.scenes / f"{scene_id:03d}"

    # --- outputs -------------------------------------------------------------------------------
    @property
    def subtitles(self) -> Path:
        return self.root / "subtitles"

    @property
    def renders(self) -> Path:
        return self.root / "render"

    def render_dir(self, preset: str) -> Path:
        return self.renders / preset

    @property
    def output(self) -> Path:
        return self.root / "output"

    def output_video(self, preset: str) -> Path:
        return self.output / f"{self.project_id}-{preset}.mp4"

    @property
    def thumbnail(self) -> Path:
        return self.root / "thumbnail"

    @property
    def youtube(self) -> Path:
        return self.root / "youtube.json"
