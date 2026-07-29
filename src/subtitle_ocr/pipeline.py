"""Core video download, OCR detection, and transcript generation logic."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .audio import extract_wav_segments
from .models import PipelineConfig, PipelineResult, SubtitleEvent
from .srt import clean_text, merge_events, write_outputs

VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}


def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def download_youtube(source: str, work_dir: Path, cookies: Path | None = None) -> Path:
    """Download one YouTube video and return its local path."""

    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise RuntimeError("找不到 yt-dlp；請先安裝工具依賴：python -m pip install -e .") from exc

    work_dir.mkdir(parents=True, exist_ok=True)
    options: dict[str, Any] = {
        # OpenCV cannot decode YouTube AV1 reliably, so prefer H.264/AVC.
        "format": (
            "bestvideo[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/"
            "best[ext=mp4][vcodec^=avc1]/"
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        ),
        "merge_output_format": "mp4",
        "outtmpl": str(work_dir / "video.%(ext)s"),
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
    }
    if cookies:
        options["cookiefile"] = str(cookies)

    print("下載影片中（只下載這支影片，不下載整個 playlist）……", flush=True)
    with YoutubeDL(options) as downloader:
        downloader.download([source])

    candidates = sorted(
        path
        for path in work_dir.glob("video.*")
        if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES
    )
    if not candidates:
        raise RuntimeError(f"影片下載完成但找不到影片檔：{work_dir}")
    return candidates[0]


def _result_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        payload: Any = result
    else:
        payload = getattr(result, "json", None)
        if callable(payload):
            payload = payload()
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return {}
    if not isinstance(payload, dict):
        return {}
    nested = payload.get("res")
    return nested if isinstance(nested, dict) else payload


def _box_coordinates(box: Any) -> tuple[float, float, float, float] | None:
    try:
        values = box.tolist() if hasattr(box, "tolist") else box
        if len(values) < 4:
            return None
        if isinstance(values[0], (list, tuple)):
            points = [(float(point[0]), float(point[1])) for point in values if len(point) >= 2]
            if not points:
                return None
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            return min(xs), min(ys), max(xs), max(ys)
        x1, y1, x2, y2 = (float(value) for value in values[:4])
        return x1, y1, x2, y2
    except (TypeError, ValueError, IndexError):
        return None


def result_text(
    result: Any,
    image_width: int | None = None,
    image_height: int | None = None,
) -> str:
    """Select the most likely centered subtitle line from a PaddleOCR result."""

    payload = _result_payload(result)
    texts = payload.get("rec_texts", [])
    boxes = payload.get("rec_boxes", [])
    if hasattr(texts, "tolist"):
        texts = texts.tolist()
    if hasattr(boxes, "tolist"):
        boxes = boxes.tolist()
    if not texts:
        return ""

    fallback = clean_text(" ".join(str(text) for text in texts if str(text).strip()))
    if not boxes or len(boxes) != len(texts) or not image_width:
        return fallback

    candidates: list[tuple[str, tuple[float, float, float, float], float, float]] = []
    for raw_text, raw_box in zip(texts, boxes):
        text = clean_text(str(raw_text))
        coordinates = _box_coordinates(raw_box)
        if not text or coordinates is None:
            continue
        x1, y1, x2, y2 = coordinates
        width = max(0.0, x2 - x1)
        center_x = (x1 + x2) / 2.0
        center_y = (y1 + y2) / 2.0
        if center_x < image_width * 0.25 or center_x > image_width * 0.75:
            continue
        if image_height and center_y < image_height * 0.15:
            continue
        candidates.append((text, coordinates, width, center_y))

    if not candidates:
        return ""
    anchor = max(candidates, key=lambda item: item[2])
    if anchor[2] < max(100.0, image_width * 0.05):
        return ""

    anchor_y = anchor[3]
    anchor_height = anchor[1][3] - anchor[1][1]
    selected = [
        item for item in candidates if abs(item[3] - anchor_y) <= max(30.0, anchor_height * 0.75)
    ]
    selected.sort(key=lambda item: item[1][0])
    return clean_text(" ".join(item[0] for item in selected))


def ocr_image(ocr: Any, image: Any) -> str:
    texts: list[str] = []
    for result in ocr.predict(image):
        text = result_text(result, image.shape[1], image.shape[0])
        if text:
            texts.append(text)
    return clean_text(" ".join(texts))


def detect_subtitles(
    video_path: Path,
    ocr: Any,
    config: PipelineConfig,
) -> list[SubtitleEvent]:
    """Sample a video and convert stable OCR observations into subtitle events."""

    import cv2

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"無法開啟影片：{video_path}")

    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = frame_count / fps if frame_count else 0.0
    step = max(1, round(fps * config.interval))

    events: list[SubtitleEvent] = []
    accepted_text = ""
    accepted_start: float | None = None
    candidate_text: str | None = None
    candidate_start: float | None = None
    candidate_count = 0
    last_sample_time = 0.0
    frame_index = 0

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index % step != 0:
                frame_index += 1
                continue

            timestamp = frame_index / fps
            last_sample_time = timestamp
            height, width = frame.shape[:2]
            y1 = max(0, min(height - 1, round(height * config.top)))
            y2 = max(y1 + 1, min(height, round(height * config.bottom)))
            subtitle_area = frame[y1:y2, 0:width]
            if config.scale != 1.0:
                subtitle_area = cv2.resize(
                    subtitle_area,
                    None,
                    fx=config.scale,
                    fy=config.scale,
                    interpolation=cv2.INTER_CUBIC,
                )

            observed = ocr_image(ocr, subtitle_area)
            if observed == candidate_text:
                candidate_count += 1
            else:
                candidate_text = observed
                candidate_start = timestamp
                candidate_count = 1

            if candidate_count >= config.stability and candidate_text != accepted_text:
                if accepted_text and accepted_start is not None:
                    end = candidate_start if candidate_start is not None else timestamp
                    if end > accepted_start:
                        events.append(SubtitleEvent(accepted_start, end, accepted_text))
                accepted_text = candidate_text or ""
                accepted_start = candidate_start if accepted_text else None

            frame_index += 1
            if frame_index % max(step * 20, 1) == 0 and duration:
                progress = min(100.0, timestamp / duration * 100.0)
                print(f"OCR 進度：{progress:5.1f}%", end="\r", flush=True)
    finally:
        capture.release()

    print(" " * 40, end="\r")
    if accepted_text and accepted_start is not None:
        end = max(last_sample_time + config.interval, accepted_start + 0.1)
        events.append(SubtitleEvent(accepted_start, end, accepted_text))
    return merge_events(events)


def create_ocr(config: PipelineConfig) -> Any:
    """Create the PaddleOCR engine lazily so TXT/SRT utilities need no OCR install."""

    try:
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise RuntimeError(
            "找不到 PaddleOCR/PaddlePaddle；請先依 README 安裝相容的 PaddlePaddle，"
            "再執行：python -m pip install -e '.[ocr]'"
        ) from exc

    options: dict[str, Any] = {
        "lang": config.lang,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
    }
    if config.device:
        options["device"] = config.device
    print("載入 PaddleOCR 模型中……第一次執行可能需要下載模型。", flush=True)
    return PaddleOCR(**options)


def _resolve_video(
    source: str | Path,
    output_dir: Path,
    cookies: Path | None,
) -> tuple[Path, bool]:
    source_text = str(source)
    if is_url(source_text):
        return download_youtube(source_text, output_dir / "download", cookies), True

    video_path = Path(source).expanduser().resolve()
    if not video_path.is_file():
        raise FileNotFoundError(f"找不到影片：{video_path}")
    if video_path.suffix.lower() not in VIDEO_SUFFIXES:
        raise ValueError(f"不支援的影片副檔名：{video_path.suffix or '(無副檔名)'}")
    return video_path, False


def _cleanup_download(output_dir: Path) -> None:
    download_dir = output_dir / "download"
    for path in download_dir.glob("video.*"):
        path.unlink(missing_ok=True)
    try:
        download_dir.rmdir()
    except OSError:
        pass


def run_pipeline(
    source: str | Path,
    output_dir: str | Path,
    config: PipelineConfig | None = None,
    cookies: str | Path | None = None,
    no_wav: bool = False,
    keep_download: bool = False,
    ocr: Any | None = None,
) -> PipelineResult:
    """Run the complete download → OCR → SRT/TXT → WAV pipeline."""

    config = config or PipelineConfig()
    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    cookies_path = Path(cookies).expanduser().resolve() if cookies else None
    if cookies_path and not cookies_path.is_file():
        raise FileNotFoundError(f"找不到 cookies 檔案：{cookies_path}")

    video_path: Path | None = None
    downloaded = False
    try:
        video_path, downloaded = _resolve_video(source, output_path, cookies_path)
        ocr_engine = ocr if ocr is not None else create_ocr(config)
        events = detect_subtitles(video_path, ocr_engine, config)
        srt_path, txt_path = write_outputs(events, output_path)

        wav_dir: Path | None = None
        wav_count = 0
        if not no_wav:
            wav_dir = output_path / "wav"
            wav_count = extract_wav_segments(video_path, events, wav_dir)

        return PipelineResult(
            video_path=video_path,
            output_dir=output_path,
            events=events,
            srt_path=srt_path,
            txt_path=txt_path,
            wav_dir=wav_dir,
            wav_count=wav_count,
        )
    finally:
        if downloaded and not keep_download:
            _cleanup_download(output_path)
