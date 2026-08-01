from pathlib import Path

from bilidownloader.commons.constants import DEFAULT_COOKIES


def raise_ffmpeg(path: Path | None):
    if path is None:
        raise FileNotFoundError("ffmpeg binary couldn't be found!")


def raise_mkvpropedit(path: Path | None):
    if path is None:
        raise FileNotFoundError("mkvpropedit binary couldn't be found!")


def raise_mkvmerge(path: Path | None):
    if path is None:
        raise FileNotFoundError("mkvmerge binary couldn't be found!")


def raise_cookie(path: Path | None):
    if path is None or not path.exists():
        raise FileNotFoundError(
            f"Cookie file not found at {path or DEFAULT_COOKIES}. "
            "Please create it or specify the path with --cookie."
        )
