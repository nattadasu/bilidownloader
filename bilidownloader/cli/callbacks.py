from pathlib import Path
from typing import Optional

import typer

from bilidownloader.constants import DEFAULT_COOKIES


def resolution_callback(user_input: int) -> int:
    from bilidownloader.cli.options import resos

    if user_input in resos:
        return user_input
    raise typer.BadParameter(f"Only following values were accepted: {resos}")


def resolution_autocomplete():
    from bilidownloader.cli.options import resos

    return resos


def raise_ffmpeg(path: Optional[Path]):
    if path is None:
        raise FileNotFoundError("ffmpeg binary couldn't be found!")


def raise_mkvpropedit(path: Optional[Path]):
    if path is None:
        raise FileNotFoundError("mkvpropedit binary couldn't be found!")


def raise_mkvmerge(path: Optional[Path]):
    if path is None:
        raise FileNotFoundError("mkvmerge binary couldn't be found!")


def raise_cookie(path: Optional[Path]):
    if path is None or not path.exists():
        raise FileNotFoundError(
            f"Cookie file not found at {path or DEFAULT_COOKIES}. "
            "Please create it or specify the path with --cookie."
        )
