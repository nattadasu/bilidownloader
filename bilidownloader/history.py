from os import path as opath
from pathlib import Path
from typing import List

from survey import printers

try:
    from common import DEFAULT_HISTORY, DataExistError
except ImportError:
    from bilidownloader.common import DEFAULT_HISTORY, DataExistError


class History:
    def __init__(self, path: Path = DEFAULT_HISTORY):
        self.path = path
        self.list: List[str] = []

        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not opath.exists(self.path):
            printers.info(f"History file can't be found on {str(path)}, creating...")
            with open(self.path, "w+", encoding="utf8") as file:
                file.write("")
        self.read_history()

    def read_history(self) -> List[str]:
        """Reads the history of episode URLs from the specified file path."""
        with open(self.path, "r+", encoding="utf8") as file:
            self.list = [line.strip() for line in file.read().splitlines()]
        return self.list

    def check_history(self, episode_url: str) -> List[str]:
        """Check if the episode was on the history"""
        if episode_url in self.list:
            raise DataExistError("Episode was ripped previously")

        return self.list

    def _write(self, queue: List[str]):
        with open(self.path, "w+", encoding="utf8") as file:
            file.write("\n".join([url for url in queue]) + "\n")

    def write_history(self, episode_url: str) -> List[str]:
        """Writes an episode URL to the history."""
        self.list.append(episode_url)

        self._write(self.list)

        printers.done(f"{episode_url} has beed added to history")

        return self.list
