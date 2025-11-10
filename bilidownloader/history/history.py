import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from thefuzz import fuzz

from bilidownloader.commons.constants import DEFAULT_HISTORY
from bilidownloader.commons.ui import prn_done, prn_info
from bilidownloader.commons.utils import DataExistError
from bilidownloader.history.migration import HistoryMigrator
from bilidownloader.history.repository import HistoryRepository


class History:
    """Main interface for history management"""

    def __init__(self, path: Path = DEFAULT_HISTORY):
        self.repo = HistoryRepository(path)
        self.repo.ensure_file_exists()

        # Check for old history.txt file and migrate if needed
        old_path = path.parent / "history.txt"
        if old_path.exists() and old_path != path:
            prn_info(
                f"Found old history file at {old_path}, will migrate to new format"
            )
            self.repo.path = old_path
            migrator = HistoryMigrator(self.repo)
            migrator.migrate_if_needed()
            self.repo.path = path
        else:
            migrator = HistoryMigrator(self.repo)
            migrator.migrate_if_needed()

        self.read_history()

    @property
    def path(self) -> Path:
        """Get the path to the history file"""
        return self.repo.path

    @path.setter
    def path(self, value: Path) -> None:
        """Set the path to the history file"""
        self.repo.path = value

    @property
    def list(self) -> List[Tuple[int, str, str, str, str]]:
        """Get the history list"""
        return self.repo.list

    def read_history(self) -> List[Tuple[int, str, str, str, str]]:
        """Read the history from the file"""
        return self.repo.read()

    def check_history(self, episode_url: str) -> List[Tuple[int, str, str, str, str]]:
        """
        Check if the episode was in the history

        Args:
            episode_url (str): the episode URL to check

        Returns:
            List[Tuple[int, str, str, str, str]]: the history list

        Raises:
            DataExistError: if the episode was in the history
        """
        pattern = re.compile(r"play/(\d+)/(\d+)")
        match = pattern.search(episode_url)

        if not match:
            return self.list

        series_id = match.group(1)
        episode_id = match.group(2)

        if self.repo.check_exists(series_id, episode_id):
            raise DataExistError("Episode was ripped previously")

        return self.list

    def write_history(
        self,
        episode_url: str,
        series_id: Optional[str] = None,
        series_title: Optional[str] = None,
        episode_idx: Optional[str] = None,
        episode_id: Optional[str] = None,
    ) -> List[Tuple[int, str, str, str, str]]:
        """
        Write an episode to the history with metadata

        Args:
            episode_url (str): the episode URL to write
            series_id (Optional[str]): the series ID (extracted from URL if not provided)
            series_title (Optional[str]): the series title (fetched from API if not provided)
            episode_idx (Optional[str]): the episode index/number
            episode_id (Optional[str]): the episode ID (extracted from URL if not provided)

        Returns:
            List[Tuple[int, str, str, str, str]]: the history list

        Raises:
            DataExistError: if the episode already exists in history
        """
        pattern = re.compile(r"play/(\d+)/(\d+)")
        match = pattern.search(episode_url)

        if not match:
            raise ValueError("Invalid episode URL format")

        if not series_id:
            series_id = match.group(1)
        if not episode_id:
            episode_id = match.group(2)

        if not series_id or not episode_id:
            raise ValueError("Series ID and Episode ID must be provided or extractable")

        if self.repo.check_exists(series_id, episode_id):
            raise DataExistError("Episode already exists in history")

        if not series_title:
            series_title = f"Series {series_id}"

        if not episode_idx:
            episode_idx = ""

        self.repo.add_entry(series_id, series_title, episode_id, episode_idx)
        return self.list

    def search_history(
        self,
        series_id: Optional[str] = None,
        series_title: Optional[str] = None,
        episode_id: Optional[str] = None,
        fuzzy_threshold: int = 70,
    ) -> List[Tuple[int, str, str, str, str]]:
        """
        Search history by series ID, title, or episode ID.

        Args:
            series_id (Optional[str]): Search by series ID (exact match)
            series_title (Optional[str]): Search by series title (fuzzy match)
            episode_id (Optional[str]): Search by episode ID (exact match)
            fuzzy_threshold (int): Minimum fuzzy match score (0-100, default: 70)

        Returns:
            List[Tuple[int, str, str, str, str]]: Matching history entries
        """
        results = []

        for timestamp, s_id, s_title, e_idx, e_id in self.list:
            match = True

            if series_id and s_id != series_id:
                match = False
            if series_title:
                # Use fuzzy matching for title search
                ratio = fuzz.partial_ratio(series_title.lower(), s_title.lower())
                if ratio < fuzzy_threshold:
                    match = False
            if episode_id and e_id != episode_id:
                match = False

            if match:
                results.append((timestamp, s_id, s_title, e_idx, e_id))

        return results

    def purge_by_series(
        self,
        series_id_or_title: str,
        interactive: bool = False,
        fuzzy_threshold: int = 70,
    ) -> List[Tuple[int, str, str, str, str]]:
        """
        Purge history entries by series ID or title (with fuzzy matching)

        Args:
            series_id_or_title (str): Series ID or title to search for
            interactive (bool): Show matching entries and confirm deletion
            fuzzy_threshold (int): Minimum fuzzy match score for title matching (0-100, default: 70)

        Returns:
            List[Tuple[int, str, str, str, str]]: Updated history list
        """
        matches = []
        for entry in self.list:
            _, s_id, s_title, _, _ = entry
            if s_id == series_id_or_title:
                matches.append(entry)
            else:
                ratio = fuzz.partial_ratio(series_id_or_title.lower(), s_title.lower())
                if ratio >= fuzzy_threshold:
                    matches.append(entry)

        if not matches:
            prn_info(f"No history entries found for: {series_id_or_title}")
            return self.list

        if interactive:
            prn_info(f"Found {len(matches)} entries:")
            for timestamp, s_id, s_title, e_idx, e_id in matches:
                date_str = self.format_timestamp(timestamp)
                prn_info(f"  - {s_title} (Series {s_id}, Episode {e_id}) - {date_str}")
            prn_info("Interactive deletion not fully implemented, showing matches only")
            return self.list

        removed_count = self.repo.remove_entries(matches)
        prn_done(f"Removed {removed_count} entries from history")
        return self.list

    def purge_by_episode_id(
        self, episode_ids: List[str]
    ) -> List[Tuple[int, str, str, str, str]]:
        """
        Purge history entries by episode ID(s)

        Args:
            episode_ids (List[str]): List of episode IDs to delete

        Returns:
            List[Tuple[int, str, str, str, str]]: Updated history list
        """
        matches = []
        for entry in self.list:
            _, _, _, _, e_id = entry
            if e_id in episode_ids:
                matches.append(entry)

        if not matches:
            prn_info("No history entries found for the specified episode ID(s)")
            return self.list

        removed_count = self.repo.remove_entries(matches)
        prn_done(f"Removed {removed_count} entries from history")
        return self.list

    def purge_by_date(
        self, date_input: Union[int, str]
    ) -> List[Tuple[int, str, str, str, str]]:
        """
        Purge entries older than specified date

        Args:
            date_input (Union[int, str]): Either:
                - Number of days ago (int)
                - Date string in YYYY-MM-DD format (str)

        Returns:
            List[Tuple[int, str, str, str, str]]: Updated history list
        """
        from time import time

        if isinstance(date_input, int):
            threshold = int(time()) - (date_input * 86400)
            date_desc = f"{date_input} days"
        else:
            try:
                dt = datetime.strptime(date_input, "%Y-%m-%d")
                threshold = int(dt.timestamp())
                date_desc = date_input
            except ValueError:
                raise ValueError(
                    f"Invalid date format: {date_input}. Expected YYYY-MM-DD"
                )

        to_remove = [entry for entry in self.list if entry[0] < threshold]
        removed_count = self.repo.remove_entries(to_remove)

        if removed_count > 0:
            prn_done(f"Removed {removed_count} entries older than {date_desc}")
        else:
            prn_info(f"No entries found older than {date_desc}")

        return self.list

    def purge_all(self, confirm: bool = True) -> List[Tuple[int, str, str, str, str]]:
        """
        Clear entire history

        Args:
            confirm (bool): Whether confirmation is required (for safety)

        Returns:
            List[Tuple[int, str, str, str, str]]: Empty list
        """
        if confirm:
            prn_info("Clearing all history")

        self.repo.list = []
        self.repo._create_empty_file_with_header()

        if confirm:
            prn_done("History cleared successfully")

        return self.list

    def format_timestamp(self, timestamp: int, use_rich: bool = False) -> str:
        """Format a UNIX timestamp for display.

        Args:
            timestamp (int): UNIX timestamp
            use_rich (bool): Whether to use rich markup for migrated entries

        Returns:
            str: Formatted date string
        """
        if timestamp == 0:
            if use_rich:
                return "[i]Migrated[/i]"
            return "Migrated"

        # Use localtime for conversion
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    def get_statistics(self) -> Dict[str, Union[int, str]]:
        """Get statistics about the history.

        Returns:
            Dict: Statistics including total episodes, series count, date range
        """
        if not self.list:
            return {"total_episodes": 0, "unique_series": 0, "date_range": "N/A"}

        unique_series = set(s_id for _, s_id, _, _, _ in self.list)
        timestamps = [ts for ts, _, _, _, _ in self.list if ts > 0]

        if timestamps:
            oldest = min(timestamps)
            newest = max(timestamps)
            date_range = (
                f"{self.format_timestamp(oldest)} to {self.format_timestamp(newest)}"
            )
        else:
            date_range = "N/A"

        return {
            "total_episodes": len(self.list),
            "unique_series": len(unique_series),
            "date_range": date_range,
        }
