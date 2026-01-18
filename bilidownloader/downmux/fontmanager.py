"""Font management utilities for BiliDownloader.

This module provides functionality to download and manage fonts used in subtitle
processing, particularly for ASS/SSA subtitle files. It handles font discovery,
downloading, and lookup operations for yt-dlp integration.
"""

import json
from json import loads as jloads
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple, TypedDict

from bilidownloader.commons.constants import BASE_DIR
from bilidownloader.commons.ui import prn_dbg, prn_error, prn_info


class FontInfo(TypedDict):
    """Type definition for font information.

    Attributes:
        url: The URL where the font can be downloaded from.
        path: The local file system path where the font should be stored.
    """

    url: str
    path: Path


class FontCache:
    """Manages font cache with incremental updates."""

    def __init__(self, cache_file: Path):
        """Initialize FontCache.

        Args:
            cache_file: Path to the cache file.
        """
        self.cache_file = cache_file
        # Store mappings as {font_path: {family_name, full_name, subfamily_name}}
        self._path_to_names: Dict[str, Dict[str, str]] = {}
        # Reverse lookup: {name_lower: font_path}
        self._name_to_path: Dict[str, Path] = {}

    def load(self) -> bool:
        """Load font cache from disk.

        Returns:
            True if cache was loaded successfully, False otherwise.
        """
        if not self.cache_file.exists():
            prn_dbg("Font cache file not found, will build new cache")
            return False

        try:
            prn_dbg(f"Loading font cache from {self.cache_file}")
            with open(self.cache_file, "r", encoding="utf-8") as f:
                cache_data = json.load(f)

            # Load path_to_names mappings
            self._path_to_names = cache_data.get("fonts", {})

            # Rebuild reverse lookup
            self._build_reverse_lookup()

            return True
        except Exception as e:
            prn_dbg(f"Failed to load font cache: {e}, will rebuild")
            return False

    def save(self) -> None:
        """Save font cache to disk."""
        try:
            # Ensure directory exists
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)

            # Store as {font_path: {family, full_name, subfamily}}
            cache_data = {"fonts": self._path_to_names}

            prn_dbg(f"Saving font cache to {self.cache_file}")
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f)

            prn_dbg(f"Font cache saved with {len(self._path_to_names)} font files")
        except Exception as e:
            prn_error(f"Failed to save font cache: {e}")

    def _build_reverse_lookup(self) -> None:
        """Build reverse lookup dictionary from path_to_names."""
        self._name_to_path = {}

        for font_path_str, names in self._path_to_names.items():
            font_path = Path(font_path_str)
            family = names.get("family", "")
            full_name = names.get("full_name", "")
            subfamily = names.get("subfamily", "")

            # Store by full name (highest priority - includes Bold/Italic)
            if full_name:
                key = full_name.lower()
                if key not in self._name_to_path:
                    self._name_to_path[key] = font_path

            # Store by family name (fallback)
            if family:
                key = family.lower()
                if key not in self._name_to_path:
                    self._name_to_path[key] = font_path

            # Store combined family + subfamily for explicit matching
            if family and subfamily and subfamily not in ["Regular", "Normal"]:
                combined = f"{family} {subfamily}".lower()
                if combined not in self._name_to_path:
                    self._name_to_path[combined] = font_path

    def update(self, system_fonts_filename: Callable[[], Set[str]]) -> None:
        """Update font cache incrementally by only processing new/changed fonts.

        Args:
            system_fonts_filename: Function that returns paths to system fonts.
        """
        # Load existing cache
        self.load()

        # Get current system fonts
        current_fonts = system_fonts_filename()
        cached_paths = set(self._path_to_names.keys())

        # Determine what changed
        new_fonts = current_fonts - cached_paths
        removed_fonts = cached_paths - current_fonts

        if not new_fonts and not removed_fonts:
            prn_dbg("No font changes detected, using existing cache")
            return

        prn_dbg(
            f"Font changes detected: {len(new_fonts)} new, {len(removed_fonts)} removed"
        )

        # Remove deleted fonts from cache
        if removed_fonts:
            for font_path in removed_fonts:
                self._path_to_names.pop(font_path, None)
            prn_dbg(f"Removed {len(removed_fonts)} fonts from cache")

        # Scan only new fonts
        if new_fonts:
            prn_dbg(f"Scanning {len(new_fonts)} new font files...")
            new_mappings = self._scan_font_files(new_fonts)
            self._path_to_names.update(new_mappings)
            prn_dbg(f"Added {len(new_mappings)} new fonts to cache")

        # Rebuild reverse lookup and save
        self._build_reverse_lookup()
        self.save()

    def build_full_cache(self, system_fonts_filename: Callable[[], Set[str]]) -> None:
        """Build complete font cache from scratch.

        Args:
            system_fonts_filename: Function that returns paths to system fonts.
        """
        system_fonts = system_fonts_filename()
        prn_dbg(
            f"Found {len(system_fonts)} font files to process, starts mapping font family name"
        )

        self._path_to_names = self._scan_font_files(system_fonts)
        self._build_reverse_lookup()
        self.save()

    def get_mappings(self) -> Dict[str, Path]:
        """Get font name to path mappings.

        Returns:
            Dictionary mapping font names to paths.
        """
        return self._name_to_path

    @staticmethod
    def _scan_font_files(font_paths: Set[str]) -> Dict[str, Dict[str, str]]:
        """Scan font files and extract their names.

        Args:
            font_paths: Set of font file paths to scan.

        Returns:
            Dictionary mapping font paths to their name information.
        """
        font_mappings: Dict[str, Dict[str, str]] = {}

        try:
            from fontTools import ttLib
        except ImportError:
            prn_error(
                "fontTools is required for font name extraction but not installed."
            )
            return font_mappings

        for font_path_str in font_paths:
            font_path = Path(font_path_str)
            if not font_path.exists():
                continue

            try:
                # Extract font names from the font file
                font = ttLib.TTFont(font_path, fontNumber=0)
                name_table = font.get("name")

                names_info = {"family": "", "full_name": "", "subfamily": ""}

                if name_table:
                    for record in name_table.names:  # type: ignore
                        if record.nameID == 1:  # Font Family name
                            names_info["family"] = record.toUnicode().strip()
                        elif record.nameID == 2:  # Subfamily (Bold, Italic, etc.)
                            names_info["subfamily"] = record.toUnicode().strip()
                        elif record.nameID == 4:  # Full font name
                            names_info["full_name"] = record.toUnicode().strip()

                # Only store if we got at least one name
                if names_info["family"] or names_info["full_name"]:
                    font_mappings[font_path_str] = names_info

                font.close()
            except Exception:
                # If we can't read the font, skip it silently
                continue

        return font_mappings


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
    "Noto Sans::Bold": {
        "url": f"{NOTO_URI}/NotoSans[wdth,wght].ttf",
        "path": BASE_DIR / "fonts" / "noto-sans.ttf",
    },
    "Noto Sans::Bold Italic": {
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

    # Use FontCache to manage font mappings
    cache_file = BASE_DIR / "fonts" / "font_cache.json"
    font_cache = FontCache(cache_file)
    font_cache.update(get_system_fonts_filename)

    system_fonts_cache = font_cache.get_mappings()
    prn_dbg(f"Font cache ready with {len(system_fonts_cache)} fonts")

    prn_info(f"Detected {len(fonts)} font(s) used in subtitles, attaching to file")

    found_fonts = 0
    for font_name in fonts:
        font_path: Optional[Path] = None

        prn_dbg(f"Looking up font: {font_name}")
        # First, check if it's a native font we manage
        font_path = _resolve_native_font(font_name)
        if font_path:
            prn_dbg(f" Found in native fonts: {font_path}")

        # If not found in native fonts, try system font lookup
        if not font_path:
            prn_dbg("  Not found in native fonts, checking system fonts...")
            font_path = _resolve_system_font(font_name, system_fonts_cache)
            if font_path:
                prn_dbg(f" Found in system fonts: {font_path}")

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

    Handles both simple names and variation syntax (e.g., "Noto Sans::Italic").

    Args:
        font_name: The name of the font to resolve.

    Returns:
        Path to the native font file if found, None otherwise.
    """
    # Check for exact match first (includes :: syntax)
    if font_name in NATIVE_FONTS:
        return NATIVE_FONTS[font_name]["path"]

    # Try with :: syntax for common variations
    for variation in ["Bold", "Italic", "Bold Italic"]:
        key = f"{font_name}::{variation}"
        if key in NATIVE_FONTS:
            return NATIVE_FONTS[key]["path"]

    return None


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
