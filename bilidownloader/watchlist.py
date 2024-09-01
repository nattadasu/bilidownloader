from copy import deepcopy
from os import path as opath
from pathlib import Path
from typing import List, Optional, Tuple, Union

from survey import printers

try:
    from common import DEFAULT_WATCHLIST, DataExistError
except ImportError:
    from bilidownloader.common import DEFAULT_WATCHLIST, DataExistError


class Watchlist:
    def __init__(self, path: Path = DEFAULT_WATCHLIST):
        self.path = path
        self.list: List[Tuple[str, str]] = []

        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not opath.exists(self.path):
            printers.info(f"Watchlist file can't be found on {str(path)}, creating...")
            with open(self.path, "w+", encoding="utf8") as file:
                file.write("")
        self.read_watchlist()

    def read_watchlist(self) -> List[Tuple[str, str]]:
        """Reads the watchlist from the specified file path.

        Returns:
            List[Tuple[str, str]]: List of Season ID and title as tuples
        """
        with open(self.path, "r+", encoding="utf8") as file:
            data = file.read().splitlines()
        for entry in data:
            spl = entry.split(", ", 1)
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
        with open(self.path, "w+", encoding="utf8") as file:
            for season, name in self.list:
                file.write(f"{season}, {name}\n")

    def add_watchlist(
        self, season_id: Union[str, int], title: str
    ) -> List[Tuple[str, str]]:
        """Writes a season ID to the watchlist, raises an error if it already exists."""
        for season, _ in self.list:
            if str(season_id) == season:
                raise DataExistError("Show has been added previously to watchlist")

        self.list.append((str(season_id), title))
        self._write_watchlist()
        printers.done(f"{title} has been added to {str(self.path)}")
        return self.list

    def delete_from_watchlist(
        self, season_id: Union[str, int]
    ) -> List[Tuple[str, str]]:
        """Deletes a season ID from the watchlist. Raises an error if the season ID is not found."""
        # Filter out the season ID to be deleted
        updated_data = [entry for entry in self.list if entry[0] != str(season_id)]

        if len(updated_data) == len(self.list):
            raise ValueError("Season ID not found in watchlist")

        self.list = deepcopy(updated_data)
        self._write_watchlist()
        printers.done(f"{season_id} is removed from watchlist")
        return updated_data
