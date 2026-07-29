"""Data models shared by the command-line tools and Python API."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SubtitleEvent:
    """One subtitle line and the time range in which it is visible."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class PipelineConfig:
    """OCR sampling and subtitle-region settings."""

    lang: str = "chinese_cht"
    device: str | None = None
    interval: float = 0.35
    top: float = 0.84
    bottom: float = 0.99
    scale: float = 2.0
    stability: int = 3

    def __post_init__(self) -> None:
        if self.interval <= 0:
            raise ValueError("interval 必須大於 0")
        if self.scale <= 0:
            raise ValueError("scale 必須大於 0")
        if self.stability < 1:
            raise ValueError("stability 必須至少為 1")
        if not 0 <= self.top < self.bottom <= 1:
            raise ValueError("字幕區域必須符合 0 <= top < bottom <= 1")


@dataclass(frozen=True)
class PipelineResult:
    """Files and events produced by one OCR run."""

    video_path: Path
    output_dir: Path
    events: list[SubtitleEvent]
    srt_path: Path
    txt_path: Path
    wav_dir: Path | None
    wav_count: int
