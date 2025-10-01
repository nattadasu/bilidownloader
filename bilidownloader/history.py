import re
from datetime import datetime
from os import path as opath
from pathlib import Path
from time import time
from typing import Dict, List, Optional, Tuple, Union

from bilidownloader.api import BiliApi
from bilidownloader.common import (
    DEFAULT_HISTORY,
    DataExistError,
    prn_done,
    prn_info,
)

# Constants for TSV format
HEAD = "Timestamp\tSeries ID\tSeries Title\tEpisode ID"
SEP = "\t"


class History:
    def __init__(self, path: Path = DEFAULT_HISTORY):
        self.path = path
        self.list: List[Tuple[int, str, str, str]] = []
        self._legacy_list: List[str] = []  # For backward compatibility during migration

        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not opath.exists(self.path):
            # Check for old history.txt file
            old_path = self.path.parent / "history.txt"
            if old_path.exists():
                prn_info(f"Found old history file at {old_path}, will migrate to new format")
                # Rename old file temporarily
                self.path = old_path
                self._migrate_to_tsv()
                # Update path to new file
                self.path = path
            else:
                prn_info(f"History file can't be found on {str(path)}, creating...")
                self._create_empty_file_with_header()
        else:
            self._migrate_to_tsv()
        
        self.read_history()

    def _has_header(self, lines: List[str]) -> bool:
        """Check if the file has a header line"""
        if not lines:
            return False
        first_line = lines[0].strip().lower()
        return first_line.startswith("timestamp")

    def _is_old_format(self, lines: List[str]) -> bool:
        """Check if the file is in old URL-only format"""
        if not lines or self._has_header(lines):
            return False
        # Check if first line looks like a URL
        first_line = lines[0].strip()
        return bool(re.match(r"https?://", first_line))

    def _migrate_to_tsv(self) -> None:
        """Migrate history file from old format (URL list) to new format (TSV)"""
        if not self.path.exists() or self.path.stat().st_size == 0:
            self._create_empty_file_with_header()
            return

        data = self._read_file_lines()
        if not data:
            self._create_empty_file_with_header()
            return

        has_header = self._has_header(data)
        is_old_format = self._is_old_format(data)

        if is_old_format:
            prn_info("Migrating history from old URL format to new TSV format...")
            new_data = self._convert_old_format_to_tsv(data)
            
            # Update path to new format file if we're still using old path
            if self.path.name == "history.txt":
                new_path = self.path.parent / "history.v2.tsv"
                self.path = new_path
            
            self._write_file_lines(new_data)
            prn_info("Migration completed successfully")
        elif not has_header:
            # TSV format but missing header
            prn_info("Adding header to history file")
            new_data = [HEAD] + data
            self._write_file_lines(new_data)

    def _convert_old_format_to_tsv(self, urls: List[str]) -> List[str]:
        """Convert old URL-only format to TSV format with metadata"""
        new_data = [HEAD]
        
        # Pattern to extract series_id and episode_id from URL
        pattern = re.compile(r"play/(\d+)/(\d+)")
        
        # Cache for series titles to minimize API calls
        series_cache: Dict[str, str] = {}
        
        for url in urls:
            url = url.strip()
            if not url:
                continue
            
            match = pattern.search(url)
            if match:
                series_id = match.group(1)
                episode_id = match.group(2)
                
                # Get series title from cache or API
                if series_id not in series_cache:
                    series_title = self._fetch_series_title(series_id, series_cache)
                else:
                    series_title = series_cache[series_id]
                
                # Use timestamp 0 for legacy entries
                entry = f"0{SEP}{series_id}{SEP}{series_title}{SEP}{episode_id}"
                new_data.append(entry)
        
        return new_data

    def _fetch_series_title(self, series_id: str, cache: Dict[str, str]) -> str:
        """Fetch series title from API and cache it"""
        if series_id in cache:
            return cache[series_id]
        
        try:
            api = BiliApi()
            # Get all shows and find the matching one
            shows = api.get_all_shows_simple()
            for show_id, title in shows:
                cache[show_id] = title
                if show_id == series_id:
                    return title
            
            # If not found, return a placeholder
            cache[series_id] = f"Series {series_id}"
            return cache[series_id]
        except Exception:
            # If API fails, use placeholder
            cache[series_id] = f"Series {series_id}"
            return cache[series_id]

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

    def read_history(self) -> List[Tuple[int, str, str, str]]:
        """Reads the history from the specified file path.
        
        Returns:
            List[Tuple[int, str, str, str]]: List of (timestamp, series_id, series_title, episode_id)
        """
        self.list = []
        self._legacy_list = []

        if not self.path.exists() or self.path.stat().st_size == 0:
            return self.list

        data = self._read_file_lines()

        # Skip header if present
        if self._has_header(data):
            data = data[1:]

        for entry in data:
            parsed_entry = self._parse_history_entry(entry)
            if parsed_entry:
                self.list.append(parsed_entry)

        return self.list

    def _parse_history_entry(self, entry: str) -> Optional[Tuple[int, str, str, str]]:
        """Parse a single history entry"""
        if not entry.strip():
            return None

        if SEP in entry:
            parts = entry.split(SEP)
            if len(parts) == 4:
                try:
                    timestamp = int(parts[0])
                    series_id = parts[1]
                    series_title = parts[2]
                    episode_id = parts[3]
                    return (timestamp, series_id, series_title, episode_id)
                except ValueError:
                    return None

        return None

    def check_history(self, episode_url: str) -> List[Tuple[int, str, str, str]]:
        """
        Check if the episode was on the history

        Args:
            episode_url (str): the episode URL to check

        Returns:
            List[Tuple[int, str, str, str]]: the history list

        Raises:
            DataExistError: if the episode was on the history
        """
        # Extract series_id and episode_id from URL
        pattern = re.compile(r"play/(\d+)/(\d+)")
        match = pattern.search(episode_url)
        
        if not match:
            return self.list
        
        series_id = match.group(1)
        episode_id = match.group(2)
        
        # Check if this series+episode combination exists
        for _, s_id, _, e_id in self.list:
            if s_id == series_id and e_id == episode_id:
                raise DataExistError("Episode was ripped previously")

        return self.list

    def _write(self, entries: List[Tuple[int, str, str, str]]) -> None:
        """Write entries to file in TSV format"""
        lines = [HEAD]
        for timestamp, series_id, series_title, episode_id in entries:
            lines.append(f"{timestamp}{SEP}{series_id}{SEP}{series_title}{SEP}{episode_id}")
        self._write_file_lines(lines)

    def write_history(
        self, 
        episode_url: str, 
        series_id: Optional[str] = None,
        series_title: Optional[str] = None,
        episode_id: Optional[str] = None
    ) -> List[Tuple[int, str, str, str]]:
        """
        Writes an episode to the history with metadata.

        Args:
            episode_url (str): the episode URL to write
            series_id (Optional[str]): the series ID (extracted from URL if not provided)
            series_title (Optional[str]): the series title (fetched from API if not provided)
            episode_id (Optional[str]): the episode ID (extracted from URL if not provided)

        Returns:
            List[Tuple[int, str, str, str]]: the history list
            
        Raises:
            DataExistError: if the episode already exists in history
        """
        # Extract IDs from URL if not provided
        pattern = re.compile(r"play/(\d+)/(\d+)")
        match = pattern.search(episode_url)
        
        if not match:
            raise ValueError("Invalid episode URL format")
        
        if not series_id:
            series_id = match.group(1)
        if not episode_id:
            episode_id = match.group(2)
        
        # Check for duplicates
        for _, s_id, _, e_id in self.list:
            if s_id == series_id and e_id == episode_id:
                raise DataExistError("Episode already exists in history")
        
        # Fetch series title if not provided
        if not series_title:
            series_title = self._fetch_series_title(series_id, {})
        
        # Get current timestamp
        timestamp = int(time())
        
        # Add to list
        entry = (timestamp, series_id, series_title, episode_id)
        self.list.append(entry)
        
        # Write to file
        self._write(self.list)
        
        prn_done(f"{series_title} (Episode {episode_id}) has been added to history")
        
        return self.list

    def search_history(
        self,
        series_id: Optional[str] = None,
        series_title: Optional[str] = None,
        episode_id: Optional[str] = None
    ) -> List[Tuple[int, str, str, str]]:
        """
        Search history by series ID, title, or episode ID.

        Args:
            series_id (Optional[str]): Search by series ID
            series_title (Optional[str]): Search by series title (partial match)
            episode_id (Optional[str]): Search by episode ID

        Returns:
            List[Tuple[int, str, str, str]]: Matching history entries
        """
        results = []
        
        for timestamp, s_id, s_title, e_id in self.list:
            match = True
            
            if series_id and s_id != series_id:
                match = False
            if series_title and series_title.lower() not in s_title.lower():
                match = False
            if episode_id and e_id != episode_id:
                match = False
            
            if match:
                results.append((timestamp, s_id, s_title, e_id))
        
        return results

    def purge_by_series(
        self,
        series_id_or_title: str,
        interactive: bool = False
    ) -> List[Tuple[int, str, str, str]]:
        """
        Purge history entries by series ID or title.

        Args:
            series_id_or_title (str): Series ID or title to search for
            interactive (bool): Show matching entries and confirm deletion

        Returns:
            List[Tuple[int, str, str, str]]: Updated history list
        """
        # Try to find matches
        matches = []
        for entry in self.list:
            _, s_id, s_title, _ = entry
            if s_id == series_id_or_title or series_id_or_title.lower() in s_title.lower():
                matches.append(entry)
        
        if not matches:
            prn_info(f"No history entries found for: {series_id_or_title}")
            return self.list
        
        if interactive:
            prn_info(f"Found {len(matches)} entries:")
            for timestamp, s_id, s_title, e_id in matches:
                date_str = self.format_timestamp(timestamp)
                prn_info(f"  - {s_title} (Series {s_id}, Episode {e_id}) - {date_str}")
            
            # For now, just show the matches
            # In a full implementation, this would prompt for confirmation
            prn_info("Interactive deletion not fully implemented, showing matches only")
            return self.list
        
        # Remove matches
        self.list = [entry for entry in self.list if entry not in matches]
        self._write(self.list)
        
        prn_done(f"Removed {len(matches)} entries from history")
        return self.list

    def purge_by_date(self, days_ago: int) -> List[Tuple[int, str, str, str]]:
        """
        Purge entries older than specified number of days.

        Args:
            days_ago (int): Remove entries older than this many days

        Returns:
            List[Tuple[int, str, str, str]]: Updated history list
        """
        threshold = int(time()) - (days_ago * 86400)  # 86400 seconds in a day
        
        old_count = len(self.list)
        self.list = [entry for entry in self.list if entry[0] >= threshold]
        removed_count = old_count - len(self.list)
        
        if removed_count > 0:
            self._write(self.list)
            prn_done(f"Removed {removed_count} entries older than {days_ago} days")
        else:
            prn_info(f"No entries found older than {days_ago} days")
        
        return self.list

    def purge_all(self, confirm: bool = True) -> List[Tuple[int, str, str, str]]:
        """
        Clear entire history.

        Args:
            confirm (bool): Whether confirmation is required (for safety)

        Returns:
            List[Tuple[int, str, str, str]]: Empty list
        """
        if confirm:
            prn_info("Clearing all history")
        
        self.list = []
        self._create_empty_file_with_header()
        
        if confirm:
            prn_done("History cleared successfully")
        
        return self.list

    def format_timestamp(self, timestamp: int) -> str:
        """Format a UNIX timestamp for display.
        
        Args:
            timestamp (int): UNIX timestamp
            
        Returns:
            str: Formatted date string
        """
        if timestamp == 0:
            return "Unknown (migrated)"
        
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    def get_statistics(self) -> Dict[str, Union[int, str]]:
        """Get statistics about the history.
        
        Returns:
            Dict: Statistics including total episodes, series count, date range
        """
        if not self.list:
            return {
                "total_episodes": 0,
                "unique_series": 0,
                "date_range": "N/A"
            }
        
        unique_series = set(s_id for _, s_id, _, _ in self.list)
        timestamps = [ts for ts, _, _, _ in self.list if ts > 0]
        
        if timestamps:
            oldest = min(timestamps)
            newest = max(timestamps)
            date_range = f"{self.format_timestamp(oldest)} to {self.format_timestamp(newest)}"
        else:
            date_range = "N/A"
        
        return {
            "total_episodes": len(self.list),
            "unique_series": len(unique_series),
            "date_range": date_range
        }

