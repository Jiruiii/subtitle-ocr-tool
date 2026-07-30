"""Set up subtitle-ocr-tool with the matching PaddlePaddle package."""

from __future__ import annotations

import argparse
import platform
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PADDLE_VERSION = "3.3.0"
PADDLE_INDEX = "https://www.paddlepaddle.org.cn/packages/stable"
SUPPORTED_CUDA = {
    (11, 8): "cu118",
    (12, 6): "cu126",
    (12, 9): "cu129",
    (13, 0): "cu130",
}


def parse_cuda_version(value: str) -> tuple[int, int] | None:
    """Parse an explicit CUDA version such as 12.6."""

    match = re.fullmatch(r"\s*(\d+)\.(\d+)\s*", value)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def detect_cuda_version() -> tuple[int, int] | None:
    """Read the CUDA version reported by NVIDIA's nvidia-smi command."""

    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is None:
        return None

    try:
        result = subprocess.run(
            [nvidia_smi],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None

    match = re.search(
        r"CUDA Version:\s*(\d+)\.(\d+)",
        f"{result.stdout}\n{result.stderr}",
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def select_cuda_channel(cuda_version: tuple[int, int]) -> str | None:
    """Select the newest supported channel not newer than the detected version."""

    candidates = [version for version in SUPPORTED_CUDA if version <= cuda_version]
    if not candidates:
        return None
    return SUPPORTED_CUDA[max(candidates)]


def format_cuda_version(cuda_version: tuple[int, int] | None) -> str:
    if cuda_version is None:
        return "未知"
    return f"{cuda_version[0]}.{cuda_version[1]}"


def choose_paddle_target(args: argparse.Namespace) -> tuple[str, str | None, str]:
    """Return kind, channel, and a user-facing explanation."""

    if args.cpu and args.cuda is not None:
        raise RuntimeError("--cpu 不能和 --cuda 一起使用。")

    explicit_cuda = parse_cuda_version(args.cuda) if args.cuda is not None else None
    if args.cuda is not None and explicit_cuda not in SUPPORTED_CUDA:
        supported = ", ".join(format_cuda_version(item) for item in SUPPORTED_CUDA)
        raise RuntimeError(f"目前腳本支援的 CUDA 版本為：{supported}。")

    if args.cpu:
        return "cpu", None, "已指定使用 CPU 版 PaddlePaddle。"

    if explicit_cuda is not None:
        return (
            "gpu",
            SUPPORTED_CUDA[explicit_cuda],
            (f"已指定 CUDA {format_cuda_version(explicit_cuda)}，使用 Paddle GPU 套件。"),
        )

    detected_cuda = detect_cuda_version()
    if detected_cuda is None:
        if args.gpu:
            raise RuntimeError(
                "--gpu 找不到可用的 nvidia-smi/CUDA；請改用 --cpu，或使用 --cuda 11.8 "
                "這類明確版本。"
            )
        return "cpu", None, "沒有偵測到 NVIDIA GPU，使用 CPU 版 PaddlePaddle。"

    channel = select_cuda_channel(detected_cuda)
    if channel is None:
        if args.gpu:
            raise RuntimeError(
                f"偵測到 CUDA {format_cuda_version(detected_cuda)}，但目前沒有可對應的官方 "
                "Paddle GPU 套件；請改用 --cpu。"
            )
        return (
            "cpu",
            None,
            (f"偵測到 CUDA {format_cuda_version(detected_cuda)}，沒有可對應的版本，改用 CPU 版。"),
        )

    selected_version = next(
        version
        for version, supported_channel in SUPPORTED_CUDA.items()
        if supported_channel == channel
    )
    if selected_version != detected_cuda:
        explanation = (
            f"偵測到 CUDA {format_cuda_version(detected_cuda)}，使用最近的官方套件頻道 {channel}。"
        )
    else:
        explanation = (
            f"偵測到 CUDA {format_cuda_version(detected_cuda)}，使用 GPU 版 PaddlePaddle。"
        )
    return "gpu", channel, explanation


def venv_python(venv_dir: Path) -> Path:
    if platform.system() == "Windows":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def run_command(command: list[str], *, dry_run: bool = False) -> int:
    print(f"\n$ {shlex.join(command)}")
    if dry_run:
        return 0
    try:
        completed = subprocess.run(command, cwd=ROOT, check=False)
    except OSError as exc:
        print(f"執行失敗：{exc}", file=sys.stderr)
        return 1
    return completed.returncode


def prepare_python(*, use_current: bool, dry_run: bool) -> Path:
    """Use an active venv, or create the repository's .venv automatically."""

    if use_current or sys.prefix != sys.base_prefix:
        return Path(sys.executable)

    venv_dir = ROOT / ".venv"
    python = venv_python(venv_dir)
    if not python.exists():
        print(f"建立虛擬環境：{venv_dir}")
        result = run_command(
            [sys.executable, "-m", "venv", str(venv_dir)],
            dry_run=dry_run,
        )
        if result != 0:
            raise RuntimeError("建立虛擬環境失敗。")
    if not dry_run and not python.exists():
        raise RuntimeError(f"找不到虛擬環境 Python：{python}")
    return python


def paddle_command(python: Path, kind: str, channel: str | None) -> list[str]:
    if kind == "cpu":
        return [
            str(python),
            "-m",
            "pip",
            "install",
            "--upgrade",
            f"paddlepaddle=={PADDLE_VERSION}",
        ]

    if channel is None:
        raise ValueError("GPU 安裝需要 CUDA channel。")
    return [
        str(python),
        "-m",
        "pip",
        "install",
        "--upgrade",
        f"paddlepaddle-gpu=={PADDLE_VERSION}",
        "-i",
        f"{PADDLE_INDEX}/{channel}/",
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="自動建立虛擬環境，並安裝適合目前環境的 PaddlePaddle 與 OCR 工具。"
    )
    device = parser.add_mutually_exclusive_group()
    device.add_argument("--cpu", action="store_true", help="強制安裝 CPU 版。")
    device.add_argument("--gpu", action="store_true", help="強制安裝 GPU 版。")
    parser.add_argument(
        "--cuda",
        metavar="VERSION",
        help="明確指定 CUDA 版本，例如 11.8；會使用對應的 GPU 套件。",
    )
    parser.add_argument(
        "--no-venv",
        action="store_true",
        help="不要建立 .venv，直接安裝到目前的 Python 環境。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只顯示將執行的安裝指令，不實際安裝。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        kind, channel, explanation = choose_paddle_target(args)
        python = prepare_python(use_current=args.no_venv, dry_run=args.dry_run)
    except RuntimeError as exc:
        print(f"安裝設定失敗：{exc}", file=sys.stderr)
        return 2

    print(explanation)
    if args.dry_run:
        print("\n這是 dry-run，只顯示指令，不會實際安裝。")

    commands = [
        [str(python), "-m", "pip", "install", "--upgrade", "pip"],
        paddle_command(python, kind, channel),
        [str(python), "-m", "pip", "install", "-e", ".[ocr]"],
    ]
    for command in commands:
        if run_command(command, dry_run=args.dry_run) != 0:
            print("安裝失敗，請查看上方 pip 錯誤訊息。", file=sys.stderr)
            return 1

    if not args.dry_run:
        verify_command = [
            str(python),
            "-c",
            "import paddle; print('PaddlePaddle', paddle.__version__); paddle.utils.run_check()",
        ]
        if run_command(verify_command) != 0:
            print("PaddlePaddle 驗證失敗；可以先用 python install.py --cpu 重試。", file=sys.stderr)
            return 1

        if shutil.which("ffmpeg") is None:
            print("\n提醒：找不到 ffmpeg。OCR 可以安裝完成，但輸出 WAV 前仍需安裝 ffmpeg。")

    executable = (
        ".venv\\Scripts\\subtitle-ocr.exe"
        if platform.system() == "Windows" and not args.no_venv
        else ".venv/bin/subtitle-ocr"
        if not args.no_venv
        else "subtitle-ocr"
    )
    if args.dry_run:
        print(
            f"\ndry-run 完成。實際安裝後可執行：{executable} ./video.mp4 --output-dir outputs/video"
        )
    else:
        print(f"\n安裝完成。執行範例：{executable} ./video.mp4 --output-dir outputs/video")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
