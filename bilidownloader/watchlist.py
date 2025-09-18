from copy import deepcopy
from os import path as opath
from pathlib import Path
from typing import List, Literal, Optional, Tuple, Union

from bilidownloader.api import BiliApi
from bilidownloader.common import (
    DEFAULT_WATCHLIST,
    DataExistError,
    prn_done,
    prn_error,
    prn_info,
)


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
        if not opath.exists(self.path):
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
        first_line = lines[0].strip()
        return first_line.lower() == "id\ttitle"

    def _migrate_to_tsv(self) -> None:
        """Migrate watchlist file from old format (comma-separated) to new format (tab-separated)"""
        if not opath.exists(self.path) or opath.getsize(self.path) == 0:
            if self.add_header:
                with open(self.path, "w", encoding="utf8") as file:
                    file.write("ID\tTitle\n")
            return

        with open(self.path, "r", encoding="utf8") as file:
            data = file.read().splitlines()
        
        if not data:
            if self.add_header:
                with open(self.path, "w", encoding="utf8") as file:
                    file.write("ID\tTitle\n")
            return

        has_header = self._has_header(data)
        migrated = False
        new_data = []
        
        # Add header if needed and not present
        if self.add_header and not has_header:
            new_data.append("ID\tTitle")
        elif has_header:
            new_data.append(data[0])  # Keep existing header
            data = data[1:]  # Skip header for processing

        for entry in data:
            if not entry.strip():  # Skip empty lines
                continue
            if ", " in entry and "\t" not in entry:
                # Old comma-separated format
                spl = entry.split(", ", 1)
                if len(spl) == 2:
                    new_data.append(f"{spl[0]}\t{spl[1]}")
                    migrated = True
            elif "\t" in entry:
                # Already tab-separated
                new_data.append(entry)
            else:
                # Single value or malformed entry, skip
                continue
        
        if migrated or (self.add_header and not has_header and len(new_data) > 1):
            if migrated:
                prn_info("Migrating watchlist file to new format (tab-separated)")
            if self.add_header and not has_header:
                prn_info("Adding header to watchlist file")
            
            with open(self.path, "w", encoding="utf8") as file:
                file.write("\n".join(new_data) + "\n")

    def read_watchlist(self) -> List[Tuple[str, str]]:
        """Reads the watchlist from the specified file path.

        Returns:
            List[Tuple[str, str]]: List of Season ID and title as tuples
        """
        self.list = []  # Clear existing list
        
        if not opath.exists(self.path) or opath.getsize(self.path) == 0:
            return self.list

        with open(self.path, "r", encoding="utf8") as file:
            data = file.read().splitlines()
        
        # Skip header if present
        if self._has_header(data):
            data = data[1:]
        
        for entry in data:
            if not entry.strip():  # Skip empty lines
                continue
            if "\t" in entry:
                spl = entry.split("\t", 1)
                if len(spl) == 2:
                    self.list.append((spl[0], spl[1]))
        
        return self.list

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
            NameError: Both title and season_id were empty
        """
        if not title and not season_id:
            raise NameError("Query is empty. Please fill either title or season_id")
        for entry in self.list:
            if (str(season_id) == entry[0]) or (title == entry[1]):
                return entry
        return None

    def _write_watchlist(self) -> None:
        """Write data to Watchlist file"""
        with open(self.path, "w", encoding="utf8") as file:
            if self.add_header:
                file.write("ID\tTitle\n")
            for season, name in self.list:
                file.write(f"{season}\t{name}\n")

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
            ValueError: Failed to {long_action} {season_id}: {resp.message}
        """
        if not self.cookie:
            raise ValueError("Cookie path must be set to perform this action")
        api = BiliApi(cookie_path=self.cookie)
        long_action = "delete" if action == "del" else "add"
        prn_info(
            f"Cookies found, updating watchlist on Bilibili's server: {long_action} {season_id}"
        )
        try:
            resp = api.post_favorite(action, season_id)
            if resp.code != 0:
                raise ValueError(f"Failed to {long_action} {season_id}: {resp.message}")
        except Exception as e:
            prn_error(f"{e}")

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
        remote_update: Optional[bool] = False,
    ) -> List[Tuple[str, str]]:
        """
        Writes a season ID to the watchlist, raises an error if it already exists.

        Args:
            season_id (Union[str, int]): Season ID
            title (str): Title of the show
            remote_update (Optional[bool], optional): Update watchlist on Bilibili's server. Defaults to False.

        Returns:
            List[Tuple[str, str]]: Updated watchlist
        """
        for season, _ in self.list:
            if str(season_id) == season:
                raise DataExistError("Show has been added previously to watchlist")

        if remote_update:
            self._remote_update(season_id, "add")

        self.list.append((str(season_id), title))
        self._write_watchlist()
        self._prn_rw("add", season_id, title)
        return self.list

    def delete_from_watchlist(
        self, season_id: Union[str, int], remote_update: Optional[bool] = False
    ) -> List[Tuple[str, str]]:
        """
        Deletes a season ID from the watchlist. Raises an error if the season ID is not found.

        Args:
            season_id (Union[str, int]): Season ID
            remote_update (Optional[bool], optional): Update watchlist on Bilibili's server. Defaults to False.

        Returns:
            List[Tuple[str, str]]: Updated watchlist
        """
        # Filter out the season ID to be deleted
        updated_data = [entry for entry in self.list if entry[0] != str(season_id)]

        if len(updated_data) == len(self.list):
            raise ValueError("Season ID not found in watchlist")

        if remote_update:
            self._remote_update(season_id, "del")

        idx = self.search_watchlist(season_id=season_id)
        if not idx:
            raise ValueError("Season ID not found in watchlist")
        self.list = deepcopy(updated_data)
        self._write_watchlist()
        self._prn_rw("delete", season_id, idx[1])
        return updated_data
