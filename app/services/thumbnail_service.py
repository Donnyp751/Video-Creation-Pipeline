"""Thumbnail pipeline: text-free artwork from the image model + deterministic typography.

Image models misspell text (especially Vietnamese diacritics), so the title is drawn with Pillow.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.pipeline.context import PipelineContext, PipelineError
from app.services.character_bible import load_bibles, reference_images
from app.services.prompt_compiler import compile_thumbnail_prompt
from app.utils.files import list_versions, write_json, write_text
from app.utils.scripts import cjk_font_file, has_cjk

THUMB_SIZE = (1280, 720)
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def find_font(ctx: PipelineContext | None = None) -> Path | None:
    candidates: list[Path] = []
    if ctx is not None:
        if ctx.config.title_font:
            candidates.append(ctx.resolve(ctx.config.title_font))
        fonts_dir = ctx.ws.assets_dir / "templates" / "fonts"
        if fonts_dir.is_dir():
            candidates += sorted(fonts_dir.glob("*.ttf")) + sorted(fonts_dir.glob("*.otf"))
    candidates += [Path(p) for p in FONT_CANDIDATES]
    return next((p for p in candidates if p.is_file()), None)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        trial = f"{lines[-1]} {word}" if lines else word
        if lines and draw.textlength(trial, font=font) <= max_width:
            lines[-1] = trial
        else:
            lines.append(word)
    return lines


def overlay_title(artwork: Path, title: str, output: Path, font_path: Path | None,
                  font_index: int = 0,
                  subtitle: str | None = None) -> Path:
    img = Image.open(artwork).convert("RGB")
    # Cover-fit to 16:9 thumbnail size.
    scale = max(THUMB_SIZE[0] / img.width, THUMB_SIZE[1] / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left = (img.width - THUMB_SIZE[0]) // 2
    top = (img.height - THUMB_SIZE[1]) // 2
    img = img.crop((left, top, left + THUMB_SIZE[0], top + THUMB_SIZE[1]))

    draw = ImageDraw.Draw(img)
    max_w = int(THUMB_SIZE[0] * 0.42)
    size = 130
    while True:
        font = (ImageFont.truetype(str(font_path), size, index=font_index) if font_path
                else ImageFont.load_default(size=size))
        lines = _wrap(draw, title, font, max_w)
        line_h = int(size * 1.15)
        if (len(lines) * line_h <= THUMB_SIZE[1] * 0.7
                and all(draw.textlength(ln, font=font) <= max_w for ln in lines)) or size <= 40:
            break
        size -= 6
    y = (THUMB_SIZE[1] - len(lines) * line_h) // 2
    for ln in lines:
        draw.text((48, y), ln, font=font, fill=(255, 225, 40), stroke_width=max(4, size // 12),
                  stroke_fill=(30, 30, 90))
        y += line_h
    if subtitle:
        sub_size = max(28, size // 3)
        sub_font = (ImageFont.truetype(str(font_path), sub_size, index=font_index) if font_path
                    else ImageFont.load_default(size=sub_size))
        draw.text((52, y + 8), subtitle, font=sub_font, fill=(255, 255, 255),
                  stroke_width=3, stroke_fill=(30, 30, 90))
    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(output, "PNG")
    return output


async def generate_candidates(ctx: PipelineContext, count: int | None = None) -> list[Path]:
    count = count or ctx.config.thumbnail_candidates
    d = ctx.paths.thumbnail
    plan = ctx.plan()
    bibles = load_bibles(ctx)
    prompt = compile_thumbnail_prompt(ctx.spec, bibles, plan.title)
    write_text(d / "prompt.txt", prompt)
    refs = [r for b in bibles for r in reference_images(ctx, b.name, limit=1)]
    existing = list_versions(d, "candidate", ".png")
    start = existing[-1][0] + 1 if existing else 1
    provider = ctx.image(stage="thumbnail")

    async def one(n: int) -> Path:
        out = d / f"candidate_v{n}.png"
        await provider.generate(prompt, refs, "16:9", out, variant=n)
        return out

    return list(await asyncio.gather(*(one(n) for n in range(start, start + count))))


def select_candidate(ctx: PipelineContext, version: int, *, title: str | None = None) -> Path:
    d = ctx.paths.thumbnail
    src = d / f"candidate_v{version}.png"
    if not src.is_file():
        raise PipelineError(f"no thumbnail candidate v{version}")
    plan = ctx.plan()
    title = title or plan.title
    subtitle = plan.title_secondary or None
    font_path, font_index = find_font(ctx), 0
    if has_cjk(title + (subtitle or "")) and (cjk := cjk_font_file(ctx.spec.languages.script)):
        font_path, font_index = cjk  # Latin-only fonts would draw empty boxes for 汉字
    out = overlay_title(src, title, d / "selected.png", font_path, font_index,
                        subtitle=plan.title_secondary or None)
    write_json(d / "selection.json", {"candidate": version, "title": title})
    return out
