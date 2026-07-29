"""Audio download and subtitle-aligned WAV extraction."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from .models import SubtitleEvent
from .srt import safe_filename, srt_timestamp


def extract_wav_segments(
    video_path: Path,
    events: list[SubtitleEvent],
    wav_dir: Path,
) -> int:
    """Extract one 16 kHz mono PCM WAV file for each subtitle event."""

    wav_dir.mkdir(parents=True, exist_ok=True)
    if not events:
        return 0

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("找不到 ffmpeg；請先安裝 ffmpeg，或使用 --no-wav 只輸出 SRT/TXT。")

    count = 0
    for index, event in enumerate(events, start=1):
        start = max(0.0, event.start)
        duration = max(0.1, event.end - event.start)
        stamp = srt_timestamp(start).replace(":", "-").replace(",", "_")
        filename = f"{index:04d}_{stamp}_{safe_filename(event.text)}.wav"
        output_path = wav_dir / filename
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(video_path),
            "-t",
            f"{duration:.3f}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
        try:
            subprocess.run(command, check=True)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"ffmpeg 無法切出第 {index} 段 WAV：{output_path}") from exc
        count += 1
        if count % 50 == 0 or count == len(events):
            print(f"WAV 進度：{count}/{len(events)}", flush=True)
    return count


def download_audio(
    source: str,
    audio_dir: Path,
    cookies: Path | None = None,
) -> Path:
    """Download only the audio stream for the SRT-to-WAV helper."""

    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise RuntimeError("找不到 yt-dlp；請先安裝工具依賴：python -m pip install -e .") from exc

    audio_dir.mkdir(parents=True, exist_ok=True)
    options: dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": str(audio_dir / "audio.%(ext)s"),
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
    }
    if cookies:
        options["cookiefile"] = str(cookies)

    with YoutubeDL(options) as downloader:
        downloader.download([source])

    candidates = sorted(path for path in audio_dir.glob("audio.*") if path.is_file())
    if not candidates:
        raise RuntimeError(f"找不到下載的音訊檔：{audio_dir}")
    return candidates[0]
