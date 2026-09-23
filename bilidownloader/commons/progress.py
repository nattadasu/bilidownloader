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
    """yt-dlp progress_hooks reporter: one rich task per media track.

    Files whose extension is in transient_exts (e.g. subtitles) keep their
    tasks only for their own phase: the whole group is removed (unhooked) at
    once when the video/audio download starts, instead of lingering.
    """

    def __init__(
        self,
        describe: Callable[[str, dict | None], str] | None = None,
        transient_exts: frozenset[str] | None = None,
    ) -> None:
        from bilidownloader.commons.ui import prn_info

        self._prn_info = prn_info
        self._describe = describe or (lambda name, _: Path(name).name[:45])
        self._transient_exts = transient_exts or frozenset()
        self._progress = make_progress()
        self._tasks: dict[str, Any] = {}
        self._started = False

    def _ensure_started(self) -> None:
        if not self._started:
            self._progress.start()
            self._started = True

    def _is_transient(self, filename: str) -> bool:
        return Path(filename).suffix.lower() in self._transient_exts

    def _purge_transients(self) -> None:
        """Remove all transient task rows, e.g. before video/audio start."""
        for filename in [fn for fn in self._tasks if self._is_transient(fn)]:
            task_id = self._tasks.pop(filename)
            if task_id is not None:
                self._progress.remove_task(task_id)

    def _label(self, filename: str, info_dict: dict | None) -> str:
        """Badge-style task title, e.g. `[ DOWN ] Video (144P)` (soft violet block)."""
        from rich.markup import escape

        try:
            desc = self._describe(filename, info_dict)
        except Exception:
            desc = Path(filename).name[:45]
        # Muted violet (#875faf = xterm 97): plain "purple" is neon (129).
        return f"[reverse #875faf] DOWN [/] {escape(desc)}"

    def _plain_label(self, filename: str, info_dict: dict | None) -> str:
        """Unstyled task title for headless logs."""
        try:
            return self._describe(filename, info_dict)
        except Exception:
            return Path(filename).name[:45]

    def hook(self, d: dict[str, Any]) -> None:
        status = d.get("status")
        filename = d.get("filename", "")
        info_dict = d.get("info_dict")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if filename not in self._tasks:
                if is_headless():
                    self._prn_info(
                        f"Downloading {self._plain_label(filename, info_dict)} ..."
                    )
                    self._tasks[filename] = None
                    return
                if not self._is_transient(filename):
                    self._purge_transients()
                self._ensure_started()
                self._tasks[filename] = self._progress.add_task(
                    self._label(filename, info_dict), total=total
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
            # Transient rows are kept (not popped) so the whole subtitle
            # group can be purged at once when video/audio start.
            task_id = (
                self._tasks.get(filename)
                if self._is_transient(filename)
                else self._tasks.pop(filename, None)
            )
            if task_id is not None:
                done = d.get("downloaded_bytes") or d.get("total_bytes")
                if done:
                    self._progress.update(task_id, completed=done)
                self._progress.stop_task(task_id)
            total_bytes = d.get("total_bytes") or d.get("downloaded_bytes")
            size = f" ({format_binary_size(total_bytes)})" if total_bytes else ""
            self._prn_info(f"Download completed: {Path(filename).name}{size}")
        elif status == "error":
            task_id = self._tasks.pop(filename, None)
            if task_id is not None:
                self._progress.stop_task(task_id)

    def close(self) -> None:
        self._purge_transients()
        if self._started:
            self._progress.stop()
            self._started = False
