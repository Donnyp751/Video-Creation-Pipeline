"""Decorators around real providers that add caching and cost tracking.

Services talk to these wrappers and never need to know about either concern. Each wrapper is
created for one *scope* (project + stage + optional scene) so calls are attributed correctly.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

from app.models.timing import Transcript
from app.providers.common import Usage
from app.providers.image.base import GeneratedImage, ImageProvider
from app.providers.llm.base import ChatMessage, LLMProvider, LLMResponse
from app.providers.music.base import GeneratedAudio, MusicProvider, MusicRequest
from app.providers.speech.base import SpeechProvider, TranscriptionResult
from app.providers.video.base import GeneratedVideo, VideoProvider
from app.services.cache import ProviderCache
from app.services.cost_tracker import CallScope, CostTracker


class _Tracking:
    def __init__(self, inner: Any, scope: CallScope, tracker: CostTracker, cache: ProviderCache,
                 use_cache: bool):
        self.inner = inner
        self.scope = scope
        self.tracker = tracker
        self.cache = cache
        self.use_cache = use_cache
        self.name = inner.name
        self.model = inner.model

    def _key(self, operation: str, params: dict[str, Any], files: list[Path] = ()) -> str:
        return self.cache.key({
            "provider": self.name,
            "model": self.model,
            "operation": operation,
            "params": params,
            "files": self.cache.file_fingerprints(list(files)),
        })

    def _hit(self, operation: str, key: str) -> None:
        self.tracker.record(self.scope, provider=self.name, model=self.model,
                            operation=operation, cache_hit=True, request_hash=key)

    async def _call(self, operation: str, key: str, coro):
        t0 = time.monotonic()
        try:
            result = await coro
        except Exception as e:
            self.tracker.record(self.scope, provider=self.name, model=self.model,
                                operation=operation, success=False, error=str(e)[:2000],
                                duration_s=time.monotonic() - t0, request_hash=key)
            raise
        self.tracker.record(self.scope, provider=self.name, model=result.model or self.model,
                            operation=operation, usage=result.usage,
                            duration_s=time.monotonic() - t0, request_hash=key)
        return result


class TrackedLLM(_Tracking, LLMProvider):
    async def complete(self, messages: list[ChatMessage], *, json_mode: bool = True,
                       schema_name: str | None = None) -> LLMResponse:
        images = [p for m in messages for p in m.images]
        params = {"messages": [(m.role, m.text) for m in messages], "json": json_mode}
        key = self._key("chat", params, images)
        if self.use_cache and (hit := self.cache.get_json(key)) is not None:
            self._hit("chat", key)
            return LLMResponse(model=self.model, text=hit["text"], cache_hit=True)
        resp = await self._call("chat", key, self.inner.complete(
            messages, json_mode=json_mode, schema_name=schema_name))
        self.cache.put_json(key, {"text": resp.text, "model": resp.model})
        return resp


class TrackedImage(_Tracking, ImageProvider):
    async def generate(self, prompt: str, references: list[Path], aspect_ratio: str,
                       output: Path, variant: int = 1) -> GeneratedImage:
        params = {"prompt": prompt, "aspect_ratio": aspect_ratio, "variant": variant}
        key = self._key("image", params, references)
        if self.use_cache and (hit := self.cache.get_file(key, output.suffix)):
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(hit, output)
            self._hit("image", key)
            return GeneratedImage(model=self.model, path=output, cache_hit=True)
        result = await self._call("image", key, self.inner.generate(
            prompt, references, aspect_ratio, output, variant))
        self.cache.put_file(key, result.path)
        return result


class TrackedMusic(_Tracking, MusicProvider):
    @property
    def output_extension(self) -> str:  # type: ignore[override]
        return self.inner.output_extension

    async def compose(self, request: MusicRequest, output: Path, variant: int = 1) -> GeneratedAudio:
        key = self._key("music", {"request": request.model_dump(), "variant": variant})
        if self.use_cache and (hit := self.cache.get_file(key, output.suffix)):
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(hit, output)
            self._hit("music", key)
            return GeneratedAudio(model=self.model, path=output, cache_hit=True)
        result = await self._call("music", key, self.inner.compose(request, output, variant))
        self.cache.put_file(key, result.path)
        return result


class TrackedVideo(_Tracking, VideoProvider):
    async def image_to_video(self, image: Path, prompt: str, duration: float, aspect_ratio: str,
                             output: Path, variant: int = 1) -> GeneratedVideo:
        params = {"prompt": prompt, "duration": round(duration, 2), "aspect_ratio": aspect_ratio,
                  "variant": variant}
        key = self._key("image_to_video", params, [image])
        if self.use_cache and (hit := self.cache.get_file(key, output.suffix)):
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(hit, output)
            self._hit("image_to_video", key)
            return GeneratedVideo(model=self.model, path=output, cache_hit=True)
        result = await self._call("image_to_video", key, self.inner.image_to_video(
            image, prompt, duration, aspect_ratio, output, variant))
        self.cache.put_file(key, result.path)
        return result


class TrackedSpeech(_Tracking, SpeechProvider):
    async def transcribe(self, audio: Path, *, language: str | None = None,
                         prompt: str | None = None) -> TranscriptionResult:
        key = self._key("transcribe", {"language": language, "prompt": prompt}, [audio])
        if self.use_cache and (hit := self.cache.get_json(key)) is not None:
            self._hit("transcribe", key)
            return TranscriptionResult(model=self.model, usage=Usage(), cache_hit=True,
                                       transcript=Transcript.model_validate(hit))
        result = await self._call("transcribe", key, self.inner.transcribe(
            audio, language=language, prompt=prompt))
        self.cache.put_json(key, result.transcript.model_dump())
        return result
