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
import sys
import time
from pathlib import Path
from typing import Iterable, List, Sequence

import typer
from rich.console import Console
from rich.table import Table

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
    else:
        console.print(
            f"[yellow][asr_quickstart] 未生成输出文件。请在 {input_dir} 提供样本后重试。[/yellow]"
        )

    console.print("[blue][asr_quickstart] 流程结束。[/blue]")


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point used by ``python asr_quickstart.py``."""

    argv = list(argv or sys.argv[1:])
    # ``typer`` treats ``python script.py`` as calling the default command.  To
    # keep the CLI explicit we redirect to the ``run`` command when the user does
    # not specify one.
    if not argv or argv[0].startswith("-"):
        argv = ["run", *argv]
    try:
        app(argv)
    except typer.Exit as exc:  # Typer raises typer.Exit for normal termination.
        return exc.exit_code
    return 0


if __name__ == "__main__":
    sys.exit(main())
