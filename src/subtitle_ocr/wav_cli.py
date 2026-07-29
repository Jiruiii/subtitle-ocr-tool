"""CLI for generating WAV files from an existing SRT."""

from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from .audio import download_audio, extract_wav_segments
from .pipeline import is_url
from .srt import copy_transcript_files, parse_srt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="subtitle-ocr-wav",
        description="使用既有 SRT/TXT 產生逐句 WAV，不重新執行 OCR。",
    )
    parser.add_argument("source", help="本地影片/音訊路徑或 YouTube URL")
    parser.add_argument("--srt", type=Path, required=True, help="既有的 SRT 檔案")
    parser.add_argument("--txt", type=Path, required=True, help="既有的 TXT 檔案")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cookies", type=Path, help="YouTube cookies.txt 路徑")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    srt_path = args.srt.expanduser().resolve()
    txt_path = args.txt.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    if not srt_path.is_file() or not txt_path.is_file():
        print("錯誤：找不到既有的 SRT/TXT 檔案", file=sys.stderr)
        return 2
    if args.cookies:
        args.cookies = args.cookies.expanduser().resolve()
        if not args.cookies.is_file():
            print(f"錯誤：找不到 cookies 檔案：{args.cookies}", file=sys.stderr)
            return 2

    temporary_audio_dir = output_dir / "_audio_download"
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        copy_transcript_files(srt_path, txt_path, output_dir)
        events = parse_srt(srt_path)
        if is_url(args.source):
            audio_path = download_audio(args.source, temporary_audio_dir, args.cookies)
        else:
            audio_path = Path(args.source).expanduser().resolve()
            if not audio_path.is_file():
                raise FileNotFoundError(f"找不到來源檔案：{audio_path}")
        count = extract_wav_segments(audio_path, events, output_dir / "wav")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1
    finally:
        if temporary_audio_dir.is_dir():
            shutil.rmtree(temporary_audio_dir)

    print(f"完成：{count} 個 WAV")
    print(f"輸出：{output_dir / 'wav'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
