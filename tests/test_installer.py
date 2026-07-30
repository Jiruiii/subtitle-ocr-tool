from pathlib import Path

from install import SUPPORTED_CUDA, build_parser, paddle_command, select_cuda_channel


def test_select_cuda_channel_uses_nearest_supported_version() -> None:
    assert select_cuda_channel((12, 8)) == "cu126"
    assert select_cuda_channel((13, 0)) == "cu130"


def test_select_cuda_channel_returns_none_for_old_cuda() -> None:
    assert select_cuda_channel((11, 7)) is None


def test_gpu_command_uses_official_channel() -> None:
    command = paddle_command(Path("python"), "gpu", "cu126")
    assert "paddlepaddle-gpu==3.3.0" in command
    assert "https://www.paddlepaddle.org.cn/packages/stable/cu126/" in command


def test_parser_supports_simple_overrides() -> None:
    args = build_parser().parse_args(["--gpu", "--cuda", "11.8"])
    assert args.gpu is True
    assert args.cuda == "11.8"
    assert SUPPORTED_CUDA[(11, 8)] == "cu118"
