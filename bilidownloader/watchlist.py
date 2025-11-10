from pathlib import Path
from typing import List, Literal, Optional, Tuple, Union

from bilidownloader.alias import SERIES_ALIASES
from bilidownloader.api import BiliApi
from bilidownloader.constants import DEFAULT_WATCHLIST
from bilidownloader.ui import prn_done, prn_error, prn_info
from bilidownloader.utils import DataExistError

# Constants
HEAD = "ID\tTitle"
SEP = "\t"
C_SEP = ", "


class Watchlist:
    def __init__(
        self,
        path: Path = DEFAULT_WATCHLIST,
        cookie_path: Optional[Path] = None,
        add_header: bool = True,
    ):
        self.path = path
        self.list: List[Tuple[str, str]] = []
        self.cookie: Optional[Path] = None
        self.add_header = add_header

        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            prn_info(f"Watchlist file can't be found on {str(path)}, creating...")
            self.path.touch()
        if cookie_path:
            self.cookie = Path(cookie_path)

        self._migrate_to_tsv()
        self.read_watchlist()

    def _has_header(self, lines: List[str]) -> bool:
        """Check if the file has a header line"""
        if not lines:
            return False
        first_line = lines[0].strip().lower()
        return first_line in ("id\ttitle", "id\ttitle\n")

    def _migrate_to_tsv(self) -> None:
        """Migrate watchlist file from old format (comma-separated) to new format (tab-separated)"""
        if not self.path.exists() or self.path.stat().st_size == 0:
            self._create_empty_file_with_header()
            return

        data = self._read_file_lines()
        if not data:
            self._create_empty_file_with_header()
            return

        has_header = self._has_header(data)
        new_data, migrated = self._process_migration_data(data, has_header)

        if self._should_write_file(migrated, has_header, new_data):
            self._write_migration_messages(migrated, has_header)
            self._write_file_lines(new_data)

    def _create_empty_file_with_header(self) -> None:
        """Create an empty file with header if needed"""
        if self.add_header:
            with open(self.path, "w", encoding="utf8") as file:
                file.write(f"{HEAD}\n")

    def _read_file_lines(self) -> List[str]:
        """Read and return file lines"""
        with open(self.path, "r", encoding="utf8") as file:
            return file.read().splitlines()

    def _process_migration_data(
        self, data: List[str], has_header: bool
    ) -> Tuple[List[str], bool]:
        """Process data for migration and return new data and migration status"""
        new_data = []
        migrated = False

        # Handle header
        if self.add_header and not has_header:
            new_data.append(HEAD)
        elif has_header:
            new_data.append(data[0])
            data = data[1:]

        # Process data lines
        for entry in data:
            if not entry.strip():
                continue

            processed_entry, was_migrated = self._process_entry(entry)
            if processed_entry:
                new_data.append(processed_entry)
                if was_migrated:
                    migrated = True

        return new_data, migrated

    def _process_entry(self, entry: str) -> Tuple[Optional[str], bool]:
        """Process a single entry and return the processed entry and migration status"""
        if C_SEP in entry and SEP not in entry:
            # Old comma-separated format
            parts = entry.split(C_SEP, 1)
            if len(parts) == 2:
                return f"{parts[0]}{SEP}{parts[1]}", True
        elif SEP in entry:
            # Already tab-separated
            return entry, False

        # Single value or malformed entry
        return None, False

    def _should_write_file(
        self, migrated: bool, has_header: bool, new_data: List[str]
    ) -> bool:
        """Determine if the file should be written"""
        return migrated or (self.add_header and not has_header and len(new_data) > 1)

    def _write_migration_messages(self, migrated: bool, has_header: bool) -> None:
        """Write appropriate migration messages"""
        if migrated:
            prn_info("Migrating watchlist file to new format (tab-separated)")
        if self.add_header and not has_header:
            prn_info("Adding header to watchlist file")

    def _write_file_lines(self, lines: List[str]) -> None:
        """Write lines to file"""
        with open(self.path, "w", encoding="utf8") as file:
            file.write("\n".join(lines) + "\n")

    def read_watchlist(self) -> List[Tuple[str, str]]:
        """Reads the watchlist from the specified file path.

        Returns:
            List[Tuple[str, str]]: List of Season ID and title as tuples
        """
        self.list = []

        if not self.path.exists() or self.path.stat().st_size == 0:
            return self.list

        data = self._read_file_lines()

        # Skip header if present
        if self._has_header(data):
            data = data[1:]

        for entry in data:
            parsed_entry = self._parse_watchlist_entry(entry)
            if parsed_entry:
                season_id, title = parsed_entry
                if season_id in SERIES_ALIASES:
                    title = SERIES_ALIASES[season_id]
                self.list.append((season_id, title))

        return self.list

    def _parse_watchlist_entry(self, entry: str) -> Optional[Tuple[str, str]]:
        """Parse a single watchlist entry"""
        if not entry.strip():
            return None

        if SEP in entry:
            parts = entry.split(SEP, 1)
            if len(parts) == 2:
                return (parts[0], parts[1])

        return None

    def search_watchlist(
        self, title: Optional[str] = None, season_id: Optional[Union[int, str]] = None
    ) -> Optional[Tuple[str, str]]:
        """Find and return watchlist entry by query. One of two options must be filled to operate.

        Args:
            title (Optional[str], optional): Search by title. Defaults to None.
            season_id (Optional[Union[int, str]], optional): Search by season id. Defaults to None.

        Returns:
            Optional[Tuple[str, str]]: Season ID and Title, None if can't be found

        Raises:
            ValueError: Both title and season_id were empty
        """
        if not title and not season_id:
            raise ValueError("Query is empty. Please provide either title or season_id")

        season_id_str = str(season_id) if season_id is not None else None

        for entry_id, entry_title in self.list:
            if (season_id_str and season_id_str == entry_id) or (
                title and title == entry_title
            ):
                return (entry_id, entry_title)

        return None

    def _write_watchlist(self) -> None:
        """Write data to Watchlist file"""
        lines = []
        if self.add_header:
            lines.append(HEAD)

        lines.extend(f"{season_id}{SEP}{title}" for season_id, title in self.list)

        self._write_file_lines(lines)

    def _remote_update(
        self, season_id: Union[str, int], action: Literal["add", "del"]
    ) -> None:
        """
        Update watchlist on Bilibili's server

        Args:
            season_id (Union[str, int]): Season ID
            action (Literal["add", "del"]): Action to perform

        Raises:
            ValueError: Cookie path must be set to perform this action
            ValueError: Failed to perform remote action
        """
        if not self.cookie:
            raise ValueError("Cookie path must be set to perform this action")

        api = BiliApi(cookie_path=self.cookie)
        action_name = "delete" if action == "del" else "add"

        prn_info(f"Updating watchlist on Bilibili's server: {action_name} {season_id}")

        try:
            resp = api.post_favorite(action, season_id)
            if resp.code != 0:
                error_msg = f"Failed to {action_name} {season_id}: {resp.message}"
                prn_error(error_msg)
                raise ValueError(error_msg)
        except Exception as e:
            prn_error(f"Remote update failed: {e}")
            raise

    def _prn_rw(self, action: str, season_id: Union[str, int], title: str) -> None:
        """
        Prints the action to the console

        Args:
            action (str): Action to perform
            season_id (Union[str, int]): Season ID
            title (str): Title of the show
        """
        act = {
            "add": ["added", "to"],
            "delete": ["deleted", "from"],
        }
        past_ = act[action][0]
        ft = act[action][1]
        prn_done(
            f"{title} ({season_id}) has been {past_} {ft} watchlist on: {str(self.path)}"
        )

    def add_watchlist(
        self,
        season_id: Union[str, int],
        title: str,
        remote_update: bool = False,
    ) -> List[Tuple[str, str]]:
        """
        Writes a season ID to the watchlist, raises an error if it already exists.

        Args:
            season_id (Union[str, int]): Season ID
            title (str): Title of the show
            remote_update (bool, optional): Update watchlist on Bilibili's server. Defaults to False.

        Returns:
            List[Tuple[str, str]]: Updated watchlist

        Raises:
            DataExistError: If the show is already in the watchlist
            ValueError: If season_id or title is empty
        """
        if not season_id or not title.strip():
            raise ValueError("Season ID and title cannot be empty")

        season_id_str = str(season_id)

        if season_id_str in SERIES_ALIASES:
            title = SERIES_ALIASES[season_id_str]

        # Check if already exists
        if any(season_id_str == existing_id for existing_id, _ in self.list):
            raise DataExistError("Show has been added previously to watchlist")

        if remote_update:
            self._remote_update(season_id, "add")

        self.list.append((season_id_str, title.strip()))
        self._write_watchlist()
        self._prn_rw("add", season_id, title)
        return self.list

    def delete_from_watchlist(
        self, season_id: Union[str, int], remote_update: bool = False
    ) -> List[Tuple[str, str]]:
        """
        Deletes a season ID from the watchlist. Raises an error if the season ID is not found.

        Args:
            season_id (Union[str, int]): Season ID
            remote_update (bool, optional): Update watchlist on Bilibili's server. Defaults to False.

        Returns:
            List[Tuple[str, str]]: Updated watchlist

        Raises:
            ValueError: If the season ID is not found in the watchlist
        """
        if not season_id:
            raise ValueError("Season ID cannot be empty")

        # Find the entry to delete
        entry_to_delete = self.search_watchlist(season_id=season_id)
        if not entry_to_delete:
            raise ValueError(f"Season ID {season_id} not found in watchlist")

        if remote_update:
            self._remote_update(season_id, "del")

        # Remove the entry
        season_id_str = str(season_id)
        self.list = [entry for entry in self.list if entry[0] != season_id_str]

        self._write_watchlist()
        self._prn_rw("delete", season_id, entry_to_delete[1])
        return self.list
