"""SRT gap filler post-processor for yt-dlp.

Fills distracting flicker gaps in SRT subtitle files to improve readability.
"""

from pathlib import Path
from typing import Dict, List, Tuple

from yt_dlp.postprocessor import PostProcessor

from bilidownloader.subtitles.gap_filler import FlickerFiller
from bilidownloader.subtitles.subtitle_io import SubtitleIO


class SRTGapFiller(PostProcessor):
    """A yt-dlp post-processor for filling flicker gaps in SRT subtitles."""

    def __init__(self, *args, **kwargs):
        """Initialize the SRT gap filler."""
        super().__init__(*args, **kwargs)
        self.gap_filler = FlickerFiller()

    def _process_srt_file(self, srt_path: Path) -> Tuple[bool, int]:
        """Process a single SRT file to fill flicker gaps.

        Args:
            srt_path: Path to the SRT file to process

        Returns:
            Tuple of (success: bool, gaps_filled: int)
        """
        if not srt_path.exists():
            self.report_error(f"SRT file not found: {srt_path}")
            return False, 0

        try:
            # Load subtitles
            subs = SubtitleIO.load(srt_path)

            # Extract events and apply gap filler
            events = SubtitleIO.extract_events(subs)
            adjusted_events, gaps_filled = self.gap_filler.fill_flicker_gaps(events)

            # Update events with adjusted times
            SubtitleIO.update_events(subs, adjusted_events)

            # Write back to file
            SubtitleIO.save(subs, srt_path)

            if gaps_filled > 0:
                self.write_debug(
                    f"Processed {srt_path.name}: filled {gaps_filled} gap(s)"
                )
            else:
                self.write_debug(f"Processed {srt_path.name}: no gaps filled")
            return True, gaps_filled

        except Exception as e:
            self.report_error(f"Failed to process {srt_path}: {e}")
            return False, 0

    def run(self, info: Dict) -> Tuple[List, Dict]:
        """Run the SRT gap filling process.

        Args:
            info: yt-dlp info dictionary containing file information

        Returns:
            Tuple of (files_to_delete, updated_info)
        """
        self.to_screen("Filling flicker gaps (4 frames @24fps ~167ms) in SRT subtitles")

        # Get subtitle file paths from yt-dlp metadata
        file_paths: Dict[str, str] = info.get("__files_to_move", {})
        if not file_paths:
            self.write_debug("No subtitle files found in metadata")
            return [], info

        processed_count = 0
        total_gaps_filled = 0

        for original_path, current_path in file_paths.items():
            current_file = Path(current_path)

            # Only process SRT files
            if not current_file.suffix.lower() == ".srt":
                continue

            self.write_debug(f"Processing SRT file: {current_file}")

            # Fill gaps
            success, gaps_filled = self._process_srt_file(current_file)
            if success:
                processed_count += 1
                total_gaps_filled += gaps_filled

        if processed_count > 0:
            self.to_screen(
                f"Processed {processed_count} SRT file(s), filled {total_gaps_filled} gap(s) total"
            )

        return [], info
