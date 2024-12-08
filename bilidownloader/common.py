import os
import re
from pathlib import Path
from platform import system as psys
from subprocess import PIPE, CalledProcessError, run
from typing import Literal, Optional, Union

from notifypy import Notify
from pydantic import BaseModel
from survey import printers

API_URL = "https://api.bilibili.tv/intl/gateway/web/v2/anime/timeline?s_locale=en_US&platform=web"
DEFAULT_HISTORY = Path("~/Bilibili/history.txt").expanduser()
DEFAULT_WATCHLIST = Path("~/Bilibili/watchlist.txt").expanduser()


ins_notify = Notify()

class DataExistError(Exception):
    """Exception raised when data already exists in the file."""


class Chapter(BaseModel):
    start_time: float
    end_time: float
    title: str


def sanitize_filename(filename: str, replacement: str = "_") -> str:
    """
    Sanitize a string to be used as a filename by removing or replacing characters
    that are considered invalid in both Windows and Linux.
    """
    # Define a pattern for invalid characters on both Windows and Linux
    invalid_characters = r'[\/:*?"<>|]'

    # Replace invalid characters with the specified replacement
    sanitized_filename = re.sub(invalid_characters, replacement, filename)

    # Strip any trailing periods or spaces (Windows does not allow filenames ending with a space or a dot)
    sanitized_filename = sanitized_filename.rstrip(". ")

    return sanitized_filename


available_res = Union[
    Literal[144], Literal[240], Literal[360], Literal[480], Literal[720],
    Literal[1080], Literal[2160]
]
"""Available resolutions on Bstation, 4K was skipped"""


def _find_command(executable: str) -> Optional[Path]:
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
    return _find_command("ffmpeg")


def find_mkvpropedit() -> Optional[Path]:
    return _find_command("mkvpropedit")


def prn_info(message: str) -> None:
    """Prints an informational message to the console."""
    try:
        printers.info(message)
    except Exception as _:
        print(f"!> {message}")


def prn_done(message: str) -> None:
    """Prints a success message to the console."""
    try:
        printers.done(message)
    except Exception as _:
        print(f"O> {message}")


def prn_error(message: str) -> None:
    """Prints an error message to the console."""
    try:
        printers.fail(message)
    except Exception as _:
        print(f"X> {message}")

def push_notification(title: str, index: str, path: Path) -> None:
    """Send native notification for Windows, Linux, and macOS"""
    ins_notify.application_name = "BiliDownloader"
    ins_notify.title = f"{title}, E{index} downloaded"
    ins_notify.message = f"File is saved on {path.resolve()}"
    ins_notify.send(block=False)
