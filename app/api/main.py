"""FastAPI backend for the review dashboard. Long-running work is submitted as jobs."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from app.core.config import Workspace
from app.core.db import get_database
from app.models.state import Gate
from app.pipeline.context import MissingArtifact, PipelineContext, PipelineError
from app.pipeline.jobs import JobRunner
from app.pipeline.status import project_status
from app.utils.files import read_json, safe_join

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    ws = Workspace.discover()
    app.state.ws = ws
    app.state.jobs = JobRunner(get_database(ws.db_path))
    app.state.jobs.mark_interrupted()
    yield


app = FastAPI(title="Kids Video AI", lifespan=lifespan)


def ws() -> Workspace:
    return app.state.ws


def jobs() -> JobRunner:
    return app.state.jobs


def ctx_for(project_id: str) -> PipelineContext:
    try:
        return PipelineContext(ws(), project_id)
    except MissingArtifact as e:
        raise HTTPException(404, str(e)) from None
    except (PipelineError, ValidationError) as e:
        raise HTTPException(422, str(e)) from None


def _guard(fn):
    try:
        return fn()
    except MissingArtifact as e:
        raise HTTPException(404, str(e)) from None
    except (PipelineError, ValueError, KeyError) as e:
        raise HTTPException(409, str(e)) from None


# --- projects --------------------------------------------------------------------------------
class NewProject(BaseModel):
    id: str
    title: str | None = None
    topic: str | None = None
    learning_goal: str | None = None
    duration: int | None = None


@app.get("/api/projects")
def list_projects() -> list[dict]:
    out = []
    root = ws().projects_dir
    for d in sorted(root.iterdir()) if root.is_dir() else []:
        if (d / "project.yaml").is_file():
            try:
                spec = PipelineContext(ws(), d.name).spec
                out.append({"id": d.name, "title": spec.project.title})
            except Exception as e:  # show broken projects instead of hiding them
                out.append({"id": d.name, "title": d.name, "error": str(e)[:300]})
    return out


@app.post("/api/projects")
def create(body: NewProject) -> dict:
    from app.pipeline.project_factory import create_project

    try:
        spec = create_project(ws(), body.id, title=body.title, topic=body.topic,
                              learning_goal=body.learning_goal, duration=body.duration)
    except (ValueError, FileExistsError) as e:
        raise HTTPException(409, str(e)) from None
    return {"id": spec.project.id}


@app.get("/api/projects/{pid}")
def get_project(pid: str) -> dict:
    ctx = ctx_for(pid)
    status = project_status(ctx)
    status["spec"] = ctx.spec.model_dump(mode="json")
    return status


@app.get("/api/projects/{pid}/plan")
def get_plan(pid: str) -> dict:
    ctx = ctx_for(pid)
    plan = _guard(ctx.plan)
    review = None
    if ctx.paths.language_review.exists():
        review = read_json(ctx.paths.language_review).get("review")
    return {"plan": plan.model_dump(), "review": review}


@app.put("/api/projects/{pid}/plan")
def put_plan(pid: str, plan: dict[str, Any] = Body(...)) -> dict:
    from app.services.creative_director import update_plan

    ctx = ctx_for(pid)
    try:
        update_plan(ctx, plan)
    except ValidationError as e:
        raise HTTPException(422, str(e)) from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {"ok": True}


@app.post("/api/projects/{pid}/approve/{gate}")
def approve_gate(pid: str, gate: Gate, scene: int | None = None,
                 include_flagged: bool = False) -> dict:
    from app.services import scene_assets

    ctx = ctx_for(pid)
    if gate in (Gate.images, Gate.videos):
        track = "image" if gate == Gate.images else "video"
        if scene is not None:
            _guard(lambda: scene_assets.approve(ctx, scene, track))
            return {"approved": [scene], "pending": []}
        approved, pending = _guard(lambda: scene_assets.approve_reviewed(
            ctx, track, include_flagged=include_flagged))
        return {"approved": approved, "pending": pending}
    _guard(lambda: ctx.approve(gate))
    return {"approved": gate}


# --- stages (as jobs) ------------------------------------------------------------------------
def _stage_coro(ctx: PipelineContext, stage: str, scene: int | None, force: bool):
    from app.services import (
        image_service,
        language_review,
        metadata_service,
        music_service,
        qc_service,
        render_service,
        thumbnail_service,
        timing_service,
        video_service,
        visual_qa,
    )
    from app.services.creative_director import generate_plan

    scenes = [scene] if scene else None

    async def lyrics():
        await generate_plan(ctx, force=force)
        return await language_review.review_lyrics(ctx, force=force)

    async def timing():
        await timing_service.analyze_timing(ctx, force=force)
        return timing_service.generate_storyboard(ctx)

    async def render(preset: str):
        out = await render_service.render(ctx, preset)
        await qc_service.run_qc(ctx, preset)
        return out

    table = {
        "lyrics": lyrics,
        "language_review": lambda: language_review.review_lyrics(ctx, force=True),
        "music": lambda: music_service.generate_music(ctx, force=force),
        "timing": timing,
        "images": lambda: image_service.generate_images(ctx, scenes, regenerate=force),
        "image_review": lambda: visual_qa.review_scenes(ctx, "image", scenes, force=force),
        "videos": lambda: video_service.generate_videos(ctx, scenes, regenerate=force),
        "video_review": lambda: visual_qa.review_scenes(ctx, "video", scenes, force=force),
        "render_preview": lambda: render("preview"),
        "render_youtube": lambda: render("youtube"),
        "render_shorts": lambda: render("youtube_shorts"),
        "thumbnail": lambda: thumbnail_service.generate_candidates(ctx),
        "metadata": lambda: metadata_service.generate_metadata(ctx, force=force),
    }
    if stage not in table:
        raise HTTPException(404, f"unknown stage '{stage}' (have: {', '.join(table)})")
    return table[stage]


@app.post("/api/projects/{pid}/stages/{stage}")
async def run_stage(pid: str, stage: str, scene: int | None = None, force: bool = False) -> dict:
    ctx = ctx_for(pid)
    fn = _stage_coro(ctx, stage, scene, force)
    job_id = jobs().submit(pid, stage, fn, scene_id=scene)
    return {"job_id": job_id}


@app.get("/api/jobs")
def list_jobs(project: str | None = None) -> list[dict]:
    return [
        {"id": j.id, "project_id": j.project_id, "kind": j.kind, "scene_id": j.scene_id,
         "status": j.status, "message": j.message, "error": j.error,
         "created_at": j.created_at.isoformat(), "updated_at": j.updated_at.isoformat()}
        for j in jobs().list(project)
    ]


# --- scenes ----------------------------------------------------------------------------------
@app.get("/api/projects/{pid}/scenes/{sid}")
def get_scene(pid: str, sid: int) -> dict:
    from app.services.scene_assets import OVERRIDE, PROMPT

    ctx = ctx_for(pid)
    plan_scene = _guard(lambda: ctx.plan().scene(sid))
    d = ctx.paths.scene_dir(sid)

    def text(name: str) -> str | None:
        p = d / name
        return p.read_text("utf-8") if p.is_file() else None

    timed = None
    if ctx.paths.storyboard.exists():
        s = ctx.storyboard().scene(sid)
        timed = {"start": s.start, "end": s.end}
    return {
        "scene": plan_scene.model_dump(),
        "lyrics": [ctx.plan().line(i).model_dump() for i in plan_scene.lyric_line_ids],
        "timing": timed,
        "state": ctx.scene_state(sid).model_dump(),
        "prompts": {
            track: {"compiled": text(PROMPT[track]), "override": text(OVERRIDE[track])}
            for track in ("image", "video")
        },
    }


class PromptBody(BaseModel):
    text: str | None = None


@app.put("/api/projects/{pid}/scenes/{sid}/{track}/prompt")
def put_prompt(pid: str, sid: int, track: str, body: PromptBody) -> dict:
    from app.services.scene_assets import set_prompt_override

    if track not in ("image", "video"):
        raise HTTPException(404, "track must be image or video")
    set_prompt_override(ctx_for(pid), sid, track, body.text)  # type: ignore[arg-type]
    return {"ok": True}


@app.post("/api/projects/{pid}/scenes/{sid}/{track}/{action}")
def scene_action(pid: str, sid: int, track: str, action: str, version: int | None = None
                 ) -> dict:
    from app.services import scene_assets

    if track not in ("image", "video"):
        raise HTTPException(404, "track must be image or video")
    ctx = ctx_for(pid)
    match action:
        case "approve":
            state = _guard(lambda: scene_assets.approve(ctx, sid, track))
        case "reject":
            state = _guard(lambda: scene_assets.reject(ctx, sid, track))
        case "select":
            if version is None:
                raise HTTPException(422, "version is required")
            state = _guard(lambda: scene_assets.select_version(ctx, sid, track, version))
        case _:
            raise HTTPException(404, f"unknown action '{action}'")
    return state.model_dump()


@app.post("/api/projects/{pid}/thumbnail/select")
def thumbnail_select(pid: str, version: int, title: str | None = None) -> dict:
    from app.services.thumbnail_service import select_candidate

    ctx = ctx_for(pid)
    out = _guard(lambda: select_candidate(ctx, version, title=title))
    return {"file": str(out.relative_to(ctx.paths.root))}


@app.get("/api/projects/{pid}/thumbnail")
def thumbnail_list(pid: str) -> dict:
    from app.utils.files import list_versions

    ctx = ctx_for(pid)
    d = ctx.paths.thumbnail
    return {
        "candidates": [n for n, _ in list_versions(d, "candidate", ".png")],
        "selected": (d / "selected.png").is_file(),
    }


# --- files -----------------------------------------------------------------------------------
@app.get("/files/{pid}/{path:path}")
def project_file(pid: str, path: str) -> FileResponse:
    root = ws().projects_dir / pid
    try:
        target = safe_join(root, path)
    except ValueError:
        raise HTTPException(403, "forbidden") from None
    if not target.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(target, headers={"Cache-Control": "no-cache"})


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


if FRONTEND.is_dir():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
