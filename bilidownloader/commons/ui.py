import os
import shlex
from io import StringIO
from pathlib import Path

from notifypy import Notify
from rich.console import Console
from rich.markup import escape
from rich.table import Table

ins_notify = Notify()
console = Console(highlight=False, emoji=False)
_verbose = False
_notification_disabled = os.getenv("DISPLAY") is None and os.name != "nt"


def is_headless() -> bool:
    """True when output must avoid ANSI colors/bars: rich's own terminal check.

    Nothing more — systemd env vars like INVOCATION_ID leak into desktop
    sessions, so they must not force headless mode on real terminals.
    """
    return not console.is_terminal


def print_table(table: Table, width: int = 70, indent: str = "       ") -> None:
    """Indented rich Table with color only on real terminals.

    A buffer is never a TTY, so color is forced explicitly in head mode
    (rich would otherwise strip it everywhere, not just in journals).
    """
    headless = is_headless()
    buf = StringIO()
    Console(
        file=buf,
        highlight=False,
        emoji=False,
        width=width,
        force_terminal=not headless,
        no_color=headless,
    ).print(table)
    for line in buf.getvalue().splitlines():
        if headless:
            print(f"{indent}{line}")
        else:
            console.print(f"{indent}{line}", markup=False)


def set_verbose(verbose: bool) -> None:
    """
    Set the verbose mode for debug messages.

    Args:
        verbose (bool): True to enable verbose mode, False to disable
    """
    global _verbose
    _verbose = verbose


def prn_info(message: str) -> None:
    """
    Prints an informational message to the console.

    Args:
        message (str): the informational message

    Returns:
        None

    Note:
        Uses rich for styled output with cyan color scheme.
    """
    console.print(f"[reverse cyan] INFO [/] {escape(message)}")


def prn_warn(message: str) -> None:
    """
    Prints a warn message to the console.

    Args:
        message (str): the warn message

    Returns:
        None

    Note:
        Uses rich for styled output with orange color scheme.
    """
    console.print(f"[reverse yellow] INFO [/] {escape(message)}")


def prn_done(message: str) -> None:
    """
    Prints a success message to the console.

    Args:
        message (str): the success message

    Returns:
        None

    Note:
        Uses rich for styled output with green color scheme.
    """
    console.print(f"[reverse green] DONE [/] {escape(message)}")


def prn_error(message: str) -> None:
    """
    Prints an error message to the console.

    Args:
        message (str): the error message

    Returns:
        None

    Note:
        Uses rich for styled output with red color scheme.
    """
    console.print(f"[reverse red] ERROR [/] {escape(message)}")


def prn_dbg(message: str) -> None:
    """
    Prints a debug message to the console only if verbose mode is enabled.

    Args:
        message (str): the debug message

    Returns:
        None

    Note:
        Uses rich for styled output with yellow color scheme.
        Only prints when verbose mode is enabled via set_verbose(True).
    """
    if _verbose:
        console.print(f"[reverse bright_black] DEBUG [/] [dim]{escape(message)}[/dim]")


def prn_cmd(command: list[str]) -> None:
    """
    Prints an external command that is about to be executed when verbose mode is enabled.

    Args:
        command (list[str]): the command and its arguments

    Returns:
        None

    Note:
        Uses rich for styled output with blue color scheme.
        Only prints when verbose mode is enabled via set_verbose(True).
        Formats the command as a shell-escaped string for readability.
    """
    if _verbose:
        cmd_str = " ".join(shlex.quote(str(arg)) for arg in command)
        console.print(f"[reverse bright_black] CMD [/] [dim]{escape(cmd_str)}[/dim]")


def push_notification(title: str, index: str, path: Path | None = None) -> None:
    """
    Send native notification for Windows, Linux, and macOS, exclusively used
    for episode download.

    Args:
        title (str): the title of the episode
        index (str): the episode index
        path (Optional[Path], optional): the path to the downloaded file

    Returns:
        None
    """
    if _notification_disabled:
        return
    ins_notify.application_name = "BiliDownloader"
    if path:
        ins_notify.title = f"{title}, {index} downloaded"
        ins_notify.message = f"File is saved on {path.resolve()}"
    else:
        ins_notify.title = f"Downloading {title}, {index}"
        ins_notify.message = "We will notify you when it's done"
    try:
        ins_notify.send(block=False)
    except Exception as _:
        ...
