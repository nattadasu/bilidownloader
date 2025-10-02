import re
from datetime import datetime
from os import path as opath
from pathlib import Path
from time import time
from typing import Dict, List, Optional, Tuple, Union

from thefuzz import fuzz
from bilidownloader.common import (
    DEFAULT_HISTORY,
    DataExistError,
    prn_done,
    prn_info,
)

# Constants for TSV format
HEAD = "Timestamp\tSeries ID\tSeries Title\tEpisode Index\tEpisode ID"
SEP = "\t"


class History:
    def __init__(self, path: Path = DEFAULT_HISTORY):
        self.path = path
        self.list: List[Tuple[int, str, str, str, str]] = []
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
        from time import sleep
        from alive_progress import alive_bar
        
        new_data = [HEAD]
        
        # Pattern to extract series_id and episode_id from URL
        pattern = re.compile(r"play/(\d+)/(\d+)")
        
        total_urls = len([u for u in urls if u.strip()])
        
        if total_urls == 0:
            return new_data
        
        prn_info(f"Migrating {total_urls} entries to new format...")
        prn_info("Fetching metadata from yt-dlp (this may take a while)...")
        
        try:
            # Try to import extractor for yt-dlp metadata
            from bilidownloader.extractor import BiliProcess
            from bilidownloader.common import DEFAULT_COOKIES
            
            # Create extractor instance
            extractor = BiliProcess(cookie=DEFAULT_COOKIES)
            use_ytdlp = True
        except Exception:
            # Fallback to API method if extractor fails
            use_ytdlp = False
            prn_info("Fallback to API-based metadata fetching")
        
        # Use alive_progress for progress bar
        with alive_bar(total_urls, title="Migrating", bar="smooth") as bar:
            for url in urls:
                url = url.strip()
                if not url:
                    continue
                
                match = pattern.search(url)
                if match:
                    series_id = match.group(1)
                    episode_id = match.group(2)
                    series_title = f"Series {series_id}"
                    episode_idx = ""
                    info = None
                    
                    # Try to get info from yt-dlp
                    if use_ytdlp:
                        try:
                            info = extractor._get_video_info(url)
                            if info and isinstance(info, dict):
                                # Extract series title from yt-dlp metadata
                                series_title = info.get("series", info.get("title", series_title))
                                # Clean up the title
                                if " - " in series_title:
                                    series_title = series_title.split(" - ")[0].strip()
                                
                                # Extract episode number from yt-dlp info
                                episode_num = info.get("episode_number", "")
                                if episode_num:
                                    episode_idx = str(episode_num)
                            sleep(0.5)  # Rate limiting
                        except Exception as e:
                            # Check if it's a geo-restriction or unavailable video error
                            error_str = str(e).lower()
                            if any(keyword in error_str for keyword in [
                                "geo restriction", "not available", "video is not available",
                                "geo-restriction", "georestriction", "unavailable"
                            ]):
                                prn_info(f"⚠ Unreachable video (geo-restricted/removed): {url}")
                                series_title = "Unreachable Series"
                            else:
                                # Other errors - log but use fallback
                                prn_info(f"⚠ Failed to fetch metadata for: {url}")
                            sleep(0.5)  # Rate limiting even on error
                    
                    # Use timestamp 0 for legacy entries
                    entry = f"0{SEP}{series_id}{SEP}{series_title}{SEP}{episode_idx}{SEP}{episode_id}"
                    new_data.append(entry)
                
                bar()  # Update progress bar
        
        prn_info("Migration complete!")
        return new_data



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

    def read_history(self) -> List[Tuple[int, str, str, str, str]]:
        """Reads the history from the specified file path.
        
        Returns:
            List[Tuple[int, str, str, str, str]]: List of (timestamp, series_id, series_title, episode_idx, episode_id)
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

    def _parse_history_entry(self, entry: str) -> Optional[Tuple[int, str, str, str, str]]:
        """Parse a single history entry"""
        if not entry.strip():
            return None

        if SEP in entry:
            parts = entry.split(SEP)
            # Support both old format (4 fields) and new format (5 fields)
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

    def check_history(self, episode_url: str) -> List[Tuple[int, str, str, str, str]]:
        """
        Check if the episode was on the history

        Args:
            episode_url (str): the episode URL to check

        Returns:
            List[Tuple[int, str, str, str, str]]: the history list

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
        for _, s_id, _, _, e_id in self.list:
            if s_id == series_id and e_id == episode_id:
                raise DataExistError("Episode was ripped previously")

        return self.list

    def _write(self, entries: List[Tuple[int, str, str, str, str]]) -> None:
        """Write entries to file in TSV format"""
        lines = [HEAD]
        for timestamp, series_id, series_title, episode_idx, episode_id in entries:
            lines.append(f"{timestamp}{SEP}{series_id}{SEP}{series_title}{SEP}{episode_idx}{SEP}{episode_id}")
        self._write_file_lines(lines)

    def write_history(
        self, 
        episode_url: str, 
        series_id: Optional[str] = None,
        series_title: Optional[str] = None,
        episode_idx: Optional[str] = None,
        episode_id: Optional[str] = None
    ) -> List[Tuple[int, str, str, str, str]]:
        """
        Writes an episode to the history with metadata.

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
        for _, s_id, _, _, e_id in self.list:
            if s_id == series_id and e_id == episode_id:
                raise DataExistError("Episode already exists in history")
        
        # Fetch series title if not provided
        if not series_title:
            # Use a placeholder if title not provided
            series_title = f"Series {series_id}"
        
        # Default episode_idx to empty string if not provided
        if not episode_idx:
            episode_idx = ""
        
        # Get current timestamp
        timestamp = int(time())
        
        # Add to list
        entry = (timestamp, series_id, series_title, episode_idx, episode_id)
        self.list.append(entry)
        
        # Write to file
        self._write(self.list)
        
        prn_done(f"{series_title} (Episode {episode_id}) has been added to history")
        
        return self.list

    def search_history(
        self,
        series_id: Optional[str] = None,
        series_title: Optional[str] = None,
        episode_id: Optional[str] = None,
        fuzzy_threshold: int = 70
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
        fuzzy_threshold: int = 70
    ) -> List[Tuple[int, str, str, str, str]]:
        """
        Purge history entries by series ID or title (with fuzzy matching).

        Args:
            series_id_or_title (str): Series ID or title to search for
            interactive (bool): Show matching entries and confirm deletion
            fuzzy_threshold (int): Minimum fuzzy match score for title matching (0-100, default: 70)

        Returns:
            List[Tuple[int, str, str, str, str]]: Updated history list
        """
        # Try to find matches
        matches = []
        for entry in self.list:
            _, s_id, s_title, _, _ = entry
            # Exact match on series ID or fuzzy match on title
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
            
            # For now, just show the matches
            # In a full implementation, this would prompt for confirmation
            prn_info("Interactive deletion not fully implemented, showing matches only")
            return self.list
        
        # Remove matches
        self.list = [entry for entry in self.list if entry not in matches]
        self._write(self.list)
        
        prn_done(f"Removed {len(matches)} entries from history")
        return self.list

    def purge_by_date(self, date_input: Union[int, str]) -> List[Tuple[int, str, str, str, str]]:
        """
        Purge entries older than specified date.

        Args:
            date_input (Union[int, str]): Either:
                - Number of days ago (int)
                - Date string in YYYY-MM-DD format (str)

        Returns:
            List[Tuple[int, str, str, str, str]]: Updated history list
        """
        if isinstance(date_input, int):
            # Days ago
            threshold = int(time()) - (date_input * 86400)
            date_desc = f"{date_input} days"
        else:
            # Parse date string (YYYY-MM-DD)
            try:
                dt = datetime.strptime(date_input, "%Y-%m-%d")
                # Convert to local time epoch
                threshold = int(dt.timestamp())
                date_desc = date_input
            except ValueError:
                raise ValueError(f"Invalid date format: {date_input}. Expected YYYY-MM-DD")
        
        old_count = len(self.list)
        self.list = [entry for entry in self.list if entry[0] >= threshold]
        removed_count = old_count - len(self.list)
        
        if removed_count > 0:
            self._write(self.list)
            prn_done(f"Removed {removed_count} entries older than {date_desc}")
        else:
            prn_info(f"No entries found older than {date_desc}")
        
        return self.list

    def purge_all(self, confirm: bool = True) -> List[Tuple[int, str, str, str, str]]:
        """
        Clear entire history.

        Args:
            confirm (bool): Whether confirmation is required (for safety)

        Returns:
            List[Tuple[int, str, str, str, str]]: Empty list
        """
        if confirm:
            prn_info("Clearing all history")
        
        self.list = []
        self._create_empty_file_with_header()
        
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
            return {
                "total_episodes": 0,
                "unique_series": 0,
                "date_range": "N/A"
            }
        
        unique_series = set(s_id for _, s_id, _, _, _ in self.list)
        timestamps = [ts for ts, _, _, _, _ in self.list if ts > 0]
        
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

