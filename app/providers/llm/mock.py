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

# Fruit vocabulary per language; pinyin for Chinese.
_WORDS = {
    "vi": ["Quả táo", "Quả chuối", "Quả cam", "Quả dâu", "Quả nho", "Quả dưa hấu", "Quả xoài",
           "Quả lê"],
    "en": ["apple", "banana", "orange", "strawberry", "grapes", "watermelon", "mango", "pear"],
    "zh": ["苹果", "香蕉", "橙子", "草莓", "葡萄", "西瓜", "芒果", "梨"],
    "es": ["la manzana", "el plátano", "la naranja", "la fresa", "las uvas", "la sandía",
           "el mango", "la pera"],
}
_PINYIN = ["píng guǒ", "xiāng jiāo", "chéng zi", "cǎo méi", "pú tao", "xī guā", "máng guǒ", "lí"]


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
    prim_lang, sec_lang = langs["primary"], langs["secondary"]

    def word(lang: str, i: int) -> str:
        return _WORDS[lang][i] if lang in _WORDS else f"{lang} word {i + 1}"

    chars = [c["id"] for c in ctx.get("characters", [])]
    n = max(4, min(len(_PINYIN), int(ctx.get("duration_target_seconds", 60)) // 6))
    chinese = "zh" in (prim_lang, sec_lang)
    lyrics, scenes = [], []
    for i in range(n):
        prim, sec, en = word(prim_lang, i), word(sec_lang, i), _WORDS["en"][i]
        lyrics.append({
            "id": i + 1,
            "section": "chorus" if (i + 1) % 4 == 0 else "verse",
            "sung": f"{prim}, {sec}!",
            "primary": f"{prim}!",
            "secondary": f"{sec}!",
            "romanization": _PINYIN[i] if chinese else "",
        })
        who = chars[i % len(chars)] if chars else None
        scenes.append({
            "id": i + 1,
            "lyric_line_ids": [i + 1],
            "characters": chars if (i + 1) % 3 == 0 else ([who] if who else []),
            "action": f"{who or 'A child'} holds up one {en} and smiles at the viewer.",
            "composition": "medium shot, character centered",
            "objects": [{"name": en, "count": 1, "description": ""}],
            "motion_prompt": f"{who or 'The child'} gently lifts the {en} and blinks happily.",
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
