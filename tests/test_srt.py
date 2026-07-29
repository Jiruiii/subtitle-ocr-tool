from subtitle_ocr.models import SubtitleEvent
from subtitle_ocr.srt import (
    clean_text,
    merge_events,
    parse_srt,
    safe_filename,
    srt_timestamp,
    write_outputs,
)


def test_clean_text_normalizes_cjk_spacing_and_false_positive_digit():
    assert clean_text("  台  灣\u200b ") == "台灣"
    assert clean_text("7") == ""


def test_srt_round_trip_and_consecutive_text_deduplication(tmp_path):
    events = [
        SubtitleEvent(0.0, 1.25, "第一句"),
        SubtitleEvent(1.25, 2.5, "第一句"),
        SubtitleEvent(2.5, 4.0, "第二句"),
    ]
    srt_path, txt_path = write_outputs(events, tmp_path)
    assert srt_timestamp(3661.234) == "01:01:01,234"
    assert parse_srt(srt_path) == [
        SubtitleEvent(0.0, 1.25, "第一句"),
        SubtitleEvent(1.25, 2.5, "第一句"),
        SubtitleEvent(2.5, 4.0, "第二句"),
    ]
    assert txt_path.read_text(encoding="utf-8") == "第一句\n第二句\n"


def test_merge_events_discards_invalid_events():
    events = [
        SubtitleEvent(0.0, 0.0, "invalid"),
        SubtitleEvent(0.0, 1.0, "有效"),
        SubtitleEvent(1.2, 2.0, "有效"),
    ]
    assert merge_events(events) == [SubtitleEvent(0.0, 2.0, "有效")]


def test_safe_filename_is_bounded_and_safe():
    result = safe_filename("這是一句/含有:危險字元 " * 5)
    assert len(result) <= 70
    assert "/" not in result
    assert ":" not in result
