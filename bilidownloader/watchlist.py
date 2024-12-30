from copy import deepcopy
from os import path as opath
from pathlib import Path
from typing import List, Literal, Optional, Tuple, Union

try:
    from api import BiliApi
    from common import (
        DEFAULT_WATCHLIST,
        DataExistError,
        prn_done,
        prn_error,
        prn_info,
    )
except ImportError:
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
        silent: bool = False,
    ):
        self.path = path
        self.list: List[Tuple[str, str]] = []
        self.cookie: Optional[Path] = None
        self.silent = silent

        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not opath.exists(self.path):
            prn_info(f"Watchlist file can't be found on {str(path)}, creating...")
            with open(self.path, "w+", encoding="utf8") as file:
                file.write("")
        if cookie_path:
            self.cookie = Path(cookie_path)
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

    def _remote_update(
        self, season_id: Union[str, int], action: Literal["add", "del"]
    ) -> None:
        """Update watchlist on Bilibili's server"""
        # Don't perform the action if silent mode is enabled
        if self.silent:
            return
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
        """Prints the action to the console"""
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
        self, season_id: Union[str, int], title: str, remote_update: Optional[bool] = False
    ) -> List[Tuple[str, str]]:
        """Writes a season ID to the watchlist, raises an error if it already exists."""
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
        """Deletes a season ID from the watchlist. Raises an error if the season ID is not found."""
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
