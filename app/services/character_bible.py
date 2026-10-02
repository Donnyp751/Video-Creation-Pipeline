"""Character Bible: load structured character definitions and their reference images.

Layout (workspace-level, shared by all projects):

    assets/characters/<id>/
        character.yaml
        reference_sheet.png  front.png  side.png  happy.png  surprised.png  singing.png
"""

from __future__ import annotations

from pathlib import Path

from app.models.character import REFERENCE_POSES, CharacterBible
from app.models.project import CharacterRef, ProjectSpec
from app.pipeline.context import PipelineContext
from app.utils.files import write_text


def character_dir(ctx: PipelineContext, character_id: str) -> Path:
    return ctx.ws.assets_dir / "characters" / character_id


def load_bible(ctx: PipelineContext, ref: CharacterRef) -> CharacterBible:
    """The bible entry if one exists, else a minimal one built from project.yaml."""
    path = character_dir(ctx, ref.id) / "character.yaml"
    if path.is_file():
        bible = CharacterBible.load(path)
        if not bible.description:
            bible.description = ref.description
        return bible
    return CharacterBible(name=ref.id, description=ref.description)


def load_bibles(ctx: PipelineContext, ids: list[str] | None = None) -> list[CharacterBible]:
    spec: ProjectSpec = ctx.spec
    refs = spec.characters if ids is None else [spec.character(i) for i in ids]
    return [load_bible(ctx, r) for r in refs]


def reference_images(ctx: PipelineContext, character_id: str, limit: int = 2) -> list[Path]:
    """Best available reference images for a character, most informative first."""
    found: list[Path] = []
    d = character_dir(ctx, character_id)
    for pose in REFERENCE_POSES:
        p = d / f"{pose}.png"
        if p.is_file():
            found.append(p)
    ref = ctx.spec.character(character_id).reference
    if ref:
        p = ctx.resolve(ref)
        if p.is_file() and p not in found:
            found.append(p)
    return found[:limit]


def environment_reference(ctx: PipelineContext) -> list[Path]:
    ref = ctx.spec.environment.reference
    if ref and (p := ctx.resolve(ref)).is_file():
        return [p]
    return []


def init_bible(ctx: PipelineContext) -> list[Path]:
    """Write a character.yaml skeleton for every character that doesn't have one yet."""
    created = []
    for ref in ctx.spec.characters:
        path = character_dir(ctx, ref.id) / "character.yaml"
        if path.exists():
            continue
        bible = CharacterBible(
            name=ref.id,
            description=" ".join(ref.description.split()),
            physical={"hair": "", "eyes": ""},
            clothing={"top": "", "bottom": ""},
            never_change=["hairstyle", "eye color", "clothing colors"],
        )
        write_text(path, bible.to_yaml())
        created.append(path)
    return created


async def generate_reference_sheets(ctx: PipelineContext, force: bool = False) -> list[Path]:
    """Create reference_sheet.png per character via the image provider (once)."""
    from app.services.prompt_compiler import compile_reference_sheet_prompt

    made = []
    for bible in load_bibles(ctx):
        out = character_dir(ctx, bible.name) / "reference_sheet.png"
        if out.exists() and not force:
            continue
        prompt = compile_reference_sheet_prompt(ctx.spec.style.description, bible)
        refs = reference_images(ctx, bible.name)
        refs = [r for r in refs if r != out]
        provider = ctx.image(stage="bible")
        await provider.generate(prompt, refs, "16:9", out)
        made.append(out)
    return made
