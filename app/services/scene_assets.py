"""Versioned per-scene assets (images and animations) and the human actions on them.

    scenes/004/
        prompt.txt            compiled image prompt     prompt_override.txt   human edit (optional)
        image_v1.png ...      every generation, never overwritten
        selected.png          copy of the selected version
        animation_prompt.txt  animation_prompt_override.txt
        animation_v1.mp4 ...  selected_video.mp4
        metadata.json         SceneState: versions, selection, reviews, status
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Literal

from app.models.state import AssetTrack, SceneState
from app.pipeline.context import PipelineContext, PipelineError
from app.utils.files import now_iso, write_text

Track = Literal["image", "video"]

SELECTED = {"image": "selected.png", "video": "selected_video.mp4"}
PROMPT = {"image": "prompt.txt", "video": "animation_prompt.txt"}
OVERRIDE = {"image": "prompt_override.txt", "video": "animation_prompt_override.txt"}


def track_of(state: SceneState, track: Track) -> AssetTrack:
    return state.image if track == "image" else state.video


def selected_file(ctx: PipelineContext, scene_id: int, track: Track) -> Path:
    return ctx.paths.scene_dir(scene_id) / SELECTED[track]


def effective_prompt(ctx: PipelineContext, scene_id: int, track: Track, compiled: str) -> str:
    """Write the compiled prompt; a human override (if present) takes precedence."""
    d = ctx.paths.scene_dir(scene_id)
    write_text(d / PROMPT[track], compiled)
    override = d / OVERRIDE[track]
    if override.is_file() and override.read_text(encoding="utf-8").strip():
        return override.read_text(encoding="utf-8")
    return compiled


def set_prompt_override(ctx: PipelineContext, scene_id: int, track: Track,
                        text: str | None) -> None:
    path = ctx.paths.scene_dir(scene_id) / OVERRIDE[track]
    if text and text.strip():
        write_text(path, text)
    else:
        path.unlink(missing_ok=True)


def select_version(ctx: PipelineContext, scene_id: int, track: Track, version: int) -> SceneState:
    state = ctx.scene_state(scene_id)
    t = track_of(state, track)
    v = t.version(version)
    src = ctx.paths.scene_dir(scene_id) / v.file
    shutil.copy2(src, selected_file(ctx, scene_id, track))
    changed = t.selected != version
    t.selected = version
    if changed or t.status in ("rejected", "failed"):
        overall = (v.review or {}).get("overall")
        t.status = {"pass": "ai_passed", None: "generated"}.get(overall, "needs_review")
        t.approved_at = None
    if track == "image" and changed and state.video.versions:
        # Existing animations were made from a different image.
        state.video.status = "needs_review"
        state.video.error = f"source image changed to v{version}; consider regenerating"
    ctx.save_scene_state(state)
    return state


def approve(ctx: PipelineContext, scene_id: int, track: Track) -> SceneState:
    state = ctx.scene_state(scene_id)
    t = track_of(state, track)
    if t.selected is None:
        raise PipelineError(f"scene {scene_id} has no {track} to approve")
    t.status = "approved"
    t.approved_at = now_iso()
    t.error = None
    ctx.save_scene_state(state)
    return state


def reject(ctx: PipelineContext, scene_id: int, track: Track) -> SceneState:
    state = ctx.scene_state(scene_id)
    track_of(state, track).status = "rejected"
    track_of(state, track).approved_at = None
    ctx.save_scene_state(state)
    return state


def approve_reviewed(ctx: PipelineContext, track: Track, *, include_flagged: bool = False
                     ) -> tuple[list[int], list[int]]:
    """Approve every scene the AI passed (or all generated ones with ``include_flagged``).

    Returns (approved_now, still_needing_attention).
    """
    ok_status = {"ai_passed"} | ({"generated", "needs_review"} if include_flagged else set())
    approved, pending = [], []
    for scene in ctx.plan().scenes:
        t = track_of(ctx.scene_state(scene.id), track)
        if t.status == "approved":
            continue
        if t.status in ok_status and t.selected is not None:
            approve(ctx, scene.id, track)
            approved.append(scene.id)
        else:
            pending.append(scene.id)
    return approved, pending
