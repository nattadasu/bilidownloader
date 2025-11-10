from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Optional, Tuple

import platformdirs
import requests as req
from rich import box
from rich.console import Console
from rich.panel import Panel
from semver import Version
from tomllib import loads as tloads

from bilidownloader.metadata import __VERSION__

VERSION_CACHE_FILE = (
    Path(platformdirs.user_cache_dir("bilidownloader")) / "version_cache.json"
)
CACHE_DURATION = timedelta(hours=12)

console = Console()


def _read_cache() -> Optional[Tuple[datetime, Version]]:
    """Reads the version cache file."""
    if not VERSION_CACHE_FILE.exists():
        return None
    try:
        with open(VERSION_CACHE_FILE, "r") as f:
            cache_data = json.load(f)
        cached_time = datetime.fromisoformat(cache_data["timestamp"])
        cached_version = Version.parse(cache_data["version"])
        return cached_time, cached_version
    except (json.JSONDecodeError, KeyError, ValueError):
        # Cache file is corrupted or invalid, delete it
        VERSION_CACHE_FILE.unlink(missing_ok=True)
        return None


def _write_cache(timestamp: datetime, version: Version):
    """Writes the version to the cache file."""
    VERSION_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(VERSION_CACHE_FILE, "w") as f:
        json.dump({"timestamp": timestamp.isoformat(), "version": str(version)}, f)


def check_for_updates() -> bool:
    """Check for an update from upstream's pyproject.toml and display a warning if available."""
    current_version = Version.parse(__VERSION__)
    latest_version = current_version

    cached_data = _read_cache()
    if cached_data:
        cached_time, cached_latest_version = cached_data
        if datetime.now() - cached_time < CACHE_DURATION:
            latest_version = cached_latest_version
            if latest_version > current_version:
                _display_update_warning(latest_version, current_version)
            return latest_version != current_version

    update_url = (
        "https://raw.githubusercontent.com/nattadasu/bilidownloader/main/pyproject.toml"
    )
    try:
        resp = req.get(update_url)
        resp.raise_for_status()
        data = tloads(resp.text)
        latest_version = Version.parse(data["project"]["version"])
        _write_cache(datetime.now(), latest_version)

        if latest_version > current_version:
            _display_update_warning(latest_version, current_version)
    except Exception as err:
        panel = Panel(
            f"Failed to check for an app update, reason: {err}",
            title="Update Check Failed",
            box=box.ROUNDED,
            title_align="left",
            border_style="red",
            expand=False,
        )
        console.print(panel)
        print()
    return latest_version != current_version


def _display_update_warning(latest_version: Version, current_version: Version):
    """Displays an update warning to the console."""
    warn = (
        f"[bold]BiliDownloader[/] has a new version: [blue]{latest_version}[/] "
        f"(Current: [red]{current_version}[/]).\n"
        "Updating is recommended to get the latest features and bug fixes.\n\n"
        "To update, execute [black]`[/][bold]pipx upgrade bilidownloader[black]`[/]"
    )
    panel = Panel(
        warn,
        title="Update Available",
        box=box.ROUNDED,
        title_align="left",
        border_style="yellow",
        expand=False,
    )
    console.print(panel)
    print()
