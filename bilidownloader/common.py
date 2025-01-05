import os
import re
from datetime import timedelta
from pathlib import Path
from platform import system as psys
from subprocess import PIPE, CalledProcessError, run
from typing import Literal, Optional, Union

from notifypy import Notify
from pydantic import BaseModel
from survey import printers

WEB_API_URL = "https://api.bilibili.tv/intl/gateway/web/v2"
DEFAULT_HISTORY = Path("~/Bilibili/history.txt").expanduser()
DEFAULT_WATCHLIST = Path("~/Bilibili/watchlist.txt").expanduser()


ins_notify = Notify()


class DataExistError(Exception):
    """Exception raised when data already exists in the file."""


class Chapter(BaseModel):
    """Chapter model for Bilibili videos."""

    start_time: float
    """Start time of the chapter in seconds."""
    end_time: float
    """End time of the chapter in seconds."""
    title: str
    """Title of the chapter."""


def sanitize_filename(filename: str, replacement: str = "_") -> str:
    """
    Sanitize a string to be used as a filename by removing or replacing characters
    that are considered invalid in both Windows and Linux.

    Args:
        filename (str): the filename to sanitize
        replacement (str, optional): the replacement for invalid characters

    Returns:
        str: the sanitized filename
    """
    # Define a pattern for invalid characters on both Windows and Linux
    invalid_characters = r'[\/:*?"<>|]'

    # Replace invalid characters with the specified replacement
    sanitized_filename = re.sub(invalid_characters, replacement, filename)

    # Strip any trailing periods or spaces (Windows does not allow filenames ending with a space or a dot)
    sanitized_filename = sanitized_filename.rstrip(". ")

    return sanitized_filename


available_res = Union[
    Literal[144],
    Literal[240],
    Literal[360],
    Literal[480],
    Literal[720],
    Literal[1080],
    Literal[2160],
]
"""Available resolutions on Bstation, 4K was skipped"""


def find_command(executable: str) -> Optional[Path]:
    """
    Find the path to an executable in the system.

    Args:
        executable (str): the name of the executable to find

    Returns:
        Optional[Path]: the path to the executable, or None if not found
    """
    system = psys()
    command = "where" if system == "Windows" else "which"

    try:
        # Run the command and capture the output
        result = run([command, executable], check=True, stdout=PIPE, stderr=PIPE)
        # Decode the output to get the path
        exe_path = result.stdout.decode().strip()

        if os.path.isfile(exe_path):
            return Path(exe_path)
        else:
            return None
    except CalledProcessError:
        return None


def find_ffmpeg() -> Optional[Path]:
    """
    Find the ffmpeg executable in the system.

    Returns:
        Optional[Path]: the path to the ffmpeg executable, or None if not found
    """
    return find_command("ffmpeg")


def find_mkvpropedit() -> Optional[Path]:
    """
    Find the mkvpropedit executable in the system.

    Returns:
        Optional[Path]: the path to the mkvpropedit executable, or None if not found
    """
    return find_command("mkvpropedit")


def prn_info(message: str) -> None:
    """
    Prints an informational message to the console.

    Args:
        message (str): the informational message

    Returns:
        None

    Note:
        If the program is running headless, the message will be printed
        using the built-in print function as a fallback. The default behavior
        may raises fatal error if the program is running on a headless
        environment.
    """
    try:
        printers.info(message)
    except Exception as _:
        print(f"!> {message}")


def prn_done(message: str) -> None:
    """
    Prints a success message to the console.

    Args:
        message (str): the success message

    Returns:
        None

    Note:
        If the program is running headless, the message will be printed
        using the built-in print function as a fallback. The default behavior
        may raises fatal error if the program is running on a headless
    """
    try:
        printers.done(message)
    except Exception as _:
        print(f"O> {message}")


def prn_error(message: str) -> None:
    """
    Prints an error message to the console.

    Args:
        message (str): the error message

    Returns:
        None

    Note:
        If the program is running headless, the message will be printed
        using the built-in print function as a fallback. The default behavior
        may raises fatal error if the program is running on a headless
        environment.
    """
    try:
        printers.fail(message)
    except Exception as _:
        print(f"X> {message}")


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
    ins_notify.application_name = "BiliDownloader"
    if path:
        ins_notify.title = f"{title}, E{index} downloaded"
        ins_notify.message = f"File is saved on {path.resolve()}"
    else:
        ins_notify.title = f"Downloading {title}, E{index}"
        ins_notify.message = "We will notify you when it's done"
    ins_notify.send(block=False)


def format_human_time(seconds: float) -> str:
    """
    Formats a duration in seconds to a human-readable format.

    Args:
        seconds (float): the duration in seconds

    Returns:
        str: the formatted duration
    """
    if seconds < 0:
        return "N/A"
    elif seconds == 0:
        return "0:00"
    delta = timedelta(seconds=seconds)
    days, hours, minutes, secs = (
        delta.days,
        delta.seconds // 3600,
        delta.seconds // 60 % 60,
        delta.seconds % 60,
    )
    if minutes == 0:
        return f"0:{secs:02}"
    return f"{days:02}:{hours:02}:{minutes:02}:{secs:02}".lstrip("0:").lstrip("0")
