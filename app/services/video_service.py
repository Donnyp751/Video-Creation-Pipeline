"""Image-to-video for approved scene images, versioned like images."""

from __future__ import annotations

import asyncio
import shutil

from app.core.progress import report
from app.models.state import AssetVersion, SceneState
from app.pipeline.context import PipelineContext, PipelineError
from app.services.character_bible import load_bibles
from app.services.prompt_compiler import compile_motion_prompt
from app.services.scene_assets import effective_prompt, selected_file
from app.utils.ffmpeg import media_duration
from app.utils.files import next_version, now_iso


def requested_duration(ctx: PipelineContext, scene_id: int, preset: str = "youtube") -> float:
    """Scene length plus the crossfade overlap the renderer will need."""
    scene = ctx.storyboard().scene(scene_id)
    xfade = ctx.config.render_presets[preset].crossfade if preset in ctx.config.render_presets \
        else 0.0
    return scene.duration + xfade


async def generate_scene_video(ctx: PipelineContext, scene_id: int, *,
                               regenerate: bool = False) -> tuple[SceneState, bool]:
    state = ctx.scene_state(scene_id)
    if state.video.versions and not regenerate:
        return state, False
    if state.image.status != "approved" and not ctx.ignore_gates:
        raise PipelineError(f"scene {scene_id}: image is not approved (status "
                            f"{state.image.status})")

    scene = ctx.plan().scene(scene_id)
    prompt = effective_prompt(ctx, scene_id, "video",
                              compile_motion_prompt(scene, load_bibles(ctx, scene.characters)))
    d = ctx.paths.scene_dir(scene_id)
    image = selected_file(ctx, scene_id, "image")
    n, out = next_version(d, "animation", ".mp4")
    duration = requested_duration(ctx, scene_id)

    state.video.status = "generating"
    state.video.error = None
    ctx.save_scene_state(state)
    report("GENERATING", f"scene {scene_id} animation v{n}")
    provider = ctx.video(scene_id, regeneration=n > 1)
    try:
        result = await provider.image_to_video(image, prompt, duration,
                                               ctx.spec.project.aspect_ratio, out, variant=n)
    except Exception as e:
        out.unlink(missing_ok=True)  # don't let a partial file occupy the version number
        state = ctx.scene_state(scene_id)
        state.video.status = "failed"
        state.video.error = str(e)[:1000]
        ctx.save_scene_state(state)
        raise

    state = ctx.scene_state(scene_id)
    state.video.versions.append(AssetVersion(
        version=n, file=out.name, prompt=prompt, created_at=now_iso(), provider=provider.name,
        model=result.model, cache_hit=result.cache_hit, duration=await media_duration(out),
    ))
    state.video.selected = n
    state.video.status = "generated"
    state.video.approved_at = None
    shutil.copy2(out, selected_file(ctx, scene_id, "video"))
    ctx.save_scene_state(state)
    return state, True


async def generate_videos(ctx: PipelineContext, scene_ids: list[int] | None = None, *,
                          regenerate: bool = False) -> dict[int, str]:
    ids = scene_ids or [s.id for s in ctx.plan().scenes]
    sem = asyncio.Semaphore(ctx.config.concurrency.videos)
    outcomes: dict[int, str] = {}

    async def one(sid: int) -> None:
        async with sem:
            try:
                _, made = await generate_scene_video(ctx, sid, regenerate=regenerate)
                outcomes[sid] = "generated" if made else "skipped (exists)"
            except Exception as e:
                outcomes[sid] = f"skipped: {e}" if isinstance(e, PipelineError) else \
                    f"failed: {e}"

    await asyncio.gather(*(one(s) for s in ids))
    return dict(sorted(outcomes.items()))
