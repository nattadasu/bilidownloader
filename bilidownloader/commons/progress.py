"""Rich progress with binary (1024-based) byte units; silent when headless."""

import re
import subprocess as sp
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich import filesize
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    ProgressColumn,
    SpinnerColumn,
    Task,
    Text,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from bilidownloader.commons.ui import console, is_headless, prn_cmd, prn_dbg

_BINARY_SUFFIXES = ["bytes", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB"]
_PROGRESS_RE = re.compile(r"progress:.*?(\d+)\s*%", re.IGNORECASE)


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


DOWN_BADGE = "[reverse #875faf] DOWN [/]"
"""Leading badge block for download rows (muted violet; plain "purple" is neon)."""


def make_progress(badge: str | None = None) -> Progress:
    """Progress with binary-byte columns; no-op rendering when headless.

    When badge is given, it leads each row as its own column, e.g. download
    rows read `[ DOWN ] ⠋ Video (144P) ━━━ …`.
    """
    columns: list[ProgressColumn] = []
    if badge:
        columns.append(TextColumn(badge))
    columns.extend(
        [
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            DownloadColumn(binary_units=True),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            BinarySpeedColumn(),
            TimeRemainingColumn(),
            TimeElapsedColumn(),
        ]
    )
    return Progress(
        *columns,
        console=console,
        transient=True,
        disable=is_headless(),
    )


def run_with_progress(cmd: list[str], description: str) -> sp.CompletedProcess[str]:
    """Run an mkvmerge/mkvpropedit command under a percentage bar.

    The command always runs verbose so progress lines can be parsed; other
    output goes to debug logs. Piped output is enough, no TTY needed.
    """
    full_cmd = [*cmd, "--verbose"]
    prn_cmd(full_cmd)
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
        transient=True,
        disable=is_headless(),
    )
    output: list[str] = []
    with progress:
        task_id = progress.add_task(description, total=100)
        proc = sp.Popen(
            full_cmd, stdout=sp.PIPE, stderr=sp.STDOUT, text=True, bufsize=1
        )
        assert proc.stdout is not None
        for raw in proc.stdout:
            for part in raw.replace("\r", "\n").split("\n"):
                line = part.strip()
                if not line:
                    continue
                if matches := _PROGRESS_RE.findall(line):
                    progress.update(task_id, completed=int(matches[-1]))
                else:
                    output.append(line)
                    prn_dbg(line)
        proc.stdout.close()
        returncode = proc.wait()
        progress.update(task_id, completed=100)
    if returncode != 0:
        raise sp.CalledProcessError(returncode, full_cmd, output="\n".join(output))
    return sp.CompletedProcess(full_cmd, returncode, stdout="\n".join(output))


class YtDlpProgress:
    """One rich task per media track; transient_exts tasks are purged as a
    group when video/audio start instead of lingering."""

    def __init__(
        self,
        describe: Callable[[str, dict | None], str] | None = None,
        transient_exts: frozenset[str] | None = None,
    ) -> None:
        from bilidownloader.commons.ui import prn_info

        self._prn_info = prn_info
        self._describe = describe or (lambda name, _: Path(name).name[:45])
        self._transient_exts = transient_exts or frozenset()
        self._progress = make_progress(badge=DOWN_BADGE)
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
        """Task title, markup-escaped so odd names can't break bar rendering."""
        from rich.markup import escape

        try:
            desc = self._describe(filename, info_dict)
        except Exception:
            desc = Path(filename).name[:45]
        return escape(desc)

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
            # Transient rows are kept for the group purge at video/audio start.
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

    def suspend(self) -> None:
        """Stop live rendering while keeping tasks (e.g. before remuxing)."""
        if self._started:
            self._progress.stop()
            self._started = False

    def close(self) -> None:
        self._purge_transients()
        self.suspend()
