"""
Watchlist data access layer - handles file I/O and basic CRUD operations
"""

from pathlib import Path
from typing import List, Optional, Tuple

from bilidownloader.commons.alias import SERIES_ALIASES
from bilidownloader.commons.constants import DEFAULT_WATCHLIST

# Constants
HEAD = "ID\tTitle"
SEP = "\t"
C_SEP = ", "


class WatchlistRepository:
    """Handles file operations and basic data access for watchlist"""

    def __init__(self, path: Path = DEFAULT_WATCHLIST, add_header: bool = True):
        self.path = path
        self.list: List[Tuple[str, str]] = []
        self.add_header = add_header

    def ensure_file_exists(self) -> None:
        """Create the watchlist file with header if it doesn't exist"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._create_empty_file_with_header()

    def _create_empty_file_with_header(self) -> None:
        """Create an empty file with header if needed"""
        if self.add_header:
            with open(self.path, "w", encoding="utf8") as file:
                file.write(f"{HEAD}\n")

    def _read_file_lines(self) -> List[str]:
        """Read and return file lines"""
        with open(self.path, "r", encoding="utf8") as file:
            return file.read().splitlines()

    def _write_file_lines(self, lines: List[str]) -> None:
        """Write lines to file"""
        with open(self.path, "w", encoding="utf8") as file:
            file.write("\n".join(lines) + "\n")

    def has_header(self, lines: List[str]) -> bool:
        """Check if the file has a header line"""
        if not lines:
            return False
        first_line = lines[0].strip().lower()
        return first_line in ("id\ttitle", "id\ttitle\n")

    def is_old_format(self, lines: List[str]) -> bool:
        """Check if the file is in old comma-separated format"""
        if not lines or self.has_header(lines):
            return False
        # Check if any line uses comma separator instead of tab
        for line in lines:
            if line.strip() and C_SEP in line and SEP not in line:
                return True
        return False

    def read(self) -> List[Tuple[str, str]]:
        """Read the watchlist from file"""
        self.list = []

        if not self.path.exists() or self.path.stat().st_size == 0:
            return self.list

        data = self._read_file_lines()

        # Skip header if present
        if self.has_header(data):
            data = data[1:]

        for entry in data:
            parsed_entry = self._parse_entry(entry)
            if parsed_entry:
                season_id, title = parsed_entry
                if season_id in SERIES_ALIASES:
                    title = SERIES_ALIASES[season_id]
                self.list.append((season_id, title))

        return self.list

    def _parse_entry(self, entry: str) -> Optional[Tuple[str, str]]:
        """Parse a single watchlist entry"""
        if not entry.strip():
            return None

        if SEP in entry:
            parts = entry.split(SEP, 1)
            if len(parts) == 2:
                return (parts[0], parts[1])

        return None

    def write(self, entries: List[Tuple[str, str]]) -> None:
        """Write entries to file in TSV format"""
        lines = []
        if self.add_header:
            lines.append(HEAD)

        lines.extend(f"{season_id}{SEP}{title}" for season_id, title in entries)

        self._write_file_lines(lines)

    def add_entry(self, season_id: str, title: str) -> Tuple[str, str]:
        """Add a new entry to watchlist"""
        entry = (season_id, title.strip())
        self.list.append(entry)
        self.write(self.list)
        return entry

    def check_exists(self, season_id: str) -> bool:
        """Check if a season exists in watchlist"""
        for s_id, _ in self.list:
            if s_id == season_id:
                return True
        return False

    def remove_entry(self, season_id: str) -> bool:
        """Remove a specific entry from watchlist"""
        original_count = len(self.list)
        self.list = [entry for entry in self.list if entry[0] != season_id]
        removed = original_count > len(self.list)
        if removed:
            self.write(self.list)
        return removed
