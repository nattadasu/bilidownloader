import re
from pathlib import Path
from typing import Literal, Union

from pydantic import BaseModel

API_URL = "https://api.bilibili.tv/intl/gateway/web/v2/anime/timeline?s_locale=en_US&platform=web"
DEFAULT_HISTORY = Path("~/Bilibili/history.txt").expanduser()
DEFAULT_WATCHLIST = Path("~/Bilibili/watchlist.txt").expanduser()


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
    Literal[144], Literal[240], Literal[360], Literal[480], Literal[720], Literal[1080]
]
"""Available resolutions on Bstation, 4K was skipped"""
