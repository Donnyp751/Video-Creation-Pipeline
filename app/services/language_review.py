"""Bilingual language QA. Produces suggestions for a human; never rewrites the song."""

from __future__ import annotations

import json

from app.models.review import LanguageReview
from app.pipeline.context import PipelineContext
from app.services.creative_director import lang_name
from app.utils.files import read_json, sha256_file, write_json

SYSTEM_PROMPT = """\
You are a meticulous bilingual {primary}/{secondary} editor and early-childhood educator \
reviewing song lyrics for children aged {age_min}-{age_max}. Check every line for:
- {primary} grammar and natural, everyday vocabulary (how a parent would really say it)
- accuracy of the {secondary} translation
- whether both languages teach exactly the same concept
- age-appropriate words and pronunciation difficulty for toddlers
- useful repetition (not too little, not tedious) and overall age appropriateness
Report concrete issues with the lyric line id and a specific suggested replacement. Set "pass" \
to false if any medium or high severity issue exists. Do not rewrite the song.
"""


async def review_lyrics(ctx: PipelineContext, *, force: bool = False) -> LanguageReview:
    plan_hash = sha256_file(ctx.paths.creative_plan) if ctx.paths.creative_plan.exists() else ""
    if ctx.paths.language_review.exists() and not force:
        stored = read_json(ctx.paths.language_review)
        if stored.get("plan_hash") == plan_hash:
            return LanguageReview.model_validate(stored["review"])

    plan = ctx.plan()
    spec = ctx.spec
    system = SYSTEM_PROMPT.format(
        primary=lang_name(spec.languages.primary),
        secondary=lang_name(spec.languages.secondary),
        age_min=spec.project.target_age_min,
        age_max=spec.project.target_age_max,
    )
    context = {
        "learning_goal": spec.creative.learning_goal,
        "languages": spec.languages.model_dump(),
        "lyrics": [line.model_dump() for line in plan.lyrics],
    }
    user = ("Review these lyrics.\n"
            f"<context>\n{json.dumps(context, ensure_ascii=False, indent=2)}\n</context>")
    result = await ctx.llm("language_review").generate_structured(
        system, user, LanguageReview, max_attempts=ctx.config.llm_max_attempts
    )
    review = result.value
    valid_ids = {line.id for line in plan.lyrics} | {0}
    review.issues = [i for i in review.issues if i.line in valid_ids]
    write_json(ctx.paths.language_review,
               {"plan_hash": plan_hash, "review": review.model_dump(by_alias=True)})
    return review
