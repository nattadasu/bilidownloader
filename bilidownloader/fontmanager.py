from json import loads as jloads
from pathlib import Path
from typing import List


def loop_font_lookup(font_json: Path, font_args: List[str]) -> tuple[Path, List[str]]:
    """
    Loop through the fonts in the font json file and add them to the font_args list

    Args:
        font_json (Path): Path to the font json file
        font_args (List[str]): List of font_args

    """
    try:
        fonts: List[str] = jloads(font_json.read_text(encoding="utf-8"))
    except Exception as _:
        fonts: List[str] = []

    from matplotlib import font_manager as fontm

    for font in fonts:
        try:
            fpath = fontm.findfont(
                fontm.FontProperties(family=font),
                fallback_to_default=False,
                rebuild_if_missing=False,
            )
            if fpath:
                # fmt: off
                font_args += [
                    "--attachment-name", font,
                    "--add-attachment", str(Path(fpath).absolute()),
                ]
                # fmt: on
        except Exception as _:
            continue

    return font_json, font_args
