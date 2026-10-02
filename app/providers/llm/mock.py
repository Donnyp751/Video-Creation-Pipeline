"""Offline LLM that returns deterministic, schema-valid data. Used for tests and dry runs.

Services embed their inputs as ``<context>{json}</context>`` in the user message; the mock reads
that context to produce plausible output (e.g. a plan that uses the project's character ids).
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.providers.common import Usage
from app.providers.llm.base import ChatMessage, LLMProvider, LLMResponse

_VOCAB = {
    ("vi", "en"): [
        ("Quả táo", "apple", "The apple is red"),
        ("Quả chuối", "banana", "The banana is yellow"),
        ("Quả cam", "orange", "The orange is round"),
        ("Quả dâu", "strawberry", "The strawberry is sweet"),
        ("Quả nho", "grapes", "Purple grapes"),
        ("Quả dưa hấu", "watermelon", "A big watermelon"),
        ("Quả xoài", "mango", "A juicy mango"),
        ("Quả lê", "pear", "A green pear"),
    ]
}


def extract_context(messages: list[ChatMessage]) -> dict[str, Any]:
    for m in reversed(messages):
        if m.role != "user":
            continue
        match = re.search(r"<context>\s*(.*?)\s*</context>", m.text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
    return {}


def _plan(ctx: dict[str, Any]) -> dict[str, Any]:
    langs = ctx.get("languages", {"primary": "vi", "secondary": "en"})
    vocab = _VOCAB.get((langs["primary"], langs["secondary"])) or [
        (f"{langs['primary']} word {i}", f"word {i}", f"Sentence {i}") for i in range(1, 9)
    ]
    chars = [c["id"] for c in ctx.get("characters", [])]
    n = max(4, min(len(vocab), int(ctx.get("duration_target_seconds", 60)) // 6))
    lyrics, scenes = [], []
    for i, (prim, sec, sentence) in enumerate(vocab[:n], start=1):
        lyrics.append({
            "id": i,
            "section": "chorus" if i % 4 == 0 else "verse",
            "sung": f"{prim}, {sec}!",
            "primary": f"{prim}!",
            "secondary": f"{sentence}!",
        })
        who = chars[(i - 1) % len(chars)] if chars else None
        scenes.append({
            "id": i,
            "lyric_line_ids": [i],
            "characters": chars if i % 3 == 0 else ([who] if who else []),
            "action": f"{who or 'A child'} holds up one {sec} and smiles at the viewer.",
            "composition": "medium shot, character centered",
            "objects": [{"name": sec, "count": 1, "description": ""}],
            "motion_prompt": f"{who or 'The child'} gently lifts the {sec} and blinks happily.",
            "camera": "slow push in",
        })
    return {
        "title": ctx.get("project_title", "Mock Song"),
        "title_secondary": "Mock Song",
        "summary": "Offline mock plan.",
        "music": {
            "style": "bouncy ukulele children's pop",
            "tempo_bpm": 110,
            "mood": "cheerful",
            "vocal_description": "bright friendly female voice",
        },
        "lyrics": lyrics,
        "scenes": scenes,
    }


_CHECKS_IMAGE = ["character_identity", "clothing", "hairstyle", "objects", "object_count",
                 "no_text", "anatomy", "toddler_appropriate", "action_matches", "style_matches"]
_CHECKS_VIDEO = ["character_consistency", "face_stable", "anatomy", "objects_stable",
                 "no_unexpected_characters", "camera_ok", "no_artifacts", "characters_in_frame",
                 "matches_source_image"]


def _metadata(ctx: dict[str, Any]) -> dict[str, Any]:
    title = ctx.get("title", "Mock Song")
    return {
        "title": f"{title} | Bilingual Kids Song"[:100],
        "description": f"A cheerful bilingual song about {ctx.get('topic', 'learning')}.",
        "tags": ["kids songs", "bilingual", str(ctx.get("topic", "learning"))],
        "playlist": "Bilingual Songs",
        "alternates": [{"title": f"{title} - Learn Together"[:100], "description": "Sing along!"}],
    }


class MockLLM(LLMProvider):
    name = "mock"

    def __init__(self, model: str = "mock-llm"):
        self.model = model

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        json_mode: bool = True,
        schema_name: str | None = None,
    ) -> LLMResponse:
        ctx = extract_context(messages)
        data: dict[str, Any]
        match schema_name:
            case "CreativePlan":
                data = _plan(ctx)
            case "LanguageReview":
                data = {"pass": True, "summary": "Mock review: no issues.", "issues": []}
            case "VisualReview":
                data = {"overall": "pass", "checks": dict.fromkeys(_CHECKS_IMAGE, True),
                        "problems": []}
            case "VideoReview":
                data = {"overall": "pass", "checks": dict.fromkeys(_CHECKS_VIDEO, True),
                        "problems": []}
            case "YouTubeMetadataDraft":
                data = _metadata(ctx)
            case _:
                data = {}
        text = json.dumps(data, ensure_ascii=False)
        prompt_chars = sum(len(m.text) for m in messages)
        return LLMResponse(model=self.model, usage=Usage(prompt_chars // 4, len(text) // 4),
                           text=text)
