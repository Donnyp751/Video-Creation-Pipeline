"""Automated QC of a rendered video: duration, format, loudness, black frames, silence."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from app.core.config import QCConfig, RenderPreset
from app.pipeline.context import PipelineContext, PipelineError
from app.utils.ffmpeg import probe, run_ffmpeg
from app.utils.files import now_iso, read_json, write_json


class QCCheck(BaseModel):
    name: str
    passed: bool
    detail: str


class QCReport(BaseModel):
    file: str
    created_at: str
    passed: bool
    checks: list[QCCheck]


def _fps(rate: str) -> float:
    num, _, den = rate.partition("/")
    return float(num) / float(den or 1)


async def analyze(path: Path) -> dict:
    info = await probe(path)
    log = await run_ffmpeg([
        "-i", str(path),
        "-vf", "blackdetect=d=0.5:pix_th=0.10",
        "-af", "silencedetect=n=-50dB:d=1,ebur128=framelog=quiet",
        "-f", "null", "-",
    ])
    lufs = re.findall(r"I:\s+(-?[\d.]+) LUFS", log)
    blacks = [float(x) for x in re.findall(r"black_duration:([\d.]+)", log)]
    silences = [float(x) for x in re.findall(r"silence_duration: ([\d.]+)", log)]
    return {
        "info": info,
        "integrated_lufs": float(lufs[-1]) if lufs else None,
        "black_segments": blacks,
        "silence_segments": silences,
    }


def evaluate(data: dict, *, expected_duration: float, preset: RenderPreset, qc: QCConfig
             ) -> list[QCCheck]:
    info = data["info"]
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(info["format"]["duration"])
    checks = [
        QCCheck(name="streams", passed=bool(video and audio),
                detail=f"video={'yes' if video else 'no'} audio={'yes' if audio else 'no'}"),
        QCCheck(name="duration",
                passed=abs(duration - expected_duration) <= qc.duration_tolerance_s,
                detail=f"{duration:.2f}s (expected {expected_duration:.2f}s)"),
    ]
    if video:
        res = f"{video['width']}x{video['height']}"
        fps = _fps(video.get("avg_frame_rate") or video.get("r_frame_rate", "0/1"))
        checks += [
            QCCheck(name="resolution", passed=res == preset.resolution,
                    detail=f"{res} (expected {preset.resolution})"),
            QCCheck(name="fps", passed=abs(fps - preset.fps) < 0.1,
                    detail=f"{fps:.2f} (expected {preset.fps})"),
        ]
    lufs = data["integrated_lufs"]
    checks.append(QCCheck(
        name="loudness",
        passed=lufs is not None and abs(lufs - qc.target_lufs) <= qc.lufs_tolerance,
        detail=f"{lufs} LUFS (target {qc.target_lufs}±{qc.lufs_tolerance})",
    ))
    long_black = [b for b in data["black_segments"] if b > qc.max_black_s]
    checks.append(QCCheck(name="black_frames", passed=not long_black,
                          detail=f"black segments > {qc.max_black_s}s: {long_black}"))
    long_silence = [s for s in data["silence_segments"] if s > qc.max_silence_s]
    checks.append(QCCheck(name="silence", passed=not long_silence,
                          detail=f"silences > {qc.max_silence_s}s: {long_silence}"))
    return checks


async def run_qc(ctx: PipelineContext, preset_name: str) -> QCReport:
    preset = ctx.config.render_presets[preset_name]
    path = ctx.paths.output_video(preset_name)
    if not path.is_file():
        raise PipelineError(f"nothing rendered for '{preset_name}'")
    render_info = read_json(ctx.paths.render_dir(preset_name) / "render.json")
    data = await analyze(path)
    checks = evaluate(data, expected_duration=render_info["total_duration"], preset=preset,
                      qc=ctx.config.qc)
    report = QCReport(file=str(path.relative_to(ctx.paths.root)), created_at=now_iso(),
                      passed=all(c.passed for c in checks), checks=checks)
    write_json(ctx.paths.render_dir(preset_name) / "qc.json", report.model_dump())
    return report
