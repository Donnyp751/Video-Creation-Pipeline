"""Thin async wrappers around the ffmpeg / ffprobe binaries."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def ffmpeg_bin() -> str:
    return os.environ.get("FFMPEG_BIN") or shutil.which("ffmpeg") or "ffmpeg"


def ffprobe_bin() -> str:
    return os.environ.get("FFPROBE_BIN") or shutil.which("ffprobe") or "ffprobe"


def ffmpeg_available() -> bool:
    return shutil.which(ffmpeg_bin()) is not None and shutil.which(ffprobe_bin()) is not None


async def _run(cmd: list[str], cwd: Path | None = None) -> tuple[bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        tail = err.decode("utf-8", "replace")[-3000:]
        raise FFmpegError(f"{Path(cmd[0]).name} exited with {proc.returncode}:\n{tail}")
    return out, err


async def run_ffmpeg(args: list[str], cwd: Path | None = None) -> str:
    """Run ffmpeg with ``args``; returns stderr (ffmpeg logs analysis output there)."""
    _, err = await _run([ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", *args], cwd=cwd)
    return err.decode("utf-8", "replace")


async def probe(path: Path) -> dict:
    out, _ = await _run(
        [ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
         str(path)]
    )
    return json.loads(out)


async def media_duration(path: Path) -> float:
    info = await probe(path)
    return float(info["format"]["duration"])


async def has_audio(path: Path) -> bool:
    info = await probe(path)
    return any(s.get("codec_type") == "audio" for s in info.get("streams", []))


async def to_wav(src: Path, dst: Path, sample_rate: int = 44100) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    await run_ffmpeg(["-i", str(src), "-ar", str(sample_rate), "-ac", "2", "-c:a", "pcm_s16le",
                      str(dst)])
    return dst


async def to_speech_mp3(src: Path, dst: Path) -> Path:
    """Small mono file suitable for transcription APIs (which have upload size limits)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    await run_ffmpeg(["-i", str(src), "-ac", "1", "-ar", "16000", "-b:a", "48k", str(dst)])
    return dst


async def extract_frames(video: Path, out_dir: Path, times: list[float]) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i, t in enumerate(times):
        dst = out_dir / f"frame_{i:02d}.jpg"
        await run_ffmpeg(["-ss", f"{max(t, 0):.3f}", "-i", str(video), "-frames:v", "1",
                          "-q:v", "3", str(dst)])
        frames.append(dst)
    return frames
