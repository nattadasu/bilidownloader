"""
History migration utility - handles one-time migration from old to new format
"""

import re
from html import unescape
from re import search as rsearch
from re import sub as rsub
from time import sleep
from typing import Dict, List

from bilidownloader.cli.options import (
    BinaryPaths,
    DownloadOptions,
    FileConfig,
    PostProcessingOptions,
)
from bilidownloader.commons.alias import SERIES_ALIASES
from bilidownloader.commons.ui import prn_done, prn_error, prn_info

# Constants for TSV format
HEAD = "Timestamp\tSeries ID\tSeries Title\tEpisode Index\tEpisode ID"
SEP = "\t"


class HistoryMigrator:
    """Handles migration from old URL-based format to new TSV format"""

    def __init__(self, repository):
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
        is_old_format = self.repository.is_old_format(data)

        if is_old_format:
            prn_info("Migrating history from old URL format to new TSV format...")
            new_data = self._convert_old_format_to_tsv(data)

            # Update path to new format file if using old path
            if self.repository.path.name == "history.txt":
                new_path = self.repository.path.parent / "history.v2.tsv"
                self.repository.path = new_path

            self.repository._write_file_lines(new_data)
            prn_info("Migration completed successfully")
        elif not has_header:
            prn_info("Adding header to history file")
            new_data = [HEAD] + data
            self.repository._write_file_lines(new_data)

    def _convert_old_format_to_tsv(self, urls: List[str]) -> List[str]:
        """Convert old URL-only format to TSV format with metadata"""
        from alive_progress import alive_bar

        new_data = [HEAD]
        pattern = re.compile(r"play/(\d+)/(\d+)")
        total_urls = len([u for u in urls if u.strip()])

        if total_urls == 0:
            return new_data

        prn_info(f"Migrating {total_urls} entries to new format...")
        prn_info("Fetching metadata from yt-dlp (this may take a while)...")

        try:
            from bilidownloader.downmux.orchestrator import BiliProcess

            extractor = BiliProcess(
                file_config=FileConfig(),
                download_options=DownloadOptions(),
                post_processing_options=PostProcessingOptions(),
                binary_paths=BinaryPaths(),
            )
            use_ytdlp = True
        except Exception:
            use_ytdlp = False
            prn_info("Fallback to API-based metadata fetching")

        failed_entries = []

        with alive_bar(total_urls, title="Migrating", bar="smooth") as bar:
            for url in urls:
                url = url.strip()
                if not url:
                    continue

                regmatch = pattern.search(url)
                if regmatch:
                    series_id = regmatch.group(1)
                    episode_id = regmatch.group(2)
                    series_title = f"Series {series_id}"
                    episode_idx = ""
                    extraction_failed = False

                    if use_ytdlp:
                        try:
                            info = extractor._get_video_info(url)
                            if info and isinstance(info, dict):
                                series_title = self._extract_series_title(
                                    info, url, extractor
                                )
                                episode_num = info.get("episode_number", "")
                                if episode_num:
                                    episode_idx = str(episode_num)
                            sleep(0.5)
                        except Exception as e:
                            extraction_failed = self._handle_extraction_error(
                                e, url, series_title
                            )
                            sleep(0.5)

                    if series_id in SERIES_ALIASES:
                        series_title = SERIES_ALIASES[series_id]

                    if extraction_failed:
                        failed_entries.append(
                            {
                                "url": url,
                                "series_id": series_id,
                                "episode_id": episode_id,
                                "series_title": series_title,
                                "episode_idx": episode_idx,
                            }
                        )

                    entry = f"0{SEP}{series_id}{SEP}{series_title}{SEP}{episode_idx}{SEP}{episode_id}"
                    new_data.append(entry)

                bar()

        prn_info("Migration complete!")

        if failed_entries:
            self._handle_failed_entries(failed_entries, new_data, extractor, use_ytdlp)

        return new_data

    def _extract_series_title(self, info: Dict, url: str, extractor) -> str:
        """Extract series title from metadata"""
        series_title = info.get("series", None)
        if not series_title or series_title == "":
            try:
                from bilidownloader.apis.api import BiliHtml

                html = BiliHtml(cookie_path=extractor.cookie, user_agent="Mozilla/5.0")
                resp = html.get(url)
                title_match = rsearch(
                    r"<title>(.*)</title>",
                    resp.content.decode("utf-8"),
                    re.IGNORECASE,
                )
                if title_match:
                    series_title = rsub(
                        r"\s+(?:E\d+|PV\d*|SP\d*|OVA\d*).*$",
                        "",
                        title_match.group(1),
                    )
                    series_title = unescape(series_title).strip()
            except Exception:
                episode_title = info.get("title", "")
                if episode_title and " - " in episode_title:
                    series_title = rsub(r"^E\d+\s*-\s*", "", episode_title).strip()
                else:
                    series_title = info.get("series", "Series Unknown")
        if not series_title or series_title == "":
            series_title = "Series Unknown"
        return series_title

    def _handle_extraction_error(
        self, error: Exception, url: str, series_title: str
    ) -> bool:
        """Handle errors during metadata extraction"""
        error_str = str(error).lower()
        if any(
            keyword in error_str
            for keyword in [
                "geo restriction",
                "not available",
                "video is not available",
                "geo-restriction",
                "georestriction",
                "unavailable",
            ]
        ):
            prn_error(f"Unreachable video (geo-restricted/removed): {url}")
            return True
        else:
            prn_error(f"Failed to fetch metadata for: {url}")
            return True

    def _handle_failed_entries(
        self,
        failed_entries: List[Dict],
        new_data: List[str],
        extractor,
        use_ytdlp: bool,
    ) -> None:
        """Handle failed entries interactively"""
        import survey

        prn_info(f"\n{len(failed_entries)} entries had issues during migration.")
        try:
            choice = survey.routines.select(
                "How would you like to handle these entries? ",
                options=[
                    "Keep as is (use fallback titles)",
                    "Retry fetching metadata",
                    "Manually provide series titles",
                ],
            )

            if choice == "Retry fetching metadata":
                prn_info("\nRetrying failed entries...")
                self._retry_failed_entries(
                    failed_entries, new_data, extractor, use_ytdlp
                )
            elif choice == "Manually provide series titles":
                prn_info("\nManually updating series titles...")
                self._manually_update_entries(failed_entries, new_data)
        except (survey.widgets.Escape, KeyboardInterrupt):
            prn_info("Keeping entries as is.")

    def _retry_failed_entries(
        self,
        failed_entries: List[Dict],
        new_data: List[str],
        extractor,
        use_ytdlp: bool,
    ) -> None:
        """Retry fetching metadata for failed entries"""
        from time import sleep

        for idx, entry in enumerate(failed_entries, 1):
            prn_info(f"\nRetrying entry {idx}/{len(failed_entries)}: {entry['url']}")

            series_title = entry["series_title"]
            episode_idx = entry["episode_idx"]

            if use_ytdlp:
                try:
                    info = extractor._get_video_info(entry["url"])
                    if info and isinstance(info, dict):
                        series_title = self._extract_series_title(
                            info, entry["url"], extractor
                        )
                        episode_num = info.get("episode_number", "")
                        if episode_num:
                            episode_idx = str(episode_num)

                    prn_done(f"Successfully fetched: {series_title}")
                    sleep(0.5)
                except Exception as e:
                    prn_error(f"Retry failed: {str(e)}")
                    sleep(0.5)

            if entry["series_id"] in SERIES_ALIASES:
                series_title = SERIES_ALIASES[entry["series_id"]]

            self._update_entry_in_data(
                new_data,
                entry["series_id"],
                entry["episode_id"],
                series_title,
                episode_idx,
            )

    def _manually_update_entries(
        self, failed_entries: List[Dict], new_data: List[str]
    ) -> None:
        """Manually update series titles for failed entries"""
        import survey

        for idx, entry in enumerate(failed_entries, 1):
            prn_info(f"\nEntry {idx}/{len(failed_entries)}")
            prn_info(f"URL: {entry['url']}")
            prn_info(
                f"Series ID: {entry['series_id']}, Episode ID: {entry['episode_id']}"
            )
            prn_info(f"Current title: {entry['series_title']}")

            try:
                new_title = survey.routines.input(
                    "Enter series title (or press Enter to keep current):",
                    default=entry["series_title"],
                )

                if new_title and new_title.strip():
                    self._update_entry_in_data(
                        new_data,
                        entry["series_id"],
                        entry["episode_id"],
                        new_title.strip(),
                        entry["episode_idx"],
                    )
                    prn_done(f"Updated to: {new_title.strip()}")
            except (survey.widgets.Escape, KeyboardInterrupt):
                prn_info("Skipping remaining entries...")
                break

    def _update_entry_in_data(
        self,
        new_data: List[str],
        series_id: str,
        episode_id: str,
        series_title: str,
        episode_idx: str,
    ) -> None:
        """Update an entry in the data list"""
        for i, line in enumerate(new_data):
            if line.startswith("Timestamp"):
                continue
            parts = line.split(SEP)
            if len(parts) >= 5 and parts[1] == series_id and parts[4] == episode_id:
                new_data[i] = (
                    f"0{SEP}{series_id}{SEP}{series_title}{SEP}{episode_idx}{SEP}{episode_id}"
                )
                break
