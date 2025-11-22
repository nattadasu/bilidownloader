"""
Subtitle reporter - displays found subtitles during download
"""

from io import StringIO
from typing import Any, Dict, List

from rich.console import Console
from rich.table import Table, box
from yt_dlp.postprocessor import PostProcessor

from bilidownloader.commons.ui import prn_info
from bilidownloader.commons.utils import langcode_to_str

console = Console(highlight=False)


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

        # Sort languages for consistent display
        sorted_langs = sorted(subtitles.keys())

        if len(sorted_langs) == 0:
            return [], info

        # Create a table for subtitles matching chapter marker style
        prn_info("Available subtitles on this release")
        table = Table(
            show_header=True,
            header_style="bold",
            box=box.ROUNDED,
        )

        table.add_column("Code", justify="right", style="yellow", no_wrap=True)
        table.add_column("Name")
        table.add_column("Format", style="purple")

        for lang_code in sorted_langs:
            lang_name = langcode_to_str(lang_code)
            sub_list = subtitles[lang_code]

            # Get available formats
            formats: List[str] = []
            if isinstance(sub_list, list):
                formats = [sub.get("ext", "unknown") for sub in sub_list]
            formats_str = ", ".join(sorted(set(formats))) if formats else "unknown"

            table.add_row(lang_code, lang_name, formats_str)

        # Display the table with console to disable auto-coloring
        # Add 6 space left indent by rendering to string first
        table_str = StringIO()
        temp_console = Console(
            file=table_str, highlight=False, force_terminal=True, width=50
        )
        temp_console.print(table)
        for line in table_str.getvalue().splitlines():
            console.print(f"       {line}")

        self._reported = True
        return [], info
