"""AI Creative Director: ProjectSpec -> CreativePlan (bilingual lyrics + storyboard)."""

from __future__ import annotations

import json
import shutil

from app.models.creative import CreativePlan, validate_plan_against_spec
from app.models.state import Gate
from app.pipeline.context import PipelineContext
from app.services.character_bible import load_bibles
from app.utils.files import list_versions, read_json, write_json

LANGUAGE_NAMES = {"vi": "Vietnamese", "en": "English", "es": "Spanish", "fr": "French",
                  "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "de": "German"}


def lang_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)


SYSTEM_PROMPT = """\
You are the creative director of a YouTube channel of bilingual {primary}/{secondary} music \
videos for children aged {age_min}-{age_max}. You write short, catchy, repetitive songs that \
teach vocabulary in both languages, and you plan one simple, clearly drawable scene per lyric \
line or two.

Rules:
- Lyrics: simple words a {age_min}-year-old can repeat. Lots of repetition, a memorable chorus.
- Each lyric line has: `sung` (exactly what is sung, may mix both languages, e.g. \
"Quả táo, apple!"), `primary` ({primary} line) and `secondary` (faithful {secondary} line \
teaching the same concept).
- List EVERY sung line in order, including each repetition of the chorus (new id each time).
- Scenes cover the lyric lines in order; each scene covers 1-2 consecutive lines.
- Only use the character ids provided. Describe actions concretely (what is held, counted, \
pointed at). Avoid text/signs in scenes.
- motion_prompt: small, gentle movements suitable for a 5-10 second image-to-video clip.
- Do not describe characters' appearance or art style; that is injected separately.
"""


def _context(ctx: PipelineContext) -> dict:
    spec = ctx.spec
    return {
        "project_title": spec.project.title,
        "topic": spec.creative.topic,
        "learning_goal": spec.creative.learning_goal,
        "tone": spec.creative.tone,
        "languages": spec.languages.model_dump(),
        "duration_target_seconds": spec.creative.duration_target_seconds,
        "suggested_line_count": max(6, spec.creative.duration_target_seconds // 5),
        "music_preferences": {
            "style": spec.creative.music_style,
            "tempo_bpm": spec.creative.tempo_bpm,
            "vocal_description": spec.creative.vocal_description,
        },
        "characters": [{"id": b.name, "definition": b.definition()} for b in load_bibles(ctx)],
        "default_environment": spec.environment.default,
    }


def user_prompt(ctx: PipelineContext) -> str:
    return (
        "Write the song and storyboard for this project.\n"
        f"<context>\n{json.dumps(_context(ctx), ensure_ascii=False, indent=2)}\n</context>"
    )


async def generate_plan(ctx: PipelineContext, *, force: bool = False) -> CreativePlan:
    paths = ctx.paths
    if paths.creative_plan.exists() and not force:
        return ctx.plan()
    spec = ctx.spec
    system = SYSTEM_PROMPT.format(
        primary=lang_name(spec.languages.primary),
        secondary=lang_name(spec.languages.secondary),
        age_min=spec.project.target_age_min,
        age_max=spec.project.target_age_max,
    )
    result = await ctx.llm("lyrics").generate_structured(
        system,
        user_prompt(ctx),
        CreativePlan,
        extra_validator=lambda plan: validate_plan_against_spec(plan, spec),
        max_attempts=ctx.config.llm_max_attempts,
    )
    save_plan(ctx, result.value)
    return result.value


def save_plan(ctx: PipelineContext, plan: CreativePlan) -> None:
    """Write creative_plan.json, keeping every previous version in history/."""
    paths = ctx.paths
    if paths.creative_plan.exists():
        n = (list_versions(paths.history, "creative_plan", ".json") or [(0, None)])[-1][0] + 1
        paths.history.mkdir(parents=True, exist_ok=True)
        shutil.copy2(paths.creative_plan, paths.history / f"creative_plan_v{n}.json")
    write_json(paths.creative_plan, plan.model_dump())
    ctx.revoke(Gate.lyrics)


def update_plan(ctx: PipelineContext, data: dict) -> CreativePlan:
    """Human edit of the plan (validated the same way as LLM output)."""
    plan = CreativePlan.model_validate(data)
    errors = validate_plan_against_spec(plan, ctx.spec)
    if errors:
        raise ValueError("; ".join(errors))
    if ctx.paths.creative_plan.exists() and read_json(ctx.paths.creative_plan) == plan.model_dump():
        return plan
    save_plan(ctx, plan)
    return plan
