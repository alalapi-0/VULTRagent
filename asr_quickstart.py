"""Simple non-interactive ASR entry point.

This module provides a placeholder implementation that can be deployed to the
remote host.  It scans an input directory for audio-like files, generates a
minimal pseudo transcript, and stores the results in the configured output
folder.  The goal is to provide a working default that passes the entry-file
check performed during deployment while leaving clear extension points for a
real ASR pipeline.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, List, Sequence

import typer
from typer.main import get_command
from rich.console import Console
from rich.table import Table


os.environ.setdefault("LANG", "C.UTF-8")
os.environ.setdefault("LC_ALL", "C.UTF-8")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = typer.Typer(add_completion=False, help="Placeholder ASR pipeline.")

console = Console()


# Define a set of common audio file extensions.  The script still accepts all
# files but will highlight the ones that match these extensions.
_AUDIO_EXTENSIONS: Sequence[str] = (
    ".wav",
    ".mp3",
    ".flac",
    ".ogg",
    ".m4a",
    ".aac",
    ".wma",
)


def _iter_input_files(input_dir: Path) -> Iterable[Path]:
    """Yield files contained in *input_dir* recursively, ordered by name."""

    if not input_dir.exists():
        return []

    files: List[Path] = []
    for path in input_dir.rglob("*"):
        if path.is_file():
            files.append(path)
    files.sort()
    return files


def _describe_inputs(files: Sequence[Path]) -> None:
    """Pretty-print a summary table for the collected *files*."""

    if not files:
        console.print("[yellow]未在输入目录中发现文件，脚本将生成空结果。[/yellow]")
        return

    table = Table(title="输入文件摘要")
    table.add_column("序号", justify="right")
    table.add_column("文件名")
    table.add_column("音频格式", justify="center")

    for idx, file_path in enumerate(files, start=1):
        suffix = file_path.suffix.lower()
        is_audio = suffix in _AUDIO_EXTENSIONS
        table.add_row(
            str(idx),
            str(file_path),
            "✅" if is_audio else "-",
        )

    console.print(table)


class AudioPreparationError(RuntimeError):
    """Raised when preprocessing audio inputs fails."""


def _maybe_transcode_input(input_path: Path) -> Path:
    """Ensure *input_path* is a WAV file ready for downstream processing."""

    if not input_path.exists():
        # If the user explicitly pointed to a file (has suffix) but it is
        # missing, raise an informative error.  Otherwise, defer to the main
        # pipeline which already handles missing directories gracefully.
        if input_path.suffix:
            raise AudioPreparationError(
                f"音频路径不存在或无法访问：{input_path}"
            )
        return input_path

    if input_path.is_dir():
        return input_path

    if not os.access(input_path, os.R_OK):
        raise AudioPreparationError(f"音频路径不存在或无法访问：{input_path}")

    if input_path.suffix.lower() == ".wav":
        return input_path

    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin is None:
        raise AudioPreparationError("ffmpeg not found or audio decode failed")

    output_path = Path("/tmp") / f"{input_path.stem}_16k.wav"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(input_path),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        "-acodec",
        "pcm_s16le",
        str(output_path),
    ]

    logger.info("检测到非 WAV 输入，使用 ffmpeg 转码：%s", " ".join(cmd))
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            check=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise AudioPreparationError("ffmpeg not found or audio decode failed") from exc
    except subprocess.CalledProcessError as exc:
        logger.error("ffmpeg 转码失败：%s", exc.stderr)
        raise AudioPreparationError("ffmpeg not found or audio decode failed") from exc

    if completed.stderr:
        logger.debug("ffmpeg stderr: %s", completed.stderr)

    if not output_path.exists():
        raise AudioPreparationError("ffmpeg not found or audio decode failed")

    logger.info("音频已转码为 16 kHz 单声道 WAV：%s", output_path)
    return output_path


def _prepare_audio_arguments(argv: Sequence[str]) -> List[str]:
    """Apply preprocessing (transcoding) to the ``--input`` argument if needed."""

    args = list(argv)
    input_arg_index: int | None = None
    value_index: int | None = None
    raw_value: str | None = None

    for idx, arg in enumerate(args):
        if arg == "--input":
            if idx + 1 < len(args):
                input_arg_index = idx
                value_index = idx + 1
                raw_value = args[value_index]
            break
        if arg.startswith("--input="):
            input_arg_index = idx
            raw_value = arg.split("=", 1)[1]
            break

    if not raw_value:
        return args

    try:
        input_path = Path(raw_value).expanduser()
        transcoded_path = _maybe_transcode_input(input_path)
    except AudioPreparationError:
        raise
    except Exception as exc:  # Catch unexpected edge cases for logging clarity.
        raise AudioPreparationError(
            f"音频路径处理失败：{raw_value}"
        ) from exc

    if transcoded_path == input_path:
        return args

    new_value = str(transcoded_path)
    if value_index is not None:
        args[value_index] = new_value
    elif input_arg_index is not None:
        args[input_arg_index] = f"--input={new_value}"

    logger.info("命令行参数已更新，后续流程将使用：%s", new_value)
    return args


@app.command("run")
def run(
    input_dir: Path = typer.Option(
        Path("./inputs"),
        "--input",
        help="目录路径，包含待识别的音频或媒体文件。",
    ),
    output_dir: Path = typer.Option(
        Path("./outputs"),
        "--output",
        "--out-dir",
        help="目录路径，用于存放识别结果。",
    ),
    models_dir: Path = typer.Option(
        Path("./models"),
        "--models-dir",
        help="模型缓存目录（占位参数，便于后续扩展）。",
    ),
    model: str = typer.Option(
        "base",
        "--model",
        help="使用的模型名称，仅用于记录日志。",
    ),
) -> None:
    """Execute the placeholder ASR pipeline."""

    console.print("[blue][asr_quickstart] 启动占位 ASR 流程。[/blue]")
    console.print(f"[blue][asr_quickstart] 输入目录: {input_dir}[/blue]")
    console.print(f"[blue][asr_quickstart] 输出目录: {output_dir}[/blue]")
    console.print(f"[blue][asr_quickstart] 模型目录: {models_dir}[/blue]")
    console.print(f"[blue][asr_quickstart] 选用模型: {model}[/blue]")

    input_dir = input_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    models_dir = models_dir.expanduser().resolve()

    # Ensure the directories exist.
    if not input_dir.exists():
        console.print(
            f"[yellow][asr_quickstart] 输入目录 {input_dir} 不存在，稍后将生成空结果。[/yellow]"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)

    files = list(_iter_input_files(input_dir))
    _describe_inputs(files)

    results = []
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for file_path in files:
        relative = file_path.relative_to(input_dir)
        transcript = {
            "source": str(file_path),
            "relative_path": str(relative),
            "generated_at": timestamp,
            "model": model,
            "transcript": (
                "(placeholder) 请在此处集成真实的 ASR 推理逻辑后生成文本。"
            ),
        }
        output_file = output_dir / f"{relative.with_suffix('')}.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with output_file.open("w", encoding="utf-8") as fh:
            json.dump(transcript, fh, ensure_ascii=False, indent=2)
        results.append((relative, output_file))

    manifest_path = output_dir / "_manifest.txt"
    with manifest_path.open("w", encoding="utf-8") as manifest:
        for relative, output_file in results:
            size = output_file.stat().st_size
            manifest.write(f"{size}\t{relative.with_suffix('.json')}\n")

    if results:
        console.print(
            f"[green][asr_quickstart] 已生成 {len(results)} 个占位结果，详情见 {output_dir}。[/green]"
        )
        for relative, output_file in results:
            console.print(
                f"[green]  ↳ {relative.with_suffix('.json')} ({output_file.stat().st_size} bytes)[/green]"
            )
    else:
        console.print(
            f"[yellow][asr_quickstart] 未生成输出文件。请在 {input_dir} 提供样本后重试。[/yellow]"
        )

    console.print("[blue][asr_quickstart] 流程结束。[/blue]")


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point used by ``python asr_quickstart.py``."""

    argv = list(argv or sys.argv[1:])
    # 兼容 ``python asr_quickstart.py run`` 与 ``python asr_quickstart.py`` 的两种写法。
    if argv[:1] == ["run"]:
        argv = argv[1:]

    command = get_command(app)
    try:
        argv = _prepare_audio_arguments(argv)
        command.main(
            args=argv,
            prog_name="asr_quickstart.py",
            standalone_mode=False,
        )
    except AudioPreparationError as exc:
        logger.exception("ASR pipeline failed during audio preparation")
        print(f"音频处理失败：{exc}", file=sys.stderr)
        return 1
    except typer.Exit as exc:  # Typer raises typer.Exit for normal termination.
        return exc.exit_code
    except Exception:
        logger.exception("ASR pipeline failed")
        print("ASR 流程执行失败，请检查日志和输入参数。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
