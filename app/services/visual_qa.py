"""AI visual QA for scene images and animations. Flags problems; never regenerates."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.core.progress import report
from app.models.review import VideoReview, VisualReview
from app.models.state import AssetTrack
from app.pipeline.context import PipelineContext
from app.services.character_bible import load_bibles, reference_images
from app.services.scene_assets import Track, track_of
from app.utils.ffmpeg import extract_frames, media_duration

IMAGE_SYSTEM = """\
You are a strict visual QA inspector for a children's cartoon production. You compare a \
generated image against the scene specification and character reference definitions. \
Judge only concrete, checkable facts. The FIRST image is the one under review; any further \
images are character reference images, in the order the characters are listed.
- overall = "fail" if a character is wrong/missing/extra, clothing or hairstyle differs from \
the definition, required objects are missing or miscounted, there is visible text, or anatomy \
is broken.
- overall = "warn" for minor issues a human should look at. Otherwise "pass".
List each problem as a short concrete sentence (e.g. "Boy is wearing a blue shirt instead of \
green.").
"""

VIDEO_SYSTEM = """\
You are a strict QA inspector for AI-generated cartoon animations for toddlers. You receive \
the SOURCE still image first, then frames sampled in order from the generated animation. \
Look for: character distortion, faces changing between frames, extra limbs, objects changing \
or disappearing, unexpected characters, bad camera movement, large artifacts, characters \
leaving the frame, and the animation no longer matching the source image.
overall = "fail" for clear defects, "warn" for doubtful ones, else "pass".
"""


def _apply_review(t: AssetTrack, review: dict, overall: str) -> None:
    t.selected_version.review = review
    if t.status != "approved":
        t.status = "ai_passed" if overall == "pass" else "needs_review"


def _scene_context(ctx: PipelineContext, scene_id: int) -> tuple[dict, list[Path]]:
    scene = ctx.plan().scene(scene_id)
    bibles = load_bibles(ctx, scene.characters)
    refs: list[Path] = []
    for b in bibles:
        refs += reference_images(ctx, b.name, limit=1)
    context = {
        "scene": {
            "action": scene.action,
            "composition": scene.composition,
            "objects": [o.model_dump() for o in scene.objects],
            "characters": scene.characters,
            "environment": scene.environment or ctx.spec.environment.default,
            "motion": scene.motion_prompt,
            "camera": scene.camera,
        },
        "characters": [{"id": b.name, "definition": b.definition()} for b in bibles],
        "style": ctx.spec.style.description,
        "audience_age": f"{ctx.spec.project.target_age_min}-{ctx.spec.project.target_age_max}",
    }
    return context, refs


async def review_image(ctx: PipelineContext, scene_id: int, *, force: bool = False
                       ) -> VisualReview | None:
    state = ctx.scene_state(scene_id)
    v = state.image.selected_version
    if v is None:
        return None
    if v.review and not force:
        return VisualReview.model_validate(v.review)
    report("REVIEWING", f"scene {scene_id} image")
    context, refs = _scene_context(ctx, scene_id)
    image = ctx.paths.scene_dir(scene_id) / v.file
    user = ("Inspect the generated scene image.\n"
            f"<context>\n{json.dumps(context, ensure_ascii=False, indent=2)}\n</context>")
    result = await ctx.llm("image_review", scene_id, vision=True).generate_structured(
        IMAGE_SYSTEM, user, VisualReview, images=[image, *refs],
        max_attempts=ctx.config.llm_max_attempts,
    )
    state = ctx.scene_state(scene_id)
    _apply_review(state.image, result.value.model_dump(), result.value.overall)
    ctx.save_scene_state(state)
    return result.value


async def review_video(ctx: PipelineContext, scene_id: int, *, force: bool = False
                       ) -> VideoReview | None:
    state = ctx.scene_state(scene_id)
    v = state.video.selected_version
    if v is None:
        return None
    if v.review and not force:
        return VideoReview.model_validate(v.review)
    report("REVIEWING", f"scene {scene_id} video")
    d = ctx.paths.scene_dir(scene_id)
    video = d / v.file
    dur = await media_duration(video)
    times = [0.0, dur * 0.33, dur * 0.66, max(dur - 0.1, 0.0)]
    frames = await extract_frames(video, d / "qa_frames" / f"v{v.version}", times)
    context, _ = _scene_context(ctx, scene_id)
    user = ("Inspect the animation frames against the source image.\n"
            f"<context>\n{json.dumps(context, ensure_ascii=False, indent=2)}\n</context>")
    result = await ctx.llm("video_review", scene_id, vision=True).generate_structured(
        VIDEO_SYSTEM, user, VideoReview, images=[d / "selected.png", *frames],
        max_attempts=ctx.config.llm_max_attempts,
    )
    state = ctx.scene_state(scene_id)
    _apply_review(state.video, result.value.model_dump(), result.value.overall)
    ctx.save_scene_state(state)
    return result.value


async def review_scenes(ctx: PipelineContext, track: Track, scene_ids: list[int] | None = None,
                        *, force: bool = False) -> dict[int, str]:
    """Review every selected-but-unreviewed asset. Returns scene -> verdict."""
    ids = scene_ids or [s.id for s in ctx.plan().scenes]
    sem = asyncio.Semaphore(ctx.config.concurrency.reviews)
    fn = review_image if track == "image" else review_video
    out: dict[int, str] = {}

    async def one(sid: int) -> None:
        if track_of(ctx.scene_state(sid), track).selected is None:
            out[sid] = "nothing to review"
            return
        async with sem:
            try:
                r = await fn(ctx, sid, force=force)
                out[sid] = r.overall + (f": {'; '.join(r.problems)}" if r.problems else "")
            except Exception as e:
                out[sid] = f"review failed: {e}"

    await asyncio.gather(*(one(s) for s in ids))
    return dict(sorted(out.items()))
