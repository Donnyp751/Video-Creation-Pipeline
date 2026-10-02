"""PipelineContext: everything a stage needs for one project (spec, paths, providers, state)."""

from __future__ import annotations

from pathlib import Path

from app.core.config import Workspace
from app.core.db import get_database
from app.core.paths import ProjectPaths
from app.models.creative import CreativePlan
from app.models.project import ProjectSpec
from app.models.state import Approval, Gate, ProjectState, SceneState
from app.models.timing import SongTiming, Storyboard
from app.providers import registry
from app.providers.tracked import (
    TrackedImage,
    TrackedLLM,
    TrackedMusic,
    TrackedSpeech,
    TrackedVideo,
)
from app.services.cache import ProviderCache
from app.services.cost_tracker import CallScope, CostTracker
from app.utils.files import now_iso, read_json, sha256_file, write_json


class PipelineError(RuntimeError):
    pass


class GateError(PipelineError):
    """A stage was asked to run before the human approval it depends on."""

    def __init__(self, gate: Gate, project_id: str, detail: str = ""):
        self.gate = gate
        msg = f"'{gate}' is not approved"
        if detail:
            msg += f" ({detail})"
        msg += f". Review it, then run: kidsvideo approve {project_id} {gate}"
        super().__init__(msg)


class MissingArtifact(PipelineError):
    pass


class PipelineContext:
    def __init__(self, workspace: Workspace, project_id: str, *, use_cache: bool = True):
        self.ws = workspace
        self.paths = ProjectPaths(workspace.projects_dir / project_id)
        if not self.paths.spec.is_file():
            raise MissingArtifact(f"no project at {self.paths.spec}")
        self.spec = ProjectSpec.load(self.paths.spec)
        if self.spec.project.id != project_id:
            raise PipelineError(
                f"project.yaml id '{self.spec.project.id}' does not match directory '{project_id}'"
            )
        self.config = workspace.config
        self.db = get_database(workspace.db_path)
        self.tracker = CostTracker(self.db, self.config)
        self.cache = ProviderCache(workspace.cache_dir)
        self.use_cache = use_cache
        self.ignore_gates = False

    @property
    def project_id(self) -> str:
        return self.spec.project.id

    # --- providers ---------------------------------------------------------------------------
    def _scope(self, stage: str, scene_id: int | None, regeneration: bool) -> CallScope:
        return CallScope(self.project_id, stage, scene_id, regeneration)

    def _wrap(self, cls, inner, stage, scene_id, regeneration):
        return cls(inner, self._scope(stage, scene_id, regeneration), self.tracker, self.cache,
                   self.use_cache)

    def llm(self, stage: str, scene_id: int | None = None, *, vision: bool = False) -> TrackedLLM:
        p = self.spec.providers
        name = p.vision_provider if vision else p.llm
        return self._wrap(TrackedLLM, registry.build_llm(self.ws, name, vision=vision), stage,
                          scene_id, False)

    def image(self, stage: str = "images", scene_id: int | None = None,
              regeneration: bool = False) -> TrackedImage:
        inner = registry.build_image(self.ws, self.spec.providers.image)
        return self._wrap(TrackedImage, inner, stage, scene_id, regeneration)

    def music(self, regeneration: bool = False) -> TrackedMusic:
        inner = registry.build_music(self.ws, self.spec.providers.music)
        return self._wrap(TrackedMusic, inner, "music", None, regeneration)

    def video(self, scene_id: int | None = None, regeneration: bool = False) -> TrackedVideo:
        inner = registry.build_video(self.ws, self.spec.providers.video)
        return self._wrap(TrackedVideo, inner, "videos", scene_id, regeneration)

    def speech(self) -> TrackedSpeech:
        inner = registry.build_speech(self.ws, self.spec.providers.speech)
        return self._wrap(TrackedSpeech, inner, "timing", None, False)

    # --- artifacts ---------------------------------------------------------------------------
    def _require(self, path: Path, hint: str) -> Path:
        if not path.is_file():
            raise MissingArtifact(f"{path.relative_to(self.paths.root)} is missing; run: {hint}")
        return path

    def plan(self) -> CreativePlan:
        path = self._require(self.paths.creative_plan, f"kidsvideo lyrics {self.project_id}")
        return CreativePlan.model_validate(read_json(path))

    def timing(self) -> SongTiming:
        path = self._require(self.paths.timing, f"kidsvideo timing {self.project_id}")
        return SongTiming.model_validate(read_json(path))

    def storyboard(self) -> Storyboard:
        path = self._require(self.paths.storyboard, f"kidsvideo storyboard {self.project_id}")
        return Storyboard.model_validate(read_json(path))

    def resolve(self, p: Path | str) -> Path:
        return self.ws.resolve(p)

    # --- state & approvals -------------------------------------------------------------------
    def state(self) -> ProjectState:
        if self.paths.state.is_file():
            return ProjectState.model_validate(read_json(self.paths.state))
        return ProjectState()

    def save_state(self, state: ProjectState) -> None:
        write_json(self.paths.state, state.model_dump())

    def scene_state(self, scene_id: int) -> SceneState:
        path = self.paths.scene_dir(scene_id) / "metadata.json"
        if path.is_file():
            return SceneState.model_validate(read_json(path))
        return SceneState(scene_id=scene_id)

    def save_scene_state(self, scene: SceneState) -> None:
        write_json(self.paths.scene_dir(scene.scene_id) / "metadata.json", scene.model_dump())

    def gate_artifact_hash(self, gate: Gate) -> str:
        """Hash of what a gate approves; an approval goes stale when this changes."""
        match gate:
            case Gate.lyrics:
                return sha256_file(self._require(self.paths.creative_plan,
                                                 f"kidsvideo lyrics {self.project_id}"))
            case Gate.storyboard:
                return sha256_file(self._require(self.paths.storyboard,
                                                 f"kidsvideo storyboard {self.project_id}"))
            case Gate.preview:
                return sha256_file(self._require(self.paths.output_video("preview"),
                                                 f"kidsvideo render {self.project_id} --preset preview"))
            case Gate.images | Gate.videos:
                track = "image" if gate == Gate.images else "video"
                parts = []
                for scene in self.plan().scenes:
                    t = getattr(self.scene_state(scene.id), track)
                    parts.append(f"{scene.id}:{t.selected}:{t.status}")
                return "|".join(parts)
        raise ValueError(gate)

    def gate_status(self, gate: Gate) -> tuple[bool, str]:
        """(approved, reason). Image/video gates require every scene to be approved."""
        try:
            if gate in (Gate.images, Gate.videos):
                track = "image" if gate == Gate.images else "video"
                pending = [s.id for s in self.plan().scenes
                           if getattr(self.scene_state(s.id), track).status != "approved"]
                if pending:
                    return False, f"scenes not approved: {pending}"
                return True, "all scenes approved"
            approval = self.state().approvals.get(gate.value)
            if approval is None:
                return False, "not approved yet"
            if approval.artifact_hash != self.gate_artifact_hash(gate):
                return False, "changed since it was approved"
            return True, f"approved {approval.approved_at}"
        except MissingArtifact as e:
            return False, str(e)

    def require_gate(self, gate: Gate) -> None:
        if self.ignore_gates:
            return
        ok, reason = self.gate_status(gate)
        if not ok:
            raise GateError(gate, self.project_id, reason)

    def approve(self, gate: Gate, note: str = "") -> None:
        state = self.state()
        state.approvals[gate.value] = Approval(
            approved_at=now_iso(), artifact_hash=self.gate_artifact_hash(gate), note=note
        )
        self.save_state(state)

    def revoke(self, gate: Gate) -> None:
        state = self.state()
        if state.approvals.pop(gate.value, None) is not None:
            self.save_state(state)
