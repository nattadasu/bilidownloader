"""Font management utilities for BiliDownloader.

This module provides functionality to download and manage fonts used in subtitle
processing, particularly for ASS/SSA subtitle files. It handles font discovery,
downloading, and lookup operations for yt-dlp integration.
"""

from json import loads as jloads
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple, TypedDict

from bilidownloader.commons.constants import BASE_DIR
from bilidownloader.commons.ui import prn_error, prn_info


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
ARIAL_URI: str = "https://cdn.jsdelivr.net/npm/@canvas-fonts/arial"

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
    "Arial": {
        "url": f"{ARIAL_URI}@1.0.4/Arial.ttf",
        "path": BASE_DIR / "fonts" / "arial.ttf",
    },
    "Arial::Bold": {
        "url": f"{ARIAL_URI}-bold@1.0.4/Arial%20Bold.ttf",
        "path": BASE_DIR / "fonts" / "arial-bold.ttf",
    },
    "Arial::Italic": {
        "url": f"{ARIAL_URI}-italic@1.0.4/Arial%20Italic.ttf",
        "path": BASE_DIR / "fonts" / "arial-italic.ttf",
    },
    "Arial::Bold Italic": {
        "url": f"{ARIAL_URI}-bold-italic@1.0.4/Arial%20Bold%20Italic.ttf",
        "path": BASE_DIR / "fonts" / "arial-bold-italic.ttf",
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
        declared_size: Optional[int] = (
            int(raw_size) if raw_size and raw_size.isdigit() else None
        )

        downloaded_bytes: int = 0
        chunk_size: int = 8192  # Larger chunk size for better performance

        with (
            open(path, "wb") as file,
            alive_bar(
                declared_size, title=f"Downloading {font_family}", unit="B", scale="IEC"
            ) as bar,
        ):
            for data in response.iter_content(chunk_size=chunk_size):
                if not data:  # End of stream
                    break
                bytes_written: int = file.write(data)
                downloaded_bytes += bytes_written

                # Let alive-progress handle overruns if content-length is wrong
                bar(bytes_written)

        prn_info(
            f"Font '{font_family}' downloaded successfully to {path} ({downloaded_bytes:,} bytes)."
        )

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


def loop_font_lookup(font_json: Path, font_args: List[str]) -> Tuple[Path, List[str]]:
    """Process fonts from a JSON file and add them to font arguments list.

    This function reads a JSON file containing a list of font names, resolves
    their file paths (either from NATIVE_FONTS or system fonts), and adds
    appropriate yt-dlp attachment arguments for each found font.

    Args:
        font_json: Path to the JSON file containing the list of font names.
        font_args: List of command-line arguments to append font attachments to.

    Returns:
        A tuple containing the original font_json path and the updated font_args list.

    Note:
        The function prioritizes NATIVE_FONTS over system fonts and gracefully
        handles missing files or parsing errors.
    """
    # Load font list from JSON file
    try:
        fonts: List[str] = jloads(font_json.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        prn_error(f"Failed to read or parse font JSON file '{font_json}': {e}")
        fonts = []

    if not fonts:
        return font_json, font_args

    # Import FindSystemFontsFilename for system font lookup
    try:
        from find_system_fonts_filename import get_system_fonts_filename
    except ImportError:
        prn_error(
            "FindSystemFontsFilename is required for font lookup but not installed."
        )
        return font_json, font_args

    # Build a cache of system fonts for faster lookup
    system_fonts_cache = _build_system_fonts_cache(get_system_fonts_filename)

    prn_info(f"Detected {len(fonts)} font(s) used in subtitles, attaching to file")

    found_fonts = 0
    for font_name in fonts:
        font_path: Optional[Path] = None

        # First, check if it's a native font we manage
        font_path = _resolve_native_font(font_name)

        # If not found in native fonts, try system font lookup
        if not font_path:
            font_path = _resolve_system_font(font_name, system_fonts_cache)

        # Add to arguments if font was found and file exists
        if font_path and font_path.exists():
            font_args.extend(
                [
                    "--attachment-name",
                    font_path.name,
                    "--add-attachment",
                    str(font_path),
                ]
            )
            found_fonts += 1
            prn_info(f"  - {font_name} ({font_path.name})")
        else:
            prn_error(f"  - Font '{font_name}' not found or file does not exist.")

    if found_fonts > 0:
        prn_info(f"Successfully attached {found_fonts} font(s) to the file")

    return font_json, font_args


def _resolve_native_font(font_name: str) -> Optional[Path]:
    """Resolve a font name to a path from NATIVE_FONTS.

    Args:
        font_name: The name of the font to resolve.

    Returns:
        Path to the native font file if found, None otherwise.
    """
    # Check for exact match first
    if font_name in NATIVE_FONTS:
        return NATIVE_FONTS[font_name]["path"]

    return None


def _build_system_fonts_cache(
    system_fonts_filename: Callable[[], Set[str]],
) -> Dict[str, Path]:
    """Build a cache mapping font names to their file paths.

    Args:
        system_fonts_filename: Function that returns paths to system fonts.

    Returns:
        Dictionary mapping lowercase font family names to font file paths.
    """
    font_cache: Dict[str, Path] = {}

    try:
        from fontTools import ttLib
    except ImportError:
        prn_error("fontTools is required for font name extraction but not installed.")
        return font_cache

    for font_path_str in system_fonts_filename():
        font_path = Path(font_path_str)
        if not font_path.exists():
            continue

        try:
            # Extract font family name from the font file
            font = ttLib.TTFont(font_path, fontNumber=0)
            name_table = font.get("name")
            if name_table:
                # Try to get the font family name (Name ID 1)
                for record in name_table.names:  # type: ignore
                    if record.nameID == 1:  # Font Family name
                        family_name = record.toUnicode().strip()
                        # Store with lowercase key for case-insensitive lookup
                        font_cache[family_name.lower()] = font_path
                        break
            font.close()
        except Exception:
            # If we can't read the font, skip it silently
            continue

    return font_cache


def _resolve_system_font(font_name: str, font_cache: Dict[str, Path]) -> Optional[Path]:
    """Resolve a font name to a system font path using font cache.

    Args:
        font_name: The name of the font to resolve.
        font_cache: Dictionary mapping font names to paths.

    Returns:
        Path to the system font file if found, None otherwise.
    """
    # Try case-insensitive lookup
    font_path = font_cache.get(font_name.lower())

    if font_path and font_path.exists():
        return font_path

    return None
