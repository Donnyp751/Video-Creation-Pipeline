"""Create new projects from the template."""

from __future__ import annotations

import re

import yaml

from app.core.config import Workspace
from app.models.project import ProjectSpec
from app.utils.files import write_text

DEFAULT_TEMPLATE = {
    "project": {"id": "", "title": "", "target_age_min": 2, "target_age_max": 5,
                "aspect_ratio": "16:9", "resolution": "1920x1080", "fps": 30},
    "languages": {"primary": "vi", "secondary": "en"},
    "creative": {"topic": "", "learning_goal": "", "tone": "cheerful",
                 "duration_target_seconds": 120},
    "characters": [
        {"id": "brother", "reference": "assets/characters/brother/front.png",
         "description": "Four-year-old boy, fluffy black hair, large brown eyes, green t-shirt, "
                        "blue shorts."},
        {"id": "sister", "reference": "assets/characters/sister/front.png",
         "description": "Three-year-old girl, two pigtails, pink bows, yellow dress."},
    ],
    "environment": {"default": "farm", "reference": "assets/environments/farm.png"},
    "style": {"description": "Cute soft 3D toddler cartoon, bright cheerful colors, warm sunny "
                             "lighting."},
    "providers": {"llm": "openai", "image": "openai", "music": "elevenlabs", "video": "runway"},
}


def create_project(ws: Workspace, project_id: str, *, title: str | None = None,
                   topic: str | None = None, learning_goal: str | None = None,
                   duration: int | None = None) -> ProjectSpec:
    if not re.match(r"^[a-z0-9][a-z0-9_-]*$", project_id):
        raise ValueError("project id must be lowercase letters, digits, '-' or '_'")
    root = ws.projects_dir / project_id
    if (root / "project.yaml").exists():
        raise FileExistsError(f"project '{project_id}' already exists")

    template_path = ws.assets_dir / "templates" / "project.yaml"
    data = (yaml.safe_load(template_path.read_text("utf-8")) if template_path.is_file()
            else DEFAULT_TEMPLATE)
    data = yaml.safe_load(yaml.safe_dump(data))  # deep copy
    data["project"]["id"] = project_id
    data["project"]["title"] = title or data["project"].get("title") or project_id
    topic = topic or data["creative"].get("topic") or project_id.split("-")[0]
    data["creative"]["topic"] = topic
    data["creative"]["learning_goal"] = (learning_goal or data["creative"].get("learning_goal")
                                         or f"Teach {topic} words in both languages")
    if duration:
        data["creative"]["duration_target_seconds"] = duration
    spec = ProjectSpec.model_validate(data)
    write_text(root / "project.yaml", spec.to_yaml())
    return spec
