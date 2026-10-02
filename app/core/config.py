"""Workspace discovery, secrets (.env) and pipeline configuration (config/pipeline.yaml).

Secrets come only from the environment / ``.env``. They are never read from project YAML.
"""

from __future__ import annotations

import os
from functools import cached_property
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    openai_api_key: SecretStr | None = None
    elevenlabs_api_key: SecretStr | None = None
    runway_api_key: SecretStr | None = None
    # Force every provider to the offline mock implementation (tests, dry runs).
    kidsvideo_mock_providers: bool = False


class PriceEntry(BaseModel):
    """Estimated prices in USD. Edit config/pipeline.yaml to match your contracts."""

    input_per_1m: float = 0.0
    output_per_1m: float = 0.0
    per_image: float = 0.0
    per_second: float = 0.0
    per_minute: float = 0.0
    per_call: float = 0.0


class RenderPreset(BaseModel):
    resolution: str = "1920x1080"
    fps: int = 30
    crf: int = 18
    x264_preset: str = "medium"
    audio_bitrate: str = "192k"
    # pad = letterbox to keep the whole frame, crop = fill the frame (e.g. 16:9 -> 9:16 Shorts)
    fit: Literal["pad", "crop"] = "pad"
    crossfade: float = 0.4
    burn_subtitles: bool = False
    # Allow approved still images in place of missing animations (fast previews).
    allow_stills: bool = False
    loudnorm: bool = True
    intro: Path | None = None
    outro: Path | None = None

    @field_validator("resolution")
    @classmethod
    def _res(cls, v: str) -> str:
        w, _, h = v.partition("x")
        if not (w.isdigit() and h.isdigit()) or int(w) % 2 or int(h) % 2:
            raise ValueError("resolution must be WIDTHxHEIGHT with even numbers")
        return v

    @property
    def width(self) -> int:
        return int(self.resolution.split("x")[0])

    @property
    def height(self) -> int:
        return int(self.resolution.split("x")[1])


class ModelsConfig(BaseModel):
    openai_llm: str = "gpt-5"
    openai_vision: str = "gpt-5"
    openai_image: str = "gpt-image-1"
    openai_image_quality: str = "medium"
    openai_transcription: str = "whisper-1"
    elevenlabs_music: str = "music_v1"
    runway_video: str = "gen4_turbo"


class ConcurrencyConfig(BaseModel):
    images: int = 3
    videos: int = 2
    reviews: int = 4


class QCConfig(BaseModel):
    duration_tolerance_s: float = 0.5
    target_lufs: float = -14.0
    lufs_tolerance: float = 3.0
    max_black_s: float = 1.0
    max_silence_s: float = 4.0


def _default_presets() -> dict[str, RenderPreset]:
    return {
        "youtube": RenderPreset(resolution="1920x1080", fps=30, crf=18),
        "youtube_shorts": RenderPreset(resolution="1080x1920", fps=30, crf=18, fit="crop",
                                       burn_subtitles=True),
        "preview": RenderPreset(resolution="854x480", fps=24, crf=30, x264_preset="veryfast",
                                audio_bitrate="96k", burn_subtitles=True, allow_stills=True),
    }


def _default_pricing() -> dict[str, dict[str, PriceEntry]]:
    return {
        "openai": {
            "gpt-5": PriceEntry(input_per_1m=1.25, output_per_1m=10.0),
            "gpt-image-1": PriceEntry(per_image=0.063),
            "whisper-1": PriceEntry(per_minute=0.006),
        },
        "elevenlabs": {"music_v1": PriceEntry(per_minute=0.80)},
        "runway": {"gen4_turbo": PriceEntry(per_second=0.05)},
    }


class PipelineConfig(BaseModel):
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    pricing: dict[str, dict[str, PriceEntry]] = Field(default_factory=_default_pricing)
    render_presets: dict[str, RenderPreset] = Field(default_factory=_default_presets)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    qc: QCConfig = Field(default_factory=QCConfig)
    llm_max_attempts: int = 3
    thumbnail_candidates: int = 3
    title_font: Path | None = None

    def price(self, provider: str, model: str) -> PriceEntry:
        return self.pricing.get(provider, {}).get(model, PriceEntry())


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


class Workspace:
    """The directory that holds ``projects/``, ``assets/``, ``config/`` and ``data/``."""

    def __init__(self, root: Path, *, mock: bool | None = None):
        self.root = root.resolve()
        env_values = {k.lower(): v for k, v in _load_env_file(self.root / ".env").items() if v}
        # Real environment variables win over .env.
        self.secrets = Secrets(**{**env_values, **_secret_env()})  # type: ignore[arg-type]
        if mock is not None:
            self.secrets.kidsvideo_mock_providers = mock

    @classmethod
    def discover(cls, *, mock: bool | None = None) -> Workspace:
        root = os.environ.get("KIDSVIDEO_HOME")
        return cls(Path(root) if root else Path.cwd(), mock=mock)

    @property
    def projects_dir(self) -> Path:
        return self.root / "projects"

    @property
    def assets_dir(self) -> Path:
        return self.root / "assets"

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def data_dir(self) -> Path:
        """Local state: SQLite DB (costs, jobs) and the provider cache."""
        return self.root / "data"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "kidsvideo.db"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def mock(self) -> bool:
        return self.secrets.kidsvideo_mock_providers

    @cached_property
    def config(self) -> PipelineConfig:
        path = self.config_dir / "pipeline.yaml"
        data: dict[str, Any] = {}
        if path.is_file():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        base = PipelineConfig().model_dump()
        return PipelineConfig.model_validate(_deep_merge(base, data))

    def resolve(self, p: Path | str) -> Path:
        """Resolve a workspace-relative path (as used in project.yaml)."""
        p = Path(p)
        return p if p.is_absolute() else self.root / p


def _secret_env() -> dict[str, str]:
    keys = ("OPENAI_API_KEY", "ELEVENLABS_API_KEY", "RUNWAY_API_KEY", "KIDSVIDEO_MOCK_PROVIDERS")
    return {k.lower(): os.environ[k] for k in keys if os.environ.get(k)}
