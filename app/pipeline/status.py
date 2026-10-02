"""Project status summary shared by the CLI and the dashboard."""

from __future__ import annotations

from app.models.state import Gate
from app.pipeline.context import PipelineContext
from app.utils.files import read_json

STATUS_ICONS = {
    "not_generated": "—", "generating": "⟳", "generated": "•", "ai_passed": "✓?",
    "needs_review": "⚠", "approved": "✓", "rejected": "✗", "failed": "✗",
}


def project_status(ctx: PipelineContext) -> dict:
    p = ctx.paths
    gates = {g.value: dict(zip(("approved", "reason"), ctx.gate_status(g), strict=True))
             for g in Gate}
    scenes = []
    images_done = videos_done = 0
    total = 0
    if p.creative_plan.exists():
        plan = ctx.plan()
        storyboard = ctx.storyboard() if p.storyboard.exists() else None
        total = len(plan.scenes)
        for scene in plan.scenes:
            st = ctx.scene_state(scene.id)
            images_done += st.image.status == "approved"
            videos_done += st.video.status == "approved"
            timed = storyboard.scene(scene.id) if storyboard else None
            scenes.append({
                "id": scene.id,
                "lyrics": [plan.line(i).sung for i in scene.lyric_line_ids],
                "start": timed.start if timed else None,
                "end": timed.end if timed else None,
                "image_status": st.image.status,
                "video_status": st.video.status,
                "image_versions": len(st.image.versions),
                "video_versions": len(st.video.versions),
                "image_problems": ((st.image.selected_version.review or {}).get("problems", [])
                                   if st.image.selected_version else []),
                "video_problems": ((st.video.selected_version.review or {}).get("problems", [])
                                   if st.video.selected_version else []),
                "error": st.image.error or st.video.error,
            })

    review = None
    if p.language_review.exists():
        review = read_json(p.language_review).get("review")

    renders = {}
    for preset in ctx.config.render_presets:
        out = p.output_video(preset)
        qc_path = p.render_dir(preset) / "qc.json"
        if out.exists():
            renders[preset] = {
                "file": str(out.relative_to(p.root)),
                "qc": read_json(qc_path) if qc_path.exists() else None,
            }

    return {
        "id": ctx.project_id,
        "title": ctx.spec.project.title,
        "stages": {
            "lyrics": p.creative_plan.exists(),
            "language_review": review,
            "music": p.song.exists(),
            "timing": p.timing.exists(),
            "storyboard": p.storyboard.exists(),
            "images": f"{images_done} / {total}",
            "videos": f"{videos_done} / {total}",
            "thumbnail": (p.thumbnail / "selected.png").exists(),
            "metadata": p.youtube.exists(),
        },
        "gates": gates,
        "scenes": scenes,
        "renders": renders,
        "costs": ctx.tracker.summary(ctx.project_id),
    }
