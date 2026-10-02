"""Deterministic prompt compiler.

The LLM decides *what happens* in a scene. This module decides *how it is described* to the image
and video models: style, character definitions, environment, composition and constraints are
assembled from the project spec and Character Bible the same way every time.
"""

from __future__ import annotations

from app.models.character import CharacterBible
from app.models.creative import ScenePlan
from app.models.project import ProjectSpec

BASE_CONSTRAINTS = [
    "No text, letters, numbers, logos or watermarks anywhere in the image.",
    "Child-safe, gentle and friendly; nothing scary.",
    "Correct anatomy: five fingers per hand, two arms, two legs.",
]


def _block(title: str, body: str) -> str:
    return f"{title}:\n{body.strip()}"


def _norm(text: str) -> str:
    return " ".join(text.split())


def environment_text(spec: ProjectSpec, scene: ScenePlan | None = None) -> str:
    env = (scene.environment if scene and scene.environment else None) or spec.environment.default
    desc = spec.environment.description
    if desc and env == spec.environment.default:
        return f"{env}: {_norm(desc)}"
    return env


def scene_constraints(scene: ScenePlan, characters: list[CharacterBible]) -> list[str]:
    out = list(BASE_CONSTRAINTS)
    if characters:
        names = ", ".join(c.display_name or c.name for c in characters)
        out.append(f"Exactly {len(characters)} character(s): {names}. No additional people.")
    else:
        out.append("No people or characters.")
    for c in characters:
        for item in c.never_change:
            out.append(f"{c.display_name or c.name}: {item} must match the definition exactly.")
    for obj in scene.objects:
        if obj.count:
            out.append(f"Exactly {obj.count} {obj.name}.")
    return out


def compile_image_prompt(
    spec: ProjectSpec,
    scene: ScenePlan,
    characters: list[CharacterBible],
    extra_constraints: list[str] | None = None,
) -> str:
    composition = f"{spec.project.aspect_ratio} frame. {scene.composition or 'Medium shot'}."
    composition += " Characters fully inside the frame with headroom; clear simple background."
    action = _norm(scene.action)
    if scene.objects:
        action += " Objects: " + "; ".join(
            f"{o.count} x {o.name}{(' (' + o.description + ')') if o.description else ''}"
            for o in scene.objects
        ) + "."
    blocks = [
        _block("STYLE", _norm(spec.style.description)),
        _block("CHARACTERS", "\n".join(f"- {c.definition()}" for c in characters)
               if characters else "None."),
        _block("ENVIRONMENT", environment_text(spec, scene)),
        _block("SCENE", action),
        _block("COMPOSITION", composition),
        _block("CONSTRAINTS", "\n".join(
            f"- {c}" for c in scene_constraints(scene, characters) + (extra_constraints or [])
            + [f"Avoid: {n}" for n in spec.style.negative]
        )),
    ]
    return "\n\n".join(blocks) + "\n"


def compile_motion_prompt(scene: ScenePlan, characters: list[CharacterBible]) -> str:
    names = ", ".join(c.display_name or c.name for c in characters)
    parts = [
        _norm(scene.motion_prompt),
        f"Camera: {scene.camera}.",
        "Gentle, smooth, toddler-friendly motion.",
        "Keep every character's face, hair, clothing and proportions identical to the image.",
        "No new characters or objects appear; characters stay inside the frame.",
    ]
    if names:
        parts.insert(1, f"Characters: {names}.")
    return " ".join(parts)


def compile_reference_sheet_prompt(style: str, character: CharacterBible) -> str:
    return "\n\n".join([
        _block("STYLE", _norm(style)),
        _block("CHARACTER", character.definition()),
        _block("LAYOUT", "Character reference sheet: full-body front view, side view, back view "
               "and three facial expressions (happy, surprised, singing) on a plain white "
               "background, evenly spaced."),
        _block("CONSTRAINTS", "\n".join(f"- {c}" for c in BASE_CONSTRAINTS)),
    ]) + "\n"


def compile_thumbnail_prompt(spec: ProjectSpec, characters: list[CharacterBible],
                             title: str) -> str:
    return "\n\n".join([
        _block("STYLE", _norm(spec.style.description) + " Extra vibrant, high contrast, "
               "eye-catching YouTube thumbnail for young children."),
        _block("CHARACTERS", "\n".join(f"- {c.definition()}" for c in characters)),
        _block("SCENE", f"The characters look delighted, surrounded by large, clear "
               f"{spec.creative.topic} related objects. Theme of the song: '{title}'."),
        _block("COMPOSITION", "16:9. Characters large on the right two-thirds, big expressive "
               "faces. Leave the left third uncluttered with a simple background for a title "
               "that will be added later."),
        _block("CONSTRAINTS", "\n".join(f"- {c}" for c in BASE_CONSTRAINTS)),
    ]) + "\n"
