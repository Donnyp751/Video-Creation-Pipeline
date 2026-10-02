"""`kidsvideo build`: run every stage in order, stopping at each human approval gate.

Re-running ``build`` resumes: finished stages are skipped because their artifacts exist.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from app.models.state import Gate
from app.pipeline.context import PipelineContext
from app.services import (
    image_service,
    language_review,
    music_service,
    qc_service,
    render_service,
    timing_service,
    video_service,
    visual_qa,
)
from app.services.creative_director import generate_plan


@dataclass
class BuildResult:
    completed: bool
    stopped_at: Gate | None = None
    message: str = ""
    log: list[str] = field(default_factory=list)


async def build(
    ctx: PipelineContext,
    *,
    auto_approve: bool = False,
    final_preset: str = "youtube",
    echo: Callable[[str], None] = print,
) -> BuildResult:
    """``auto_approve`` approves every gate the AI reviews passed (for tests / mock runs)."""
    log: list[str] = []

    def say(msg: str) -> None:
        log.append(msg)
        echo(msg)

    def gate(g: Gate, hint: str) -> BuildResult | None:
        ok, reason = ctx.gate_status(g)
        if ok:
            return None
        if auto_approve:
            if g in (Gate.images, Gate.videos):
                from app.services.scene_assets import approve_reviewed
                track = "image" if g == Gate.images else "video"
                approve_reviewed(ctx, track)
                ok, reason = ctx.gate_status(g)
            else:
                ctx.approve(g, note="auto-approved by build")
                ok = True
            if ok:
                say(f"  auto-approved {g}")
                return None
        say(f"STOP: waiting for approval of '{g}' ({reason})")
        say(f"  {hint}")
        return BuildResult(False, g, f"waiting for approval: {g}", log)

    pid = ctx.project_id
    say(f"Project {pid}: validated project.yaml")

    say("Creative Director: lyrics + storyboard plan")
    await generate_plan(ctx)
    review = await language_review.review_lyrics(ctx)
    say(f"  language review: {'pass' if review.passed else 'issues found'} "
        f"({len(review.issues)} issue(s))")
    for issue in review.issues:
        say(f"   - line {issue.line} [{issue.severity}] {issue.reason} -> {issue.suggestion}")
    if stop := gate(Gate.lyrics, f"Edit creative_plan.json if needed, then: kidsvideo approve "
                                 f"{pid} lyrics"):
        return stop

    say("Music generation")
    await music_service.generate_music(ctx)
    say("Song timing analysis")
    await timing_service.analyze_timing(ctx)
    storyboard = timing_service.generate_storyboard(ctx)
    for w in timing_service.storyboard_warnings(storyboard):
        say(f"  warning: {w}")
    if stop := gate(Gate.storyboard, f"Check storyboard.json, then: kidsvideo approve {pid} "
                                     "storyboard"):
        return stop

    say("Scene images")
    for sid, outcome in (await image_service.generate_images(ctx)).items():
        say(f"  scene {sid:02d}: {outcome}")
    say("AI image review")
    for sid, verdict in (await visual_qa.review_scenes(ctx, "image")).items():
        say(f"  scene {sid:02d}: {verdict}")
    if stop := gate(Gate.images, f"Review flagged scenes in the dashboard, then: kidsvideo "
                                 f"approve {pid} images [--scene N]"):
        return stop

    say("Scene animations")
    for sid, outcome in (await video_service.generate_videos(ctx)).items():
        say(f"  scene {sid:02d}: {outcome}")
    say("AI video review")
    for sid, verdict in (await visual_qa.review_scenes(ctx, "video")).items():
        say(f"  scene {sid:02d}: {verdict}")
    if stop := gate(Gate.videos, f"Review flagged animations, then: kidsvideo approve {pid} "
                                 "videos [--scene N]"):
        return stop

    say("Render preview")
    preview = await render_service.render(ctx, "preview")
    qc = await qc_service.run_qc(ctx, "preview")
    say(f"  {preview.relative_to(ctx.paths.root)}  QC: {'pass' if qc.passed else 'FAIL'}")
    if stop := gate(Gate.preview, f"Watch the preview, then: kidsvideo approve {pid} preview"):
        return stop

    say(f"Render final ({final_preset})")
    final = await render_service.render(ctx, final_preset)
    qc = await qc_service.run_qc(ctx, final_preset)
    for c in qc.checks:
        say(f"  QC {'✓' if c.passed else '✗'} {c.name}: {c.detail}")
    say(f"Done: {final}")
    return BuildResult(True, None, str(final), log)
