"""
Subtitle reporter - displays found subtitles during download
"""

from typing import Any, Dict, List

from rich import print as rprint
from rich.table import Table, box
from yt_dlp.postprocessor import PostProcessor

from bilidownloader.commons.utils import langcode_to_str


class SubtitleReporter(PostProcessor):
    """Reports found subtitles in a pretty format during download"""

    def __init__(self, downloader=None):
        super().__init__(downloader)
        self._reported = False

    def run(self, info: Dict[str, Any]) -> tuple[List[str], Dict[str, Any]]:
        """Report subtitles if available"""
        if self._reported:
            return [], info

        subtitles = info.get("subtitles", {})
        if not subtitles:
            return [], info

        # Create a table for subtitles matching chapter marker style
        table = Table(
            show_header=True,
            header_style="bold magenta",
            title="📝 Found Subtitles",
            box=box.ROUNDED,
        )

        table.add_column("Code", style="yellow", no_wrap=True)
        table.add_column("Name", style="green")
        table.add_column("Format", style="blue")

        # Sort languages for consistent display
        sorted_langs = sorted(subtitles.keys())

        for lang_code in sorted_langs:
            lang_name = langcode_to_str(lang_code)
            sub_list = subtitles[lang_code]

            # Get available formats
            formats: List[str] = []
            if isinstance(sub_list, list):
                formats = [sub.get("ext", "unknown") for sub in sub_list]
            formats_str = ", ".join(sorted(set(formats))) if formats else "unknown"

            table.add_row(lang_code, lang_name, formats_str)

        # Display the table
        rprint(table)

        self._reported = True
        return [], info
