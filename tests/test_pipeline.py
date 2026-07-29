import pytest

from subtitle_ocr.models import PipelineConfig
from subtitle_ocr.pipeline import result_text


def test_pipeline_config_validates_sampling_region():
    with pytest.raises(ValueError):
        PipelineConfig(top=0.9, bottom=0.8)
    with pytest.raises(ValueError):
        PipelineConfig(interval=0)


def test_result_text_prefers_centered_wide_text():
    result = {
        "rec_texts": ["左側小字", "畫面字幕", "右側小字"],
        "rec_boxes": [
            [0, 40, 180, 60],
            [180, 40, 820, 70],
            [820, 40, 1000, 60],
        ],
    }
    assert result_text(result, image_width=1000, image_height=100) == "畫面字幕"


def test_result_text_supports_nested_paddle_payload():
    result = {
        "res": {
            "rec_texts": ["字幕"],
            "rec_boxes": [[100, 50, 900, 80]],
        }
    }
    assert result_text(result, image_width=1000, image_height=100) == "字幕"
