"""Subtitle text cleanup and SRT input/output helpers."""

from __future__ import annotations

import re
import shutil
import unicodedata
from pathlib import Path

from .models import SubtitleEvent

TIMESTAMP = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+"
    r"(?P<end>\d{2}:\d{2}:\d{2},\d{3})"
)


def clean_text(text: str) -> str:
    """Normalize OCR whitespace and remove invisible characters."""

    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u200b", "")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", text)
    # A lone digit is usually a frame counter or a false positive from the
    # bottom edge of a video rather than a subtitle.
    if len(text) == 1 and text.isdigit():
        return ""
    return text


def safe_filename(text: str, fallback: str = "subtitle") -> str:
    """Turn subtitle text into a filesystem-safe, bounded filename part."""

    text = clean_text(text)
    text = re.sub(r"[^\w㐀-鿿-]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"_+", "_", text).strip("._-")
    return (text or fallback)[:70]


def parse_timestamp(value: str) -> float:
    hours, minutes, rest = value.split(":")
    seconds, milliseconds = rest.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(milliseconds) / 1000


def srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def parse_srt(path: Path) -> list[SubtitleEvent]:
    """Read subtitle events from a standard SRT file."""

    events: list[SubtitleEvent] = []
    content = path.read_text(encoding="utf-8-sig").strip()
    if not content:
        return events

    for block in re.split(r"\n\s*\n", content):
        lines = block.splitlines()
        match = next((candidate for line in lines if (candidate := TIMESTAMP.search(line))), None)
        if not match:
            continue
        timestamp_index = next(i for i, line in enumerate(lines) if TIMESTAMP.search(line))
        text = clean_text(
            " ".join(line.strip() for line in lines[timestamp_index + 1 :] if line.strip())
        )
        if not text:
            continue
        start = parse_timestamp(match.group("start"))
        end = parse_timestamp(match.group("end"))
        if end > start:
            events.append(SubtitleEvent(start, end, text))
    return events


def merge_events(events: list[SubtitleEvent]) -> list[SubtitleEvent]:
    """Drop invalid events and join adjacent repeated subtitle text."""

    merged: list[SubtitleEvent] = []
    for event in events:
        text = clean_text(event.text)
        if not text or event.end <= event.start:
            continue
        if merged and merged[-1].text == text and event.start <= merged[-1].end + 0.5:
            merged[-1].end = event.end
        else:
            merged.append(SubtitleEvent(event.start, event.end, text))
    return merged


def write_outputs(events: list[SubtitleEvent], output_dir: Path) -> tuple[Path, Path]:
    """Write ``transcript.srt`` and consecutive-deduplicated ``transcript.txt``."""

    output_dir.mkdir(parents=True, exist_ok=True)
    srt_path = output_dir / "transcript.srt"
    txt_path = output_dir / "transcript.txt"

    with srt_path.open("w", encoding="utf-8") as srt:
        for index, event in enumerate(events, start=1):
            srt.write(
                f"{index}\n"
                f"{srt_timestamp(event.start)} --> {srt_timestamp(event.end)}\n"
                f"{event.text}\n\n"
            )

    with txt_path.open("w", encoding="utf-8") as txt:
        previous: str | None = None
        for event in events:
            if event.text != previous:
                txt.write(event.text + "\n")
                previous = event.text
    return srt_path, txt_path


def copy_transcript_files(srt_path: Path, txt_path: Path, output_dir: Path) -> tuple[Path, Path]:
    """Copy existing transcript files into a WAV-only output directory."""

    output_dir.mkdir(parents=True, exist_ok=True)
    target_srt = output_dir / "transcript.srt"
    target_txt = output_dir / "transcript.txt"
    shutil.copy2(srt_path, target_srt)
    shutil.copy2(txt_path, target_txt)
    return target_srt, target_txt
