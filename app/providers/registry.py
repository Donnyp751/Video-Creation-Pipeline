"""Maps provider names from project.yaml to implementations.

Adding a provider = implement the family's base class and register a factory here. Pipeline code
does not change.
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.config import Workspace
from app.providers.common import ProviderError, require_key
from app.providers.image.base import ImageProvider
from app.providers.llm.base import LLMProvider
from app.providers.music.base import MusicProvider
from app.providers.speech.base import SpeechProvider
from app.providers.video.base import VideoProvider


def _openai_llm(ws: Workspace, vision: bool = False) -> LLMProvider:
    from app.providers.llm.openai import OpenAILLM

    m = ws.config.models
    return OpenAILLM(require_key(ws.secrets.openai_api_key, "OPENAI_API_KEY"),
                     m.openai_vision if vision else m.openai_llm)


def _mock_llm(ws: Workspace, vision: bool = False) -> LLMProvider:
    from app.providers.llm.mock import MockLLM

    return MockLLM()


def _openai_image(ws: Workspace) -> ImageProvider:
    from app.providers.image.openai import OpenAIImage

    m = ws.config.models
    return OpenAIImage(require_key(ws.secrets.openai_api_key, "OPENAI_API_KEY"), m.openai_image,
                       m.openai_image_quality)


def _mock_image(ws: Workspace) -> ImageProvider:
    from app.providers.image.mock import MockImage

    return MockImage()


def _elevenlabs_music(ws: Workspace) -> MusicProvider:
    from app.providers.music.elevenlabs import ElevenLabsMusic

    return ElevenLabsMusic(require_key(ws.secrets.elevenlabs_api_key, "ELEVENLABS_API_KEY"),
                           ws.config.models.elevenlabs_music)


def _mock_music(ws: Workspace) -> MusicProvider:
    from app.providers.music.mock import MockMusic

    return MockMusic()


def _runway_video(ws: Workspace) -> VideoProvider:
    from app.providers.video.runway import RunwayVideo

    return RunwayVideo(require_key(ws.secrets.runway_api_key, "RUNWAY_API_KEY"),
                       ws.config.models.runway_video)


def _mock_video(ws: Workspace) -> VideoProvider:
    from app.providers.video.mock import MockVideo

    return MockVideo()


def _openai_speech(ws: Workspace) -> SpeechProvider:
    from app.providers.speech.openai import OpenAISpeech

    return OpenAISpeech(require_key(ws.secrets.openai_api_key, "OPENAI_API_KEY"),
                        ws.config.models.openai_transcription)


def _mock_speech(ws: Workspace) -> SpeechProvider:
    from app.providers.speech.mock import MockSpeech

    return MockSpeech()


LLM: dict[str, Callable[..., LLMProvider]] = {"openai": _openai_llm, "mock": _mock_llm}
IMAGE: dict[str, Callable[[Workspace], ImageProvider]] = {"openai": _openai_image,
                                                          "mock": _mock_image}
MUSIC: dict[str, Callable[[Workspace], MusicProvider]] = {"elevenlabs": _elevenlabs_music,
                                                          "mock": _mock_music}
VIDEO: dict[str, Callable[[Workspace], VideoProvider]] = {"runway": _runway_video,
                                                          "mock": _mock_video}
SPEECH: dict[str, Callable[[Workspace], SpeechProvider]] = {"openai": _openai_speech,
                                                            "mock": _mock_speech}


def _pick(table: dict, family: str, name: str, ws: Workspace):
    key = "mock" if ws.mock else name
    try:
        return table[key]
    except KeyError:
        raise ProviderError(
            f"unknown {family} provider '{name}' (available: {', '.join(sorted(table))})"
        ) from None


def build_llm(ws: Workspace, name: str, *, vision: bool = False) -> LLMProvider:
    return _pick(LLM, "llm", name, ws)(ws, vision=vision)


def build_image(ws: Workspace, name: str) -> ImageProvider:
    return _pick(IMAGE, "image", name, ws)(ws)


def build_music(ws: Workspace, name: str) -> MusicProvider:
    return _pick(MUSIC, "music", name, ws)(ws)


def build_video(ws: Workspace, name: str) -> VideoProvider:
    return _pick(VIDEO, "video", name, ws)(ws)


def build_speech(ws: Workspace, name: str) -> SpeechProvider:
    return _pick(SPEECH, "speech", name, ws)(ws)
