"""Batch command for YouTube playlists, URL files, or multiple sources."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import unicodedata
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_playlist_url(value: str) -> bool:
    parsed = urlparse(value)
    query = parse_qs(parsed.query)
    return parsed.path.rstrip("/").endswith("/playlist") or ("list" in query and "v" not in query)


def safe_name(value: str, fallback: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = re.sub(r"[^\w\u3400-\u9fff-]+", "_", value, flags=re.UNICODE)
    value = re.sub(r"_+", "_", value).strip("._-")
    return (value or fallback)[:100]


def _youtube_downloader(cookies: Path | None = None) -> Any:
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise RuntimeError("找不到 yt-dlp；請先安裝工具依賴：python -m pip install -e .") from exc

    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
    }
    if cookies:
        options["cookiefile"] = str(cookies)
    return YoutubeDL(options)


def read_video_info(url: str, cookies: Path | None = None) -> tuple[str, str]:
    with _youtube_downloader(cookies) as downloader:
        info = downloader.extract_info(url, download=False)
    video_id = str(info.get("id") or "video")
    title = str(info.get("title") or video_id)
    return video_id, title


def read_playlist_urls(url: str, cookies: Path | None = None) -> list[str]:
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise RuntimeError("找不到 yt-dlp；請先安裝工具依賴：python -m pip install -e .") from exc

    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "noplaylist": False,
        "skip_download": True,
    }
    if cookies:
        options["cookiefile"] = str(cookies)
    with YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=False)

    entries = info.get("entries") or []
    result: list[str] = []
    for entry in entries:
        if not entry:
            continue
        video_id = entry.get("id")
        if video_id:
            result.append(f"https://www.youtube.com/watch?v={video_id}")
    return result


def load_sources(
    sources: Sequence[str],
    url_file: Path | None,
    cookies: Path | None,
    skip_latest: int,
) -> list[str]:
    raw_sources = list(sources)
    if url_file:
        raw_sources.extend(
            line.strip()
            for line in url_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    if not raw_sources:
        raise ValueError("請提供 YouTube URL、本地影片路徑，或使用 --url-file sources.txt")

    expanded: list[str] = []
    seen: set[str] = set()
    for source in raw_sources:
        if is_playlist_url(source):
            playlist_sources = read_playlist_urls(source, cookies)
            skip = max(0, skip_latest)
            print(
                f"播放清單共找到 {len(playlist_sources)} 支影片，"
                f"跳過最前面的 {min(skip, len(playlist_sources))} 支。"
            )
            playlist_sources = playlist_sources[skip:]
        else:
            playlist_sources = [source]
        for item in playlist_sources:
            if item not in seen:
                expanded.append(item)
                seen.add(item)

    if not expanded:
        raise ValueError("沒有可處理的影片")
    return expanded


def has_complete_output(output_dir: Path, no_wav: bool) -> bool:
    transcripts_ready = (output_dir / "transcript.txt").is_file() and (
        output_dir / "transcript.srt"
    ).is_file()
    if no_wav:
        return transcripts_ready
    return transcripts_ready and any((output_dir / "wav").glob("*.wav"))


def output_dir_for(source: str, output_root: Path, cookies: Path | None) -> Path:
    if is_url(source):
        video_id, title = read_video_info(source, cookies)
        return output_root / safe_name(f"{video_id}_{title}", video_id)
    path = Path(source).expanduser()
    return output_root / safe_name(path.stem, "video")


def process_source(
    number: int,
    total: int,
    source: str,
    args: argparse.Namespace,
    output_root: Path,
) -> dict[str, str]:
    try:
        output_dir = output_dir_for(source, output_root, args.cookies)
        if has_complete_output(output_dir, args.no_wav) and not args.force:
            print(f"[{number}/{total}] 已完成，略過：{source}", flush=True)
            return {"status": "skipped", "source": source}

        print(f"\n[{number}/{total}] 開始：{source}", flush=True)
        print(f"輸出資料夾：{output_dir}", flush=True)
        command = [
            sys.executable,
            "-m",
            "subtitle_ocr",
            source,
            "--output-dir",
            str(output_dir),
            "--interval",
            str(args.interval),
            "--stability",
            str(args.stability),
            "--top",
            str(args.top),
            "--bottom",
            str(args.bottom),
            "--scale",
            str(args.scale),
        ]
        if args.lang:
            command.extend(["--lang", args.lang])
        if args.device:
            command.extend(["--device", args.device])
        if args.cookies:
            command.extend(["--cookies", str(args.cookies)])
        if args.no_wav:
            command.append("--no-wav")
        if args.keep_download:
            command.append("--keep-download")

        result = subprocess.run(command, check=False)
        if result.returncode:
            return {
                "status": "failed",
                "source": source,
                "error": f"子程序返回碼 {result.returncode}",
            }
        return {"status": "done", "source": source}
    except Exception as exc:  # noqa: BLE001 - report one failure and continue.
        return {"status": "failed", "source": source, "error": str(exc)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="subtitle-ocr-batch",
        description="批次處理 YouTube URL、播放清單、URL 檔案或本地影片。",
    )
    parser.add_argument("sources", nargs="*", help="一個或多個 URL 或本地影片路徑")
    parser.add_argument("--url-file", type=Path, help="每行一個 URL/影片路徑的檔案")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("outputs"),
        help="所有影片的輸出根目錄，預設 outputs",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="同時處理的影片數，預設 1；GPU/記憶體不足時請維持 1",
    )
    parser.add_argument(
        "--skip-latest",
        type=int,
        default=0,
        help="播放清單跳過最前面的影片數，預設 0",
    )
    parser.add_argument("--cookies", type=Path, help="YouTube cookies.txt 路徑")
    parser.add_argument("--device", help="例如 cpu 或 gpu:0")
    parser.add_argument("--lang", default="chinese_cht", help="PaddleOCR 語言")
    parser.add_argument("--interval", type=float, default=0.35)
    parser.add_argument("--stability", type=int, default=3)
    parser.add_argument("--top", type=float, default=0.84)
    parser.add_argument("--bottom", type=float, default=0.99)
    parser.add_argument("--scale", type=float, default=2.0)
    parser.add_argument("--force", action="store_true", help="已有結果時仍重新辨識")
    parser.add_argument("--no-wav", action="store_true", help="只輸出 TXT/SRT")
    parser.add_argument("--keep-download", action="store_true", help="保留下載的影片檔")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.workers < 1:
        print("錯誤：--workers 必須至少為 1", file=sys.stderr)
        return 2
    if args.cookies:
        args.cookies = args.cookies.expanduser().resolve()
        if not args.cookies.is_file():
            print(f"錯誤：找不到 cookies 檔案：{args.cookies}", file=sys.stderr)
            return 2
    try:
        sources = load_sources(args.sources, args.url_file, args.cookies, args.skip_latest)
        output_root = args.output_root.expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1

    print(f"最多同時處理 {args.workers} 支影片。", flush=True)
    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(
                process_source,
                number,
                len(sources),
                source,
                args,
                output_root,
            )
            for number, source in enumerate(sources, start=1)
        ]
        for future in as_completed(futures):
            result = future.result()
            if result["status"] == "failed":
                failures += 1
                print(
                    f"處理失敗：{result['source']}\n{result.get('error', '')}",
                    file=sys.stderr,
                    flush=True,
                )
            elif result["status"] == "done":
                print(f"完成：{result['source']}", flush=True)

    if failures:
        print(f"完成，但有 {failures} 支影片失敗。", file=sys.stderr)
        return 1
    print(f"全部完成。逐字稿根目錄：{output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
