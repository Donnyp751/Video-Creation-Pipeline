"""Full pipeline with mock providers: project -> plan -> music -> timing -> images -> videos ->
FFmpeg -> final.mp4, exercising every approval gate. Costs nothing; needs ffmpeg."""

import pytest

from app.models.state import Gate
from app.pipeline.build import build
from app.pipeline.context import GateError
from app.services import image_service, music_service, scene_assets
from app.services.qc_service import run_qc
from app.utils.ffmpeg import media_duration

pytestmark = pytest.mark.ffmpeg


async def test_build_stops_at_every_gate_then_completes(ctx):
    seen = []
    for expected in (Gate.lyrics, Gate.storyboard, Gate.images, Gate.videos, Gate.preview):
        result = await build(ctx, echo=lambda _: None)
        assert not result.completed
        assert result.stopped_at == expected
        seen.append(result.stopped_at)
        if expected in (Gate.images, Gate.videos):
            approved, pending = scene_assets.approve_reviewed(
                ctx, "image" if expected == Gate.images else "video")
            assert approved and not pending
        else:
            ctx.approve(expected)

    result = await build(ctx, final_preset="preview", echo=lambda _: None)
    assert result.completed, result.log
    final = ctx.paths.output_video("preview")
    assert final.is_file()
    song = await media_duration(ctx.paths.song)
    assert abs(await media_duration(final) - song) < 0.3
    qc = await run_qc(ctx, "preview")
    assert qc.passed, qc.checks

    # Provenance and versioning artifacts exist.
    p = ctx.paths
    for f in (p.music_request, p.music_response, p.timing, p.storyboard, p.transcript,
              p.subtitles / "vi.srt", p.subtitles / "en.srt", p.subtitles / "bilingual.srt",
              p.render_dir("preview") / "filter_graph.txt", p.scene_dir(1) / "prompt.txt",
              p.scene_dir(1) / "image_v1.png", p.scene_dir(1) / "selected.png",
              p.scene_dir(1) / "animation_v1.mp4", p.scene_dir(1) / "selected_video.mp4",
              p.scene_dir(1) / "metadata.json"):
        assert f.is_file(), f

    # Re-running is idempotent: nothing is regenerated, so no new paid calls.
    calls_before = len(ctx.tracker.calls(ctx.project_id))
    await build(ctx, final_preset="preview", echo=lambda _: None)
    assert len(ctx.tracker.calls(ctx.project_id)) == calls_before


async def test_stages_refuse_to_run_without_approval(ctx):
    from app.services.creative_director import generate_plan

    await generate_plan(ctx)
    with pytest.raises(GateError, match="lyrics"):
        await music_service.generate_music(ctx)


async def test_regeneration_creates_new_versions(ctx):
    await build(ctx, auto_approve=True, final_preset="preview", echo=lambda _: None)
    state, made = await image_service.generate_scene_image(ctx, 1)
    assert not made  # exists -> skipped
    state, made = await image_service.generate_scene_image(ctx, 1, regenerate=True)
    assert made and [v.version for v in state.image.versions] == [1, 2]
    assert state.image.selected == 2 and state.image.status == "generated"
    assert state.video.status == "needs_review"  # animation came from the old image
    # Selecting the old version restores it.
    state = scene_assets.select_version(ctx, 1, "image", 1)
    assert (ctx.paths.scene_dir(1) / "selected.png").read_bytes() == \
        (ctx.paths.scene_dir(1) / "image_v1.png").read_bytes()
    calls = [c for c in ctx.tracker.calls(ctx.project_id) if c.stage == "images"]
    assert any(c.regeneration for c in calls)
