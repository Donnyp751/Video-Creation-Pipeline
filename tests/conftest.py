from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.core.config import Workspace
from app.pipeline.context import PipelineContext
from app.pipeline.project_factory import create_project
from app.utils.ffmpeg import ffmpeg_available

REPO = Path(__file__).resolve().parents[1]


def pytest_collection_modifyitems(config, items):
    if ffmpeg_available():
        return
    skip = pytest.mark.skip(reason="ffmpeg/ffprobe not installed")
    for item in items:
        if "ffmpeg" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def workspace(tmp_path, monkeypatch) -> Workspace:
    """An isolated workspace with the repo's config and assets, using mock providers."""
    for key in ("OPENAI_API_KEY", "ELEVENLABS_API_KEY", "RUNWAY_API_KEY", "KIDSVIDEO_HOME"):
        monkeypatch.delenv(key, raising=False)
    shutil.copytree(REPO / "config", tmp_path / "config")
    shutil.copytree(REPO / "assets", tmp_path / "assets")
    return Workspace(tmp_path, mock=True)


@pytest.fixture
def ctx(workspace) -> PipelineContext:
    create_project(workspace, "fruit-song", title="Trái Cây Gì Đây?", topic="fruit",
                   duration=20)
    return PipelineContext(workspace, "fruit-song")
