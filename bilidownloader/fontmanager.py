"""Font management utilities for BiliDownloader.

This module provides functionality to download and manage fonts used in subtitle
processing, particularly for ASS/SSA subtitle files. It handles font discovery,
downloading, and lookup operations for yt-dlp integration.
"""

from json import loads as jloads
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from typing import TypedDict

from bilidownloader.common import BASE_DIR, prn_error, prn_info


class FontInfo(TypedDict):
    """Type definition for font information.

    Attributes:
        url: The URL where the font can be downloaded from.
        path: The local file system path where the font should be stored.
    """

    url: str
    path: Path


# Base URI for Noto Sans font files hosted on jsdelivr CDN
NOTO_URI: str = "https://cdn.jsdelivr.net/gh/notofonts/notofonts.github.io/fonts/NotoSans/full/variable-ttf"

# Dictionary mapping font names to their download URLs and local storage paths
NATIVE_FONTS: Dict[str, FontInfo] = {
    "Noto Sans": {
        "url": f"{NOTO_URI}/NotoSans[wdth,wght].ttf",
        "path": BASE_DIR / "fonts" / "noto-sans.ttf",
    },
    "Noto Sans::Italic": {
        "url": f"{NOTO_URI}/NotoSans-Italic[wdth,wght].ttf",
        "path": BASE_DIR / "fonts" / "noto-sans-italic.ttf",
    },
}


def download_fonts(font_family: str) -> None:
    """Download a specific font family if it doesn't already exist locally.

    Args:
        font_family: The name of the font family to download (must be in NATIVE_FONTS).

    Returns:
        None

    Raises:
        No exceptions are raised; errors are logged via prn_error().
    """
    font_info: Optional[FontInfo] = NATIVE_FONTS.get(font_family)
    if not font_info:
        prn_error(f"Font '{font_family}' not found in NATIVE_FONTS.")
        return

    url: str = font_info["url"]
    path: Path = font_info["path"].absolute()

    # Skip download if font already exists
    if path.exists():
        return

    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    # Import required libraries for downloading
    try:
        import requests
        from alive_progress import alive_bar
    except ImportError:
        prn_error(
            "Required libraries for downloading fonts are not installed. "
            "Please install 'requests' and 'alive-progress'."
        )
        return

    # Download the font with progress bar
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()

        # Get content length but don't trust it completely for CDN responses
        raw_size: Optional[str] = response.headers.get("content-length", None)
        declared_size: Optional[int] = int(raw_size) if raw_size and raw_size.isdigit() else None
        
        downloaded_bytes: int = 0
        chunk_size: int = 8192  # Larger chunk size for better performance

        with (
            open(path, "wb") as file,
            alive_bar(
                declared_size, 
                title=f"Downloading {font_family}", 
                unit="B", 
                scale="IEC"
            ) as bar,
        ):
            for data in response.iter_content(chunk_size=chunk_size):
                if not data:  # End of stream
                    break
                bytes_written: int = file.write(data)
                downloaded_bytes += bytes_written
                
                # Let alive-progress handle overruns if content-length is wrong
                bar(bytes_written)

        prn_info(f"Font '{font_family}' downloaded successfully to {path} ({downloaded_bytes:,} bytes).")

    except requests.RequestException as e:
        prn_error(f"Failed to download font '{font_family}': {e}")
    except OSError as e:
        prn_error(f"Failed to write font file '{font_family}': {e}")
    except Exception as e:
        prn_error(f"Unexpected error downloading font '{font_family}': {e}")


def initialize_fonts() -> None:
    """Download all fonts defined in NATIVE_FONTS to the local config directory.

    This function iterates through all font families defined in NATIVE_FONTS
    and ensures they are downloaded and available locally. It's typically called
    during application initialization to ensure required fonts are available.

    Returns:
        None
    """
    for font_family in NATIVE_FONTS.keys():
        download_fonts(font_family)


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
