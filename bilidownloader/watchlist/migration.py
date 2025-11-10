"""
Watchlist migration utility - handles one-time migration from old to new format
"""

from typing import List, Optional, Tuple

from bilidownloader.commons.ui import prn_info
from bilidownloader.watchlist.repository import WatchlistRepository

# Constants for TSV format
HEAD = "ID\tTitle"
SEP = "\t"
C_SEP = ", "


class WatchlistMigrator:
    """Handles migration from old comma-separated format to new TSV format"""

    def __init__(self, repository: WatchlistRepository):
        self.repository = repository

    def migrate_if_needed(self) -> None:
        """Check if migration is needed and perform it"""
        if (
            not self.repository.path.exists()
            or self.repository.path.stat().st_size == 0
        ):
            self.repository._create_empty_file_with_header()
            return

        data = self.repository._read_file_lines()
        if not data:
            self.repository._create_empty_file_with_header()
            return

        has_header = self.repository.has_header(data)

        new_data, migrated = self._process_migration_data(data, has_header)

        if self._should_write_file(migrated, has_header, new_data):
            self._write_migration_messages(migrated, has_header)
            self.repository._write_file_lines(new_data)

    def _process_migration_data(
        self, data: List[str], has_header: bool
    ) -> Tuple[List[str], bool]:
        """Process data for migration and return new data and migration status"""
        new_data = []
        migrated = False

        # Handle header
        if self.repository.add_header and not has_header:
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
        return migrated or (
            self.repository.add_header and not has_header and len(new_data) > 1
        )

    def _write_migration_messages(self, migrated: bool, has_header: bool) -> None:
        """Write appropriate migration messages"""
        if migrated:
            prn_info("Migrating watchlist file to new format (tab-separated)")
        if self.repository.add_header and not has_header:
            prn_info("Adding header to watchlist file")
