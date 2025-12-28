from pathlib import Path
from typing import List, Literal, Optional, Tuple, Union

from bilidownloader.apis.api import BiliApi
from bilidownloader.commons.alias import SERIES_ALIASES
from bilidownloader.commons.constants import DEFAULT_WATCHLIST
from bilidownloader.commons.ui import prn_done, prn_error, prn_info
from bilidownloader.commons.utils import DataExistError
from bilidownloader.watchlist.migration import WatchlistMigrator
from bilidownloader.watchlist.repository import WatchlistRepository


class Watchlist:
    """Main interface for watchlist management"""

    def __init__(
        self,
        path: Path = DEFAULT_WATCHLIST,
        cookie_path: Optional[Path] = None,
        add_header: bool = True,
    ):
        self.repo = WatchlistRepository(path, add_header)
        self.cookie: Optional[Path] = None
        self.repo.ensure_file_exists()

        if cookie_path:
            self.cookie = Path(cookie_path)

        migrator = WatchlistMigrator(self.repo)
        migrator.migrate_if_needed()
        self.read_watchlist()

    @property
    def path(self) -> Path:
        """Get the path to the watchlist file"""
        return self.repo.path

    @path.setter
    def path(self, value: Path) -> None:
        """Set the path to the watchlist file"""
        self.repo.path = value

    @property
    def list(self) -> List[Tuple[str, str]]:
        """Get the watchlist list"""
        return self.repo.list

    def read_watchlist(self) -> List[Tuple[str, str]]:
        """Reads the watchlist from the specified file path.

        Returns:
            List[Tuple[str, str]]: A list of tuples containing season ID and title
        """
        return self.repo.read()

    def search_watchlist(
        self,
        season_id: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Optional[Tuple[str, str]]:
        """
        Searches for a show in the watchlist.

        Args:
            season_id (Optional[str]): Search by season ID
            title (Optional[str]): Search by title (case-insensitive)

        Returns:
            Optional[Tuple[str, str]]: First matching entry or None if not found
        """
        for existing_id, existing_title in self.list:
            if season_id and existing_id == str(season_id):
                return (existing_id, existing_title)
            if title and title.lower() in existing_title.lower():
                return (existing_id, existing_title)
        return None

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
        if self.repo.check_exists(season_id_str):
            raise DataExistError("Show has been added previously to watchlist")

        if remote_update:
            self._remote_update(season_id, "add")

        self.repo.add_entry(season_id_str, title.strip())
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
        entry_to_delete = self.search_watchlist(season_id=str(season_id))
        if not entry_to_delete:
            raise ValueError(f"Season ID {season_id} not found in watchlist")

        if remote_update:
            self._remote_update(season_id, "del")

        # Remove the entry
        season_id_str = str(season_id)
        self.repo.remove_entry(season_id_str)

        self._prn_rw("delete", season_id, entry_to_delete[1])
        return self.list

    def pull_favorites(self) -> None:
        """
        Pull all favorites from Bilibili and add them to the watchlist.
        """
        if not self.cookie:
            raise ValueError("Cookie path must be set to perform this action")

        api = BiliApi(cookie_path=self.cookie)
        pn = 1
        ps = 20
        total_added = 0

        prn_info("Fetching favorites from Bilibili...")

        while True:
            try:
                resp = api.get_favorites(pn=pn, ps=ps)
                if not resp.data.cards:
                    break

                for card in resp.data.cards:
                    try:
                        self.add_watchlist(
                            card.season_id, card.title, remote_update=False
                        )
                        total_added += 1
                    except DataExistError:
                        pass
                    except Exception as e:
                        prn_error(f"Failed to add {card.title} ({card.season_id}): {e}")

                if not resp.data.has_more:
                    break
                pn += 1
            except Exception as e:
                prn_error(f"Failed to fetch favorites page {pn}: {e}")
                break

        if total_added > 0:
            prn_done(f"Finished pulling favorites. Added {total_added} new shows.")
        else:
            prn_info("No new favorites found.")
