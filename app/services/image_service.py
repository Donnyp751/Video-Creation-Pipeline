"""Batch scene image generation with versioning. Completed work is never regenerated implicitly."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from app.core.progress import report
from app.models.creative import ScenePlan
from app.models.state import AssetVersion, Gate, SceneState
from app.pipeline.context import PipelineContext
from app.services.character_bible import environment_reference, load_bibles, reference_images
from app.services.prompt_compiler import compile_image_prompt
from app.services.scene_assets import effective_prompt, selected_file
from app.utils.files import next_version, now_iso

MAX_REFERENCES = 6


def scene_references(ctx: PipelineContext, scene: ScenePlan) -> list[Path]:
    refs: list[Path] = []
    for cid in scene.characters:
        refs += reference_images(ctx, cid, limit=1)
    refs += environment_reference(ctx)
    return refs[:MAX_REFERENCES]


def compiled_image_prompt(ctx: PipelineContext, scene: ScenePlan) -> str:
    return compile_image_prompt(ctx.spec, scene, load_bibles(ctx, scene.characters))


async def generate_scene_image(ctx: PipelineContext, scene_id: int, *,
                               regenerate: bool = False) -> tuple[SceneState, bool]:
    """Returns (state, generated). Skips scenes that already have an image unless regenerating."""
    state = ctx.scene_state(scene_id)
    if state.image.versions and not regenerate:
        return state, False

    scene = ctx.plan().scene(scene_id)
    prompt = effective_prompt(ctx, scene_id, "image", compiled_image_prompt(ctx, scene))
    refs = scene_references(ctx, scene)
    d = ctx.paths.scene_dir(scene_id)
    n, out = next_version(d, "image", ".png")

    state.image.status = "generating"
    state.image.error = None
    ctx.save_scene_state(state)
    report("GENERATING", f"scene {scene_id} image v{n}")
    provider = ctx.image("images", scene_id, regeneration=n > 1)
    try:
        result = await provider.generate(prompt, refs, ctx.spec.project.aspect_ratio, out,
                                         variant=n)
    except Exception as e:
        out.unlink(missing_ok=True)  # don't let a partial file occupy the version number
        state = ctx.scene_state(scene_id)
        state.image.status = "failed"
        state.image.error = str(e)[:1000]
        ctx.save_scene_state(state)
        raise

    state = ctx.scene_state(scene_id)
    state.image.versions.append(AssetVersion(
        version=n, file=out.name, prompt=prompt, created_at=now_iso(), provider=provider.name,
        model=result.model, cache_hit=result.cache_hit,
    ))
    state.image.selected = n
    state.image.status = "generated"
    state.image.approved_at = None
    shutil.copy2(out, selected_file(ctx, scene_id, "image"))
    if state.video.versions:
        state.video.status = "needs_review"
        state.video.error = f"source image changed to v{n}; consider regenerating"
    ctx.save_scene_state(state)
    return state, True


async def generate_images(ctx: PipelineContext, scene_ids: list[int] | None = None, *,
                          regenerate: bool = False) -> dict[int, str]:
    """Generate missing images (or regenerate the given scenes). Returns scene -> outcome."""
    ctx.require_gate(Gate.storyboard)
    ids = scene_ids or [s.id for s in ctx.plan().scenes]
    sem = asyncio.Semaphore(ctx.config.concurrency.images)
    outcomes: dict[int, str] = {}

    async def one(sid: int) -> None:
        async with sem:
            try:
                _, made = await generate_scene_image(ctx, sid, regenerate=regenerate)
                outcomes[sid] = "generated" if made else "skipped (exists)"
            except Exception as e:  # keep going; failures are visible in the dashboard
                outcomes[sid] = f"failed: {e}"

    await asyncio.gather(*(one(s) for s in ids))
    return dict(sorted(outcomes.items()))
