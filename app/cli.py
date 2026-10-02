"""`kidsvideo` command line. Every pipeline stage is callable on its own."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Annotated

import typer

from app.core.config import Workspace
from app.models.state import Gate
from app.pipeline.context import PipelineContext, PipelineError
from app.providers.common import ProviderError

app = typer.Typer(no_args_is_help=True, add_completion=False,
                  help="AI pipeline for bilingual kids' music videos.")


@dataclass
class Options:
    mock: bool | None = None
    use_cache: bool = True
    ignore_gates: bool = False


opts = Options()


@app.callback()
def main_options(
    mock: Annotated[bool, typer.Option("--mock", help="Use offline mock providers")] = False,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Bypass the request cache")] = False,
    ignore_gates: Annotated[bool, typer.Option("--ignore-gates",
                                               help="Run stages without approvals")] = False,
) -> None:
    opts.mock = True if mock else None
    opts.use_cache = not no_cache
    opts.ignore_gates = ignore_gates


def workspace() -> Workspace:
    return Workspace.discover(mock=opts.mock)


def context(project: str) -> PipelineContext:
    from pydantic import ValidationError

    try:
        ctx = PipelineContext(workspace(), project, use_cache=opts.use_cache)
    except ValidationError as e:
        typer.secho(f"project.yaml is invalid:\n{e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from None
    except PipelineError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from None
    ctx.ignore_gates = opts.ignore_gates
    return ctx


def run(coro):
    try:
        return asyncio.run(coro)
    except (PipelineError, ProviderError) as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from None


def guarded(fn):
    try:
        return fn()
    except (PipelineError, ProviderError, ValueError, FileExistsError) as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from None


def show_outcomes(outcomes: dict[int, str]) -> None:
    for sid, outcome in outcomes.items():
        color = typer.colors.RED if outcome.startswith(("failed", "fail", "review failed")) \
            else None
        typer.secho(f"  scene {sid:02d}: {outcome}", fg=color)


ProjectArg = Annotated[str, typer.Argument(help="Project id (directory under projects/)")]
SceneOpt = Annotated[int | None, typer.Option("--scene", "-s", help="Only this scene")]


# --- project ---------------------------------------------------------------------------------
@app.command()
def new(
    project: ProjectArg,
    title: Annotated[str | None, typer.Option()] = None,
    topic: Annotated[str | None, typer.Option()] = None,
    goal: Annotated[str | None, typer.Option(help="Learning goal")] = None,
    duration: Annotated[int | None, typer.Option(help="Target seconds")] = None,
) -> None:
    """Create projects/<id>/project.yaml from the template."""
    from app.pipeline.project_factory import create_project

    ws = workspace()
    guarded(lambda: create_project(ws, project, title=title, topic=topic, learning_goal=goal,
                                   duration=duration))
    typer.echo(f"Created {ws.projects_dir / project / 'project.yaml'} — edit it, then run "
               f"`kidsvideo lyrics {project}`")


@app.command()
def validate(project: ProjectArg) -> None:
    """Load and validate project.yaml."""
    s = context(project).spec
    typer.echo(f"OK: {s.project.id} '{s.project.title}' {s.languages.primary}/"
               f"{s.languages.secondary}, {len(s.characters)} characters, "
               f"{s.creative.duration_target_seconds}s target")


# --- creative --------------------------------------------------------------------------------
@app.command()
def lyrics(project: ProjectArg,
           regenerate: Annotated[bool, typer.Option(help="Write a new plan")] = False) -> None:
    """Creative Director (lyrics + scene plan) followed by bilingual language review."""
    from app.services.creative_director import generate_plan
    from app.services.language_review import review_lyrics

    ctx = context(project)

    async def go():
        plan = await generate_plan(ctx, force=regenerate)
        review = await review_lyrics(ctx, force=regenerate)
        return plan, review

    plan, review = run(go())
    typer.echo(f"{plan.title} / {plan.title_secondary}")
    for line in plan.lyrics:
        typer.echo(f"  {line.id:2d} [{line.section}] {line.sung}")
        typer.echo(f"       {line.primary}  |  {line.secondary}")
    typer.echo(f"{len(plan.scenes)} scenes. Language review: "
               + ("PASS" if review.passed else "ISSUES"))
    for i in review.issues:
        typer.secho(f"  line {i.line} [{i.severity}/{i.category}] {i.reason}\n"
                    f"     suggestion: {i.suggestion}", fg=typer.colors.YELLOW)
    typer.echo(f"Edit {ctx.paths.creative_plan} if needed, then: kidsvideo approve {project} "
               "lyrics")


@app.command()
def approve(
    project: ProjectArg,
    gate: Annotated[Gate, typer.Argument(help="lyrics|storyboard|images|videos|preview")],
    scene: SceneOpt = None,
    all_scenes: Annotated[bool, typer.Option("--all", help="Also approve AI-flagged scenes")]
    = False,
    note: Annotated[str, typer.Option()] = "",
) -> None:
    """Approve a gate (or one scene's image/video)."""
    from app.services import scene_assets

    ctx = context(project)
    if gate in (Gate.images, Gate.videos):
        track = "image" if gate == Gate.images else "video"
        if scene is not None:
            guarded(lambda: scene_assets.approve(ctx, scene, track))
            typer.echo(f"Approved scene {scene} {track}")
            return
        approved, pending = scene_assets.approve_reviewed(ctx, track, include_flagged=all_scenes)
        typer.echo(f"Approved scenes: {approved or 'none'}")
        if pending:
            typer.secho(f"Still need attention: {pending} (approve individually with --scene, "
                        "or use --all)", fg=typer.colors.YELLOW)
        return
    guarded(lambda: ctx.approve(gate, note))
    typer.echo(f"Approved {gate}")


# --- audio -----------------------------------------------------------------------------------
@app.command()
def music(project: ProjectArg,
          regenerate: Annotated[bool, typer.Option(help="Make a new version")] = False) -> None:
    """Generate the song (audio/song.wav)."""
    from app.services.music_service import generate_music

    ctx = context(project)
    path = run(generate_music(ctx, force=regenerate))
    typer.echo(f"Song: {path}")


@app.command()
def timing(project: ProjectArg,
           redo: Annotated[bool, typer.Option(help="Re-analyse")] = False) -> None:
    """Align lyrics to the song (timing.json)."""
    from app.services.timing_service import analyze_timing

    ctx = context(project)
    t = run(analyze_timing(ctx, force=redo))
    for line in t.lines:
        typer.echo(f"  {line.start:7.2f} - {line.end:7.2f}  [{line.source} "
                   f"{line.confidence:.0%}] {line.text}")


@app.command()
def storyboard(project: ProjectArg) -> None:
    """Combine plan + timing into storyboard.json (scene start/end)."""
    from app.services.timing_service import generate_storyboard, storyboard_warnings

    ctx = context(project)
    sb = guarded(lambda: generate_storyboard(ctx))
    for s in sb.scenes:
        typer.echo(f"  scene {s.id:02d} {s.start:7.2f}-{s.end:7.2f} ({s.duration:5.2f}s) "
                   f"{s.action[:60]}")
    for w in storyboard_warnings(sb):
        typer.secho(f"  warning: {w}", fg=typer.colors.YELLOW)
    typer.echo(f"Then: kidsvideo approve {project} storyboard")


# --- characters --------------------------------------------------------------------------------
@app.command()
def bible(project: ProjectArg,
          generate: Annotated[bool, typer.Option(help="Generate reference sheets")] = False
          ) -> None:
    """Create Character Bible skeletons (and optionally reference sheets)."""
    from app.services.character_bible import generate_reference_sheets, init_bible

    ctx = context(project)
    for p in init_bible(ctx):
        typer.echo(f"Created {p} — fill in physical/clothing/never_change")
    if generate:
        for p in run(generate_reference_sheets(ctx)):
            typer.echo(f"Generated {p}")


# --- images & videos -------------------------------------------------------------------------
@app.command()
def images(project: ProjectArg,
           regenerate: Annotated[bool, typer.Option(help="New version for every scene")] = False
           ) -> None:
    """Generate missing scene images (existing ones are skipped)."""
    from app.services.image_service import generate_images

    show_outcomes(run(generate_images(context(project), regenerate=regenerate)))


@app.command()
def image(project: ProjectArg, scene: Annotated[int, typer.Option("--scene", "-s")]) -> None:
    """Generate a new image version for one scene."""
    from app.services.image_service import generate_images

    show_outcomes(run(generate_images(context(project), [scene], regenerate=True)))


@app.command()
def videos(project: ProjectArg,
           regenerate: Annotated[bool, typer.Option()] = False) -> None:
    """Animate every scene whose image is approved (existing animations are skipped)."""
    from app.services.video_service import generate_videos

    show_outcomes(run(generate_videos(context(project), regenerate=regenerate)))


@app.command()
def video(project: ProjectArg, scene: Annotated[int, typer.Option("--scene", "-s")]) -> None:
    """Generate a new animation version for one scene."""
    from app.services.video_service import generate_videos

    show_outcomes(run(generate_videos(context(project), [scene], regenerate=True)))


@app.command()
def review(
    project: ProjectArg,
    what: Annotated[str, typer.Argument(help="images|videos")] = "images",
    scene: SceneOpt = None,
    force: Annotated[bool, typer.Option(help="Re-review")] = False,
) -> None:
    """AI visual QA of selected images or animations."""
    from app.services.visual_qa import review_scenes

    track = "video" if what.startswith("video") else "image"
    show_outcomes(run(review_scenes(context(project), track, [scene] if scene else None,
                                    force=force)))


@app.command()
def select(
    project: ProjectArg,
    scene: Annotated[int, typer.Option("--scene", "-s")],
    image_version: Annotated[int | None, typer.Option("--image")] = None,
    video_version: Annotated[int | None, typer.Option("--video")] = None,
) -> None:
    """Select which version of a scene's image/video to use."""
    from app.services.scene_assets import select_version

    ctx = context(project)
    if image_version:
        guarded(lambda: select_version(ctx, scene, "image", image_version))
        typer.echo(f"scene {scene}: image v{image_version} selected")
    if video_version:
        guarded(lambda: select_version(ctx, scene, "video", video_version))
        typer.echo(f"scene {scene}: video v{video_version} selected")


# --- output ----------------------------------------------------------------------------------
@app.command()
def render(project: ProjectArg,
           preset: Annotated[str, typer.Option(help="youtube|youtube_shorts|preview")]
           = "preview") -> None:
    """Render with FFmpeg, then run automated QC."""
    from app.services.qc_service import run_qc
    from app.services.render_service import render as do_render

    ctx = context(project)

    async def go():
        out = await do_render(ctx, preset)
        return out, await run_qc(ctx, preset)

    out, qc = run(go())
    typer.echo(f"Rendered {out}")
    for c in qc.checks:
        typer.secho(f"  QC {'✓' if c.passed else '✗'} {c.name}: {c.detail}",
                    fg=None if c.passed else typer.colors.RED)


@app.command()
def subtitles(project: ProjectArg) -> None:
    """Write subtitles/<lang>.srt and bilingual.srt."""
    from app.services.subtitles import write_subtitles

    for name, path in guarded(lambda: write_subtitles(context(project))).items():
        typer.echo(f"  {name}: {path}")


@app.command()
def thumbnail(
    project: ProjectArg,
    pick: Annotated[int | None, typer.Option(help="Select candidate N and add the title")] = None,
    title: Annotated[str | None, typer.Option(help="Override title text")] = None,
) -> None:
    """Generate thumbnail candidates, or --pick one to add typography."""
    from app.services.thumbnail_service import generate_candidates, select_candidate

    ctx = context(project)
    if pick is not None:
        typer.echo(f"Thumbnail: {guarded(lambda: select_candidate(ctx, pick, title=title))}")
        return
    for p in run(generate_candidates(ctx)):
        typer.echo(f"  candidate: {p}")
    typer.echo(f"Pick one: kidsvideo thumbnail {project} --pick N")


@app.command()
def metadata(project: ProjectArg,
             regenerate: Annotated[bool, typer.Option()] = False) -> None:
    """Generate youtube.json."""
    from app.services.metadata_service import generate_metadata

    meta = run(generate_metadata(context(project), force=regenerate))
    typer.echo(json.dumps(meta.model_dump(), ensure_ascii=False, indent=2))


# --- overview --------------------------------------------------------------------------------
@app.command()
def status(project: ProjectArg) -> None:
    """Show stage, approval, scene and cost status."""
    from app.pipeline.status import STATUS_ICONS, project_status

    st = project_status(context(project))
    typer.secho(st["title"].upper(), bold=True)
    stages = st["stages"]
    rows = [("Lyrics", stages["lyrics"]), ("Music", stages["music"]),
            ("Timing", stages["timing"]), ("Storyboard", stages["storyboard"]),
            ("Images", stages["images"]), ("Videos", stages["videos"]),
            ("Thumbnail", stages["thumbnail"]), ("Metadata", stages["metadata"])]
    for name, val in rows:
        shown = val if isinstance(val, str) else ("✓" if val else "—")
        typer.echo(f"  {name:<12} {shown}")
    typer.echo("Approvals")
    for g, info in st["gates"].items():
        typer.echo(f"  {g:<12} {'✓' if info['approved'] else '—'}  {info['reason']}")
    if st["scenes"]:
        typer.echo("Scenes            image   video")
        for s in st["scenes"]:
            typer.echo(f"  {s['id']:02d}  {s['lyrics'][0][:24]:<24} "
                       f"{STATUS_ICONS[s['image_status']]:<3} {s['image_status']:<13} "
                       f"{STATUS_ICONS[s['video_status']]:<3} {s['video_status']}")
            for prob in s["image_problems"] + s["video_problems"]:
                typer.secho(f"        ⚠ {prob}", fg=typer.colors.YELLOW)
    for preset, r in st["renders"].items():
        qc = r["qc"]
        typer.echo(f"Render {preset}: {r['file']}  QC "
                   f"{'—' if not qc else ('pass' if qc['passed'] else 'FAIL')}")
    _print_costs(st["costs"])


def _print_costs(costs: dict) -> None:
    typer.echo("Costs (estimated)")
    for row in costs["rows"]:
        typer.echo(f"  {row['label']:<16} ${row['cost']:>8.2f}  ({row['calls']} calls)")
    typer.echo(f"  {'TOTAL':<16} ${costs['total']:>8.2f}  ({costs['cache_hits']} cache hits)")


@app.command()
def costs(project: ProjectArg) -> None:
    """Show estimated spend per stage."""
    ctx = context(project)
    _print_costs(ctx.tracker.summary(ctx.project_id))


@app.command()
def build(
    project: ProjectArg,
    auto_approve: Annotated[bool, typer.Option(help="Approve gates the AI passed (testing)")]
    = False,
    preset: Annotated[str, typer.Option(help="Final render preset")] = "youtube",
) -> None:
    """Run the whole pipeline, stopping at every approval gate. Re-run to resume."""
    from app.pipeline.build import build as do_build

    result = run(do_build(context(project), auto_approve=auto_approve, final_preset=preset,
                          echo=typer.echo))
    if not result.completed:
        raise typer.Exit(2)


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Start the web dashboard."""
    import os

    import uvicorn

    ws = workspace()
    os.environ["KIDSVIDEO_HOME"] = str(ws.root)
    if opts.mock:
        os.environ["KIDSVIDEO_MOCK_PROVIDERS"] = "1"
    uvicorn.run("app.api.main:app", host=host, port=port)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
