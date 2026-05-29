from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import tools.kazakh_youtube_subtitles_tool as kk


def test_timestamp_formatting_rolls_millis():
    assert kk._fmt_srt_time(3661.234) == "01:01:01,234"
    assert kk._fmt_vtt_time(1.5) == "00:00:01.500"


def test_approximate_segments_are_readable_and_bounded():
    text = "бір екі үш төрт бес алты жеті сегіз тоғыз он он бір он екі"
    segments = kk._approximate_segments(text, chunk_start=10.0, chunk_duration=8.0)

    assert segments
    assert segments[0].start == 10.0
    assert all(seg.end > seg.start for seg in segments)
    assert segments[-1].end <= 18.0
    assert "бір" in segments[0].text


def test_segments_from_timestamped_response():
    data = {"segments": [{"start": 1, "end": 2.5, "text": " сәлем әлем "}]}

    segments = kk._segments_from_response(data, chunk_start=30.0, chunk_duration=10.0)

    assert len(segments) == 1
    assert segments[0].start == 31.0
    assert segments[0].end == 32.5
    assert segments[0].text == "сәлем әлем"


def test_write_outputs(tmp_path: Path):
    segments = [kk.SubtitleSegment(start=0, end=2, text="Сәлем")]

    paths = kk._write_outputs(
        segments=segments,
        output_dir=tmp_path,
        basename="video",
        formats=["srt", "vtt", "txt", "json"],
        metadata={"title": "Video"},
        full_text="Сәлем",
        timing_mode="approximate",
    )

    assert set(paths) == {"srt", "vtt", "txt", "json"}
    assert Path(paths["srt"]).read_text(encoding="utf-8").startswith("1\n00:00:00,000")
    assert Path(paths["vtt"]).read_text(encoding="utf-8").startswith("WEBVTT")
    payload = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    assert payload["language"] == "kk"
    assert payload["timing_mode"] == "approximate"


def test_transcribe_chunk_posts_openai_compatible_request(monkeypatch, tmp_path: Path):
    audio = tmp_path / "chunk.wav"
    audio.write_bytes(b"RIFFfake")
    response = Mock(status_code=200)
    response.json.return_value = {"text": "тест"}
    mock_post = Mock(return_value=response)
    monkeypatch.setattr(kk.requests, "post", mock_post)

    result = kk._transcribe_chunk(audio, api_key="secret", model="speech-to-text-kk")

    assert result == {"text": "тест"}
    _, kwargs = mock_post.call_args
    assert kwargs["headers"] == {"Authorization": "Bearer secret"}
    assert kwargs["data"] == {"model": "speech-to-text-kk"}
    assert kwargs["files"]["file"][0] == "chunk.wav"


def test_requirements_require_key_and_binaries(monkeypatch):
    monkeypatch.setattr(kk, "_api_key", lambda: "secret")
    monkeypatch.setattr(kk, "_has_binary", lambda name: name in {"yt-dlp", "ffmpeg", "ffprobe"})

    assert kk.check_kazakh_youtube_subtitles_requirements()
