#!/usr/bin/env python3
"""Kazakh YouTube subtitle generation via Alem speech-to-text.

This tool downloads a YouTube video's audio with yt-dlp, chunks it into
API-friendly WAV files with ffmpeg, sends each chunk to Alem's Kazakh
speech-to-text endpoint, and writes SRT/VTT/TXT/JSON subtitle artifacts.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

from hermes_constants import get_hermes_home
from tools.registry import registry, tool_error

ALEM_STT_URL = "https://llm.alem.ai/v1/audio/transcriptions"
DEFAULT_MODEL = "speech-to-text-kk"
DEFAULT_CHUNK_SECONDS = 300
MAX_CHUNK_SECONDS = 900
MIN_CHUNK_SECONDS = 30
OUTPUT_SUBDIR = "kazakh-youtube-subtitles"


@dataclass
class SubtitleSegment:
    start: float
    end: float
    text: str


def _get_env_value(name: str) -> Optional[str]:
    try:
        from hermes_cli.config import get_env_value

        value = get_env_value(name)
    except Exception:
        value = os.getenv(name)
    return value or None


def _api_key() -> Optional[str]:
    """Resolve the Alem STT key.

    ALEM_STT_API_KEY is preferred so the transcription key can be scoped
    separately from chat-model keys. ALEM_API_KEY is accepted as a fallback for
    users who already configured the Alem provider globally.
    """

    return _get_env_value("ALEM_STT_API_KEY") or _get_env_value("ALEM_API_KEY")


def _has_binary(name: str) -> bool:
    return shutil.which(name) is not None


def check_kazakh_youtube_subtitles_requirements() -> bool:
    return bool(_api_key()) and _has_binary("ffmpeg") and _has_binary("ffprobe") and _has_binary("yt-dlp")


def _run(cmd: List[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)


def _slugify(value: str, fallback: str = "youtube-video") -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return (slug or fallback)[:80]


def _json_loads_maybe(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def _download_audio(youtube_url: str, workdir: Path) -> tuple[Path, Dict[str, Any]]:
    metadata_cmd = ["yt-dlp", "--dump-json", "--no-playlist", youtube_url]
    meta_proc = _run(metadata_cmd, timeout=120)
    metadata = _json_loads_maybe(meta_proc.stdout.splitlines()[0] if meta_proc.stdout.strip() else "{}")

    outtmpl = str(workdir / "source.%(ext)s")
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--extract-audio",
        "--audio-format",
        "wav",
        "--audio-quality",
        "0",
        "--output",
        outtmpl,
        youtube_url,
    ]
    proc = _run(cmd, timeout=1800)
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {proc.stderr.strip() or proc.stdout.strip()}")

    candidates = sorted(workdir.glob("source*.wav"))
    if not candidates:
        # yt-dlp/ffmpeg may preserve a slightly different extension in edge cases.
        candidates = [p for p in workdir.iterdir() if p.is_file() and p.name.startswith("source.")]
    if not candidates:
        raise RuntimeError("yt-dlp did not produce an audio file")
    return candidates[0], metadata


def _duration_seconds(path: Path) -> float:
    proc = _run([
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ], timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {proc.stderr.strip()}")
    try:
        return max(0.0, float(proc.stdout.strip()))
    except ValueError as exc:
        raise RuntimeError(f"Could not parse audio duration from ffprobe: {proc.stdout!r}") from exc


def _chunk_audio(source: Path, chunks_dir: Path, chunk_seconds: int) -> List[Path]:
    chunks_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(chunks_dir / "chunk_%05d.wav")
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "segment",
        "-segment_time",
        str(chunk_seconds),
        "-reset_timestamps",
        "1",
        pattern,
    ]
    proc = _run(cmd, timeout=1800)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg chunking failed: {proc.stderr.strip()}")
    chunks = sorted(chunks_dir.glob("chunk_*.wav"))
    if not chunks:
        raise RuntimeError("ffmpeg did not produce audio chunks")
    return chunks


def _transcribe_chunk(path: Path, *, api_key: str, model: str, timeout: int = 300) -> Dict[str, Any]:
    with path.open("rb") as fh:
        response = requests.post(
            ALEM_STT_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            data={"model": model},
            files={"file": (path.name, fh, "audio/wav")},
            timeout=timeout,
        )
    if response.status_code >= 400:
        body = response.text[:1000]
        raise RuntimeError(f"Alem STT HTTP {response.status_code}: {body}")
    try:
        return response.json()
    except ValueError:
        return {"text": response.text}


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _segments_from_response(data: Dict[str, Any], chunk_start: float, chunk_duration: float) -> List[SubtitleSegment]:
    raw_segments = data.get("segments")
    segments: List[SubtitleSegment] = []
    if isinstance(raw_segments, list):
        for item in raw_segments:
            if not isinstance(item, dict):
                continue
            text = _normalize_text(str(item.get("text") or ""))
            if not text:
                continue
            start = float(item.get("start") or 0.0) + chunk_start
            end = float(item.get("end") or 0.0) + chunk_start
            if end <= start:
                end = min(chunk_start + chunk_duration, start + 4.0)
            segments.append(SubtitleSegment(start=start, end=end, text=text))
    if segments:
        return segments

    text = _normalize_text(str(data.get("text") or data.get("transcript") or ""))
    return _approximate_segments(text, chunk_start, chunk_duration)


def _approximate_segments(text: str, chunk_start: float, chunk_duration: float) -> List[SubtitleSegment]:
    """Build readable subtitle cues when the STT API returns text only.

    Alem's endpoint is OpenAI-compatible and may return only a `text` field.
    We cannot recover true word timings from text alone, so this creates
    evenly-distributed cues sized for readability. The final JSON marks timing
    mode as approximate.
    """

    text = _normalize_text(text)
    if not text:
        return []

    words = text.split()
    # Around 8 words per subtitle line; cap cue count to avoid sub-second spam.
    words_per_cue = 8
    cue_count = max(1, math.ceil(len(words) / words_per_cue))
    min_cue_seconds = 1.5
    if cue_count * min_cue_seconds > chunk_duration and chunk_duration > 0:
        cue_count = max(1, int(chunk_duration / min_cue_seconds))
        words_per_cue = max(1, math.ceil(len(words) / cue_count))

    cue_duration = max(min_cue_seconds, chunk_duration / max(1, cue_count)) if chunk_duration > 0 else 4.0
    segments: List[SubtitleSegment] = []
    for idx in range(0, len(words), words_per_cue):
        cue_index = len(segments)
        start = chunk_start + cue_index * cue_duration
        end = min(chunk_start + max(chunk_duration, cue_duration), start + cue_duration)
        if end <= start:
            end = start + cue_duration
        segments.append(SubtitleSegment(start=start, end=end, text=" ".join(words[idx : idx + words_per_cue])))
    return segments


def _fmt_srt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    millis = int(round((seconds - int(seconds)) * 1000))
    total = int(seconds)
    if millis == 1000:
        total += 1
        millis = 0
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{millis:03d}"


def _fmt_vtt_time(seconds: float) -> str:
    return _fmt_srt_time(seconds).replace(",", ".")


def _render_srt(segments: Iterable[SubtitleSegment]) -> str:
    blocks = []
    for idx, seg in enumerate(segments, 1):
        blocks.append(f"{idx}\n{_fmt_srt_time(seg.start)} --> {_fmt_srt_time(seg.end)}\n{seg.text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _render_vtt(segments: Iterable[SubtitleSegment]) -> str:
    blocks = ["WEBVTT", ""]
    for seg in segments:
        blocks.append(f"{_fmt_vtt_time(seg.start)} --> {_fmt_vtt_time(seg.end)}\n{seg.text}\n")
    return "\n".join(blocks).rstrip() + "\n"


def _write_outputs(
    *,
    segments: List[SubtitleSegment],
    output_dir: Path,
    basename: str,
    formats: List[str],
    metadata: Dict[str, Any],
    full_text: str,
    timing_mode: str,
) -> Dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: Dict[str, str] = {}
    if "srt" in formats:
        path = output_dir / f"{basename}.kk.srt"
        path.write_text(_render_srt(segments), encoding="utf-8")
        paths["srt"] = str(path)
    if "vtt" in formats:
        path = output_dir / f"{basename}.kk.vtt"
        path.write_text(_render_vtt(segments), encoding="utf-8")
        paths["vtt"] = str(path)
    if "txt" in formats:
        path = output_dir / f"{basename}.kk.txt"
        path.write_text(full_text + "\n", encoding="utf-8")
        paths["txt"] = str(path)
    if "json" in formats:
        path = output_dir / f"{basename}.kk.json"
        payload = {
            "metadata": metadata,
            "language": "kk",
            "timing_mode": timing_mode,
            "text": full_text,
            "segments": [seg.__dict__ for seg in segments],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        paths["json"] = str(path)
    return paths


def create_kazakh_youtube_subtitles(
    youtube_url: str,
    output_dir: Optional[str] = None,
    formats: Optional[List[str]] = None,
    model: str = DEFAULT_MODEL,
    chunk_seconds: int = DEFAULT_CHUNK_SECONDS,
    keep_audio: bool = False,
) -> str:
    if not youtube_url or not youtube_url.strip():
        return tool_error("youtube_url is required")

    api_key = _api_key()
    if not api_key:
        return tool_error("ALEM_STT_API_KEY is not configured. Put it in ~/.hermes/.env or the active profile .env.")
    missing = [name for name in ("yt-dlp", "ffmpeg", "ffprobe") if not _has_binary(name)]
    if missing:
        return tool_error(f"Missing required command(s): {', '.join(missing)}. Install yt-dlp and ffmpeg first.")

    if formats is None:
        formats = ["srt", "vtt", "txt", "json"]
    if isinstance(formats, str):
        formats = [part.strip().lower() for part in formats.split(",") if part.strip()]
    allowed_formats = {"srt", "vtt", "txt", "json"}
    formats = [fmt.lower() for fmt in formats if fmt and fmt.lower() in allowed_formats]
    if not formats:
        return tool_error("formats must include one or more of: srt, vtt, txt, json")

    try:
        chunk_seconds = int(chunk_seconds)
    except (TypeError, ValueError):
        chunk_seconds = DEFAULT_CHUNK_SECONDS
    chunk_seconds = max(MIN_CHUNK_SECONDS, min(MAX_CHUNK_SECONDS, chunk_seconds))

    outdir = Path(output_dir).expanduser() if output_dir else get_hermes_home() / OUTPUT_SUBDIR
    outdir = outdir.resolve()

    try:
        with tempfile.TemporaryDirectory(prefix="hermes-kk-subs-") as tmp:
            workdir = Path(tmp)
            source_audio, video_meta = _download_audio(youtube_url.strip(), workdir)
            duration = _duration_seconds(source_audio)
            chunks = _chunk_audio(source_audio, workdir / "chunks", chunk_seconds)

            all_segments: List[SubtitleSegment] = []
            texts: List[str] = []
            timing_mode = "exact"  # downgraded if any chunk lacks segment timestamps
            for idx, chunk in enumerate(chunks):
                chunk_start = idx * chunk_seconds
                chunk_duration = _duration_seconds(chunk)
                response_data = _transcribe_chunk(chunk, api_key=api_key, model=model)
                if not response_data.get("segments"):
                    timing_mode = "approximate"
                text = _normalize_text(str(response_data.get("text") or response_data.get("transcript") or ""))
                if text:
                    texts.append(text)
                all_segments.extend(_segments_from_response(response_data, chunk_start, chunk_duration))

            full_text = _normalize_text(" ".join(texts) or " ".join(seg.text for seg in all_segments))
            title = str(video_meta.get("title") or video_meta.get("id") or "youtube-video")
            video_id = str(video_meta.get("id") or "")
            basename = _slugify(f"{video_id}-{title}" if video_id else title)
            metadata = {
                "source_url": youtube_url.strip(),
                "title": title,
                "video_id": video_id,
                "duration_seconds": duration,
                "model": model,
                "chunk_seconds": chunk_seconds,
                "segment_count": len(all_segments),
            }
            paths = _write_outputs(
                segments=all_segments,
                output_dir=outdir,
                basename=basename,
                formats=formats,
                metadata=metadata,
                full_text=full_text,
                timing_mode=timing_mode,
            )

            if keep_audio:
                audio_path = outdir / f"{basename}.wav"
                shutil.copy2(source_audio, audio_path)
                paths["audio"] = str(audio_path)

        return json.dumps(
            {
                "success": True,
                "source_url": youtube_url.strip(),
                "title": title,
                "video_id": video_id,
                "duration_seconds": duration,
                "language": "kk",
                "model": model,
                "timing_mode": timing_mode,
                "subtitle_segments": len(all_segments),
                "text_chars": len(full_text),
                "outputs": paths,
                "note": "timing_mode=approximate means the STT API returned text without timestamps, so cue timings were evenly distributed per audio chunk.",
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        return tool_error(str(exc))


KAZAKH_YOUTUBE_SUBTITLES_SCHEMA = {
    "name": "create_kazakh_youtube_subtitles",
    "description": (
        "Create Kazakh subtitles for a YouTube video. Downloads audio with yt-dlp, "
        "transcribes it with Alem speech-to-text model speech-to-text-kk, and writes "
        "SRT/VTT/TXT/JSON files. Requires ALEM_STT_API_KEY plus yt-dlp/ffmpeg."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "youtube_url": {
                "type": "string",
                "description": "YouTube video URL or video ID to subtitle.",
            },
            "output_dir": {
                "type": "string",
                "description": f"Directory for generated files. Defaults to ~/.hermes/{OUTPUT_SUBDIR}.",
            },
            "formats": {
                "type": "array",
                "items": {"type": "string", "enum": ["srt", "vtt", "txt", "json"]},
                "description": "Output formats to write. Defaults to all four: srt, vtt, txt, json.",
            },
            "model": {
                "type": "string",
                "description": "Alem STT model name. Defaults to speech-to-text-kk.",
            },
            "chunk_seconds": {
                "type": "integer",
                "description": "Audio chunk size in seconds for the STT API. Clamped to 30-900. Default: 300.",
            },
            "keep_audio": {
                "type": "boolean",
                "description": "If true, also save the downloaded WAV audio next to the subtitles.",
            },
        },
        "required": ["youtube_url"],
    },
}


registry.register(
    name="create_kazakh_youtube_subtitles",
    toolset="media",
    schema=KAZAKH_YOUTUBE_SUBTITLES_SCHEMA,
    handler=lambda args, **kw: create_kazakh_youtube_subtitles(
        youtube_url=args.get("youtube_url", ""),
        output_dir=args.get("output_dir"),
        formats=args.get("formats"),
        model=args.get("model") or DEFAULT_MODEL,
        chunk_seconds=args.get("chunk_seconds", DEFAULT_CHUNK_SECONDS),
        keep_audio=bool(args.get("keep_audio", False)),
    ),
    check_fn=check_kazakh_youtube_subtitles_requirements,
    requires_env=["ALEM_STT_API_KEY"],
    emoji="🎬",
    max_result_size_chars=20_000,
)
