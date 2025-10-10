import os
import re
from enum import Enum
from importlib.util import find_spec
from pathlib import Path
from platform import system as psys
from subprocess import PIPE, CalledProcessError, run
from time import time
from typing import Literal, Optional, Union

from langcodes import Language as Lang
from notifypy import Notify
from pydantic import BaseModel
from survey import printers

WEB_API_URL = "https://api.bilibili.tv/intl/gateway/web/v2"
BASE_DIR = Path("~/Bilibili").expanduser().resolve()
BASE_DIR.mkdir(exist_ok=True)
DEFAULT_COOKIES = BASE_DIR / "cookies.txt"
DEFAULT_HISTORY = BASE_DIR / "history.v2.tsv"
DEFAULT_WATCHLIST = BASE_DIR / "watchlist.txt"


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
    # Windows: < > : " / \ | ? *
    # Linux: / (and null character, but that's rare in strings)
    invalid_characters = r'[\\/:*?"<>|]'

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


class SubtitleLanguage(str, Enum):
    en = "en"
    id = "id"
    ms = "ms"
    th = "th"
    vi = "vi"
    zh_Hans = "zh-Hans"
    zh_Hant = "zh-Hant"


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


def check_package(pkg_name: str) -> bool:
    """
    Check if the required package is installed

    Args:
        pkg_name (str): the package name

    Returns:
        bool: True if the package is installed, False otherwise
    """
    return find_spec(pkg_name) is not None


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
        ins_notify.title = f"{title}, {index} downloaded"
        ins_notify.message = f"File is saved on {path.resolve()}"
    else:
        ins_notify.title = f"Downloading {title}, {index}"
        ins_notify.message = "We will notify you when it's done"
    try:
        ins_notify.send(block=False)
    except Exception as _:
        ...


def pluralize(n: Union[int, float], word: str, plural: Optional[str] = None) -> str:
    """
    Pluralize a word based on a count.

    Args:
        n (int | float): the count
        word (str): the word to pluralize
        plural (Optional[str], optional): the plural form of the word

    Returns:
        str: the pluralized word
    """
    if n == 1:
        return f"{n} {word}"
    if plural:
        return f"{n} {plural}"
    if word.endswith("y"):
        return f"{n} {word[:-1]}ies"
    elif word.endswith("s"):
        return f"{n} {word}es"
    return f"{n} {word}s"


def secs_to_proper(seconds: Union[int, float]) -> tuple[int, int, int, int, int]:
    """
    Convert seconds to proper time format.

    Args:
        seconds (int | float): the duration in seconds

    Returns:
        tuple[int, int, int, int, int]: the duration in days, hours, minutes, seconds, and milliseconds
    """
    days, hours, minutes, secs = (
        seconds // 86400,
        seconds // 3600 % 24,
        seconds // 60 % 60,
        seconds % 60,
    )
    mili = (seconds * 1000) % 1000
    return int(days), int(hours), int(minutes), int(secs), int(mili)


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
    d_, h_, m_, s_, _ = secs_to_proper(seconds)
    if m_ == 0:
        return f"0:{s_:02}"
    return f"{d_}:{h_:02}:{m_:02}:{s_:02}".lstrip("0:").lstrip("0")


def format_mkvmerge_time(seconds: float) -> str:
    """
    Formats a duration in seconds to a format that can be used by mkvmerge.

    Args:
        mili (float): the duration in seconds

    Returns:
        str: the formatted duration
    """
    _, h_, m_, s_, ms_ = secs_to_proper(seconds)
    return f"{h_:02}:{m_:02}:{s_:02}.{ms_:03}"


class BenchClock:
    """A simple class to measure the time taken to perform a task."""

    def __init__(self) -> None:
        self.start = time()
        self.stop_ = 0.0

    def stop(self) -> float:
        """Stop the clock and return the time taken."""
        self.stop_ = time() if not self.stop_ else self.stop_
        return self.stop_ - self.start

    def reset(self) -> None:
        """Reset the clock."""
        self.start = time()
        self.stop_ = 0.0

    @property
    def format(self) -> str:
        """Format the time taken to a human-readable format."""
        return format_human_time(self.stop())

    @property
    def detailed_format(self) -> str:
        """Format the time taken to a detailed human-readable format."""
        d_, h_, m_, s_, ms_ = secs_to_proper(self.stop())
        finals = []
        if d_:
            finals.append(pluralize(d_, "day", "days"))
        if h_:
            finals.append(pluralize(h_, "hour"))
        if m_:
            finals.append(pluralize(m_, "minute"))
        if s_:
            finals.append(pluralize(s_, "second"))
        if ms_:
            finals.append(pluralize(ms_, "millisecond"))

        # only last element should be connected with 'and', others with ','
        if len(finals) > 1:
            return ", ".join(finals[:-1]) + " and " + finals[-1]
        return finals[0]

    @property
    def format_mkvmerge(self) -> str:
        """Format the time taken to a mkvmerge-compatible format."""
        return format_mkvmerge_time(self.stop())

    def echo_format(self, ctx: str = "") -> None:
        """Print the formatted time taken."""
        if ctx:
            prn_done(f"{ctx}, task took {self.detailed_format} ({self.format})")
            return
        prn_done(f"Task took {self.detailed_format} ({self.format})")


def langcode_to_str(langcode: str) -> str:
    """Convert language codes into readable"""
    get_lang = Lang.get(langcode)
    english = get_lang.display_name("en")
    native = get_lang.display_name(langcode)
    if english == native:
        return english
    return f"{english} ({native})"


REINSTALL_ARGS = 'pipx install "bilidownloader[ass] @ git+https://github.com/nattadasu/bilidownloader.git"'
