"""Command-line entry point for one video."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .models import PipelineConfig
from .pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="subtitle-ocr",
        description="使用 PaddleOCR 讀取影片中的燒錄字幕並輸出 SRT/TXT/WAV。",
    )
    parser.add_argument("source", help="YouTube URL 或本地影片路徑")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs"),
        help="輸出目錄，預設 outputs",
    )
    parser.add_argument(
        "--lang",
        default="chinese_cht",
        help="PaddleOCR 語言，預設 chinese_cht",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="例如 cpu 或 gpu:0；省略時交給 PaddleOCR 自動選擇",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.35,
        help="每幾秒辨識一次，預設 0.35",
    )
    parser.add_argument(
        "--top",
        type=float,
        default=0.84,
        help="字幕區域上緣比例，預設 0.84",
    )
    parser.add_argument(
        "--bottom",
        type=float,
        default=0.99,
        help="字幕區域下緣比例，預設 0.99",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=2.0,
        help="字幕影像放大倍數，預設 2",
    )
    parser.add_argument(
        "--stability",
        type=int,
        default=3,
        help="連續幾次相同才採用，預設 3",
    )
    parser.add_argument(
        "--cookies",
        type=Path,
        help="YouTube cookies.txt 路徑；只有需要登入驗證時才需要",
    )
    parser.add_argument(
        "--no-wav",
        action="store_true",
        help="只輸出 TXT/SRT，不切 WAV",
    )
    parser.add_argument(
        "--keep-download",
        action="store_true",
        help="來源是 URL 時保留下載的影片檔",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = PipelineConfig(
            lang=args.lang,
            device=args.device,
            interval=args.interval,
            top=args.top,
            bottom=args.bottom,
            scale=args.scale,
            stability=args.stability,
        )
        result = run_pipeline(
            source=args.source,
            output_dir=args.output_dir,
            config=config,
            cookies=args.cookies,
            no_wav=args.no_wav,
            keep_download=args.keep_download,
        )
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        return 130
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1

    print(f"完成：{len(result.events)} 段字幕")
    print(f"SRT：{result.srt_path}")
    print(f"純文字：{result.txt_path}")
    if result.wav_dir is not None:
        print(f"WAV：{result.wav_dir}（{result.wav_count} 個）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
