import re
from enum import Enum
from importlib.util import find_spec
from time import time
from typing import Optional, Union

from langcodes import Language as Lang
from pydantic import BaseModel

from bilidownloader.commons.ui import prn_done


class DataExistError(Exception):
    """Exception raised when data already exists in the file."""


class RateLimitError(Exception):
    """Exception raised when Bilibili returns 412 Precondition Failed (Rate Limit)."""


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


class SubtitleLanguage(str, Enum):
    en = "en"
    id = "id"
    ms = "ms"
    th = "th"
    vi = "vi"
    zh_Hans = "zh-Hans"
    zh_Hant = "zh-Hant"


def check_package(pkg_name: str) -> bool:
    """
    Check if the required package is installed

    Args:
        pkg_name (str): the package name

    Returns:
        bool: True if the package is installed, False otherwise
    """
    return find_spec(pkg_name) is not None


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


def int_to_abc(number: int) -> str:
    """
    Convert integer to capital alphabet

    Args:
        number (int): Number to convert

    Returns:
        str: Alphabet
    """
    # if over 26, use base26 in A-Z:
    if number > 26:
        return int_to_abc((number - 1) // 26) + chr((number - 1) % 26 + ord("A"))
    return chr(number + ord("A") - 1)
