"""Rich-based progress reporting with binary (1024-based) byte units.

Replaces alive-progress throughout the codebase. Rendering is disabled
when headless (see commons.ui.is_headless), so journals stay clean.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich import filesize
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    ProgressColumn,
    Task,
    Text,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from bilidownloader.commons.ui import console, is_headless

_BINARY_SUFFIXES = ["bytes", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB"]


def format_binary_size(size: float | None) -> str:
    """Format a byte count with binary (1024-based) units."""
    if size is None:
        return "?"
    size = int(size)
    if size < 1024:
        return f"{size} bytes"
    unit, suffix = filesize.pick_unit_and_suffix(size, _BINARY_SUFFIXES, 1024)
    precision = 0 if unit == 1 else 1
    return f"{size / unit:,.{precision}f} {suffix}"


class BinarySpeedColumn(ProgressColumn):
    """Transfer speed with binary units (rich's own column is decimal-only)."""

    def render(self, task: Task) -> Text:
        speed = task.finished_speed or task.speed
        if speed is None:
            return Text("?", style="progress.data.speed")
        unit, suffix = filesize.pick_unit_and_suffix(int(speed), _BINARY_SUFFIXES, 1024)
        precision = 0 if unit == 1 else 1
        return Text(
            f"{speed / unit:,.{precision}f} {suffix}/s", style="progress.data.speed"
        )


def make_progress() -> Progress:
    """Progress with binary-byte columns; no-op rendering when headless."""
    return Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        DownloadColumn(binary_units=True),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        BinarySpeedColumn(),
        TimeRemainingColumn(),
        TimeElapsedColumn(),
        console=console,
        disable=is_headless(),
    )


class YtDlpProgress:
    """yt-dlp progress_hooks reporter: one rich task per filename."""

    def __init__(
        self, describe: Callable[[str, dict | None], str] | None = None
    ) -> None:
        from bilidownloader.commons.ui import prn_info

        self._prn_info = prn_info
        self._describe = describe or (lambda name, _: Path(name).name[:45])
        self._progress = make_progress()
        self._tasks: dict[str, Any] = {}
        self._started = False

    def _ensure_started(self) -> None:
        if not self._started:
            self._progress.start()
            self._started = True

    def hook(self, d: dict[str, Any]) -> None:
        status = d.get("status")
        filename = d.get("filename", "")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if filename not in self._tasks:
                try:
                    desc = self._describe(filename, d.get("info_dict"))
                except Exception:
                    desc = Path(filename).name[:45]
                if is_headless():
                    self._prn_info(f"Downloading {desc} ...")
                    self._tasks[filename] = None
                    return
                self._ensure_started()
                self._tasks[filename] = self._progress.add_task(
                    f"Downloading {desc}", total=total
                )
                return
            task_id = self._tasks[filename]
            if task_id is None:
                return
            self._progress.update(
                task_id,
                completed=d.get("downloaded_bytes", 0) or 0,
                total=total or None,
            )
        elif status == "finished":
            task_id = self._tasks.pop(filename, None)
            if task_id is not None:
                total = self._progress.tasks[task_id].total
                if total:
                    self._progress.update(task_id, completed=total)
                self._progress.stop_task(task_id)
            total_bytes = d.get("total_bytes") or d.get("downloaded_bytes")
            size = f" ({format_binary_size(total_bytes)})" if total_bytes else ""
            self._prn_info(f"Download completed: {Path(filename).name}{size}")
        elif status == "error":
            task_id = self._tasks.pop(filename, None)
            if task_id is not None:
                self._progress.stop_task(task_id)

    def close(self) -> None:
        if self._started:
            self._progress.stop()
            self._started = False
