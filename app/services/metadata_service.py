"""YouTube metadata generation (youtube.json). Publishing stays manual."""

from __future__ import annotations

import json

from app.models.metadata import YouTubeMetadata, YouTubeMetadataDraft
from app.pipeline.context import PipelineContext
from app.services.creative_director import lang_name
from app.services.subtitles import srt_timestamp
from app.utils.files import write_json

SYSTEM_PROMPT = """\
You write YouTube metadata for a bilingual {primary}/{secondary} children's music channel \
(audience: children {age_min}-{age_max} and their parents). Titles: short, searchable, \
title in {primary} first then {secondary}, no clickbait, no ALL CAPS. Description: 2 short \
paragraphs in both languages describing what children learn, plus the lyrics' key words. \
Tags: 10-20 relevant search terms in both languages. Provide 3 alternate title/description \
options. Content is made for kids; never ask viewers to comment.
"""


def chapters(ctx: PipelineContext) -> str:
    """Deterministic chapter list from the storyboard (if it exists)."""
    if not ctx.paths.storyboard.exists():
        return ""
    lines = []
    for scene in ctx.storyboard().scenes:
        stamp = srt_timestamp(scene.start).split(",")[0]
        if stamp.startswith("00:"):
            stamp = stamp[3:]
        lines.append(f"{stamp} {scene.lyrics[0].primary}")
    return "\n".join(lines) if len(lines) >= 3 else ""


async def generate_metadata(ctx: PipelineContext, *, force: bool = False) -> YouTubeMetadata:
    if ctx.paths.youtube.exists() and not force:
        return YouTubeMetadata.model_validate_json(ctx.paths.youtube.read_text("utf-8"))
    spec = ctx.spec
    plan = ctx.plan()
    system = SYSTEM_PROMPT.format(
        primary=lang_name(spec.languages.primary), secondary=lang_name(spec.languages.secondary),
        age_min=spec.project.target_age_min, age_max=spec.project.target_age_max,
    )
    context = {
        "title": plan.title,
        "title_secondary": plan.title_secondary,
        "topic": spec.creative.topic,
        "learning_goal": spec.creative.learning_goal,
        "lyrics": [{"primary": ln.primary, "secondary": ln.secondary} for ln in plan.lyrics],
    }
    user = ("Write the metadata.\n"
            f"<context>\n{json.dumps(context, ensure_ascii=False, indent=2)}\n</context>")
    draft = (await ctx.llm("metadata").generate_structured(
        system, user, YouTubeMetadataDraft, max_attempts=ctx.config.llm_max_attempts
    )).value
    description = draft.description
    if ch := chapters(ctx):
        description += "\n\n" + ch
    meta = YouTubeMetadata(
        title=draft.title,
        description=description,
        tags=sorted({t.strip() for t in draft.tags if t.strip()}, key=str.lower)[:30],
        language=spec.languages.primary,
        playlist=draft.playlist,
        made_for_kids=True,  # never left to the model
        alternates=draft.alternates,
    )
    write_json(ctx.paths.youtube, meta.model_dump())
    return meta
