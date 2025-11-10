"""
History data access layer - handles file I/O and basic CRUD operations
"""

import re
from pathlib import Path
from time import time
from typing import List, Optional, Tuple

from bilidownloader.commons.alias import SERIES_ALIASES
from bilidownloader.commons.constants import DEFAULT_HISTORY
from bilidownloader.commons.ui import prn_done

# Constants for TSV format
HEAD = "Timestamp\tSeries ID\tSeries Title\tEpisode Index\tEpisode ID"
SEP = "\t"


class HistoryRepository:
    """Handles file operations and basic data access for history"""

    def __init__(self, path: Path = DEFAULT_HISTORY):
        self.path = path
        self.list: List[Tuple[int, str, str, str, str]] = []

    def ensure_file_exists(self) -> None:
        """Create the history file with header if it doesn't exist"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._create_empty_file_with_header()

    def _create_empty_file_with_header(self) -> None:
        """Create an empty file with header"""
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
        return first_line.startswith("timestamp")

    def is_old_format(self, lines: List[str]) -> bool:
        """Check if the file is in old URL-only format"""
        if not lines or self.has_header(lines):
            return False
        first_line = lines[0].strip()
        return bool(re.match(r"https?://", first_line))

    def read(self) -> List[Tuple[int, str, str, str, str]]:
        """Read the history from file"""
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
                timestamp, series_id, series_title, episode_idx, episode_id = (
                    parsed_entry
                )
                if series_id in SERIES_ALIASES:
                    series_title = SERIES_ALIASES[series_id]
                self.list.append(
                    (timestamp, series_id, series_title, episode_idx, episode_id)
                )

        return self.list

    def _parse_entry(self, entry: str) -> Optional[Tuple[int, str, str, str, str]]:
        """Parse a single history entry"""
        if not entry.strip():
            return None

        if SEP in entry:
            parts = entry.split(SEP)
            if len(parts) == 5:
                try:
                    timestamp = int(parts[0])
                    series_id = parts[1]
                    series_title = parts[2]
                    episode_idx = parts[3]
                    episode_id = parts[4]
                    return (timestamp, series_id, series_title, episode_idx, episode_id)
                except ValueError:
                    return None
            elif len(parts) == 4:
                # Old format without episode_idx
                try:
                    timestamp = int(parts[0])
                    series_id = parts[1]
                    series_title = parts[2]
                    episode_id = parts[3]
                    return (timestamp, series_id, series_title, "", episode_id)
                except ValueError:
                    return None

        return None

    def write(self, entries: List[Tuple[int, str, str, str, str]]) -> None:
        """Write entries to file in TSV format"""
        lines = [HEAD]
        for timestamp, series_id, series_title, episode_idx, episode_id in entries:
            lines.append(
                f"{timestamp}{SEP}{series_id}{SEP}{series_title}{SEP}{episode_idx}{SEP}{episode_id}"
            )
        self._write_file_lines(lines)

    def add_entry(
        self,
        series_id: str,
        series_title: str,
        episode_id: str,
        episode_idx: str = "",
        timestamp: Optional[int] = None,
    ) -> Tuple[int, str, str, str, str]:
        """Add a new entry to history"""
        if timestamp is None:
            timestamp = int(time())

        entry = (timestamp, series_id, series_title, episode_idx, episode_id)
        self.list.append(entry)
        self.write(self.list)
        prn_done(f"{series_title} (Episode {episode_id}) has been added to history")
        return entry

    def check_exists(self, series_id: str, episode_id: str) -> bool:
        """Check if an episode exists in history"""
        for _, s_id, _, _, e_id in self.list:
            if s_id == series_id and e_id == episode_id:
                return True
        return False

    def remove_entries(self, entries: List[Tuple[int, str, str, str, str]]) -> int:
        """Remove specific entries from history"""
        original_count = len(self.list)
        self.list = [entry for entry in self.list if entry not in entries]
        removed_count = original_count - len(self.list)
        if removed_count > 0:
            self.write(self.list)
        return removed_count
