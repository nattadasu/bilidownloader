import os
import shlex
from pathlib import Path
from typing import Optional

from notifypy import Notify
from rich.console import Console

ins_notify = Notify()
console = Console(highlight=False)
_verbose = False
_notification_disabled = os.getenv("DISPLAY") is None and os.name != "nt"


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
    console.print(f"[reverse cyan] INFO [/] {message}")


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
    console.print(f"[reverse green] DONE [/] {message}")


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
    console.print(f"[reverse red] ERROR [/] {message}")


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
        console.print(f"[reverse yellow] DEBUG [/] [dim]{message}[/dim]")


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
        console.print(f"[reverse blue] CMD [/] [dim]{cmd_str}[/dim]")


def push_notification(title: str, index: str, path: Optional[Path] = None) -> None:
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
