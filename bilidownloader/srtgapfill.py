"""SRT gap filler for bilidownloader.

This module provides functionality to fill 3-frame gaps in SRT subtitle files
to prevent frame jitter during video playback.
"""

import re
from pathlib import Path
from typing import Dict, List, Tuple

from yt_dlp.postprocessor import PostProcessor


class SRTGapFiller(PostProcessor):
    """A yt-dlp post-processor for filling 3-frame gaps in SRT subtitles.

    This class processes SRT subtitle files to fill gaps between lines
    that are exactly 3 frames apart to prevent frame jitter.
    """

    def __init__(self, *args, **kwargs):
        """Initialize the SRT gap filler.

        Args:
            *args: Arguments passed to parent PostProcessor
            **kwargs: Keyword arguments passed to parent PostProcessor
        """
        super().__init__(*args, **kwargs)

    def _srt_time_to_seconds(self, time_str: str) -> float:
        """Convert SRT time format to seconds.

        Args:
            time_str: Time string in SRT format (HH:MM:SS,mmm)

        Returns:
            Time in seconds as a float
        """
        time_str = time_str.replace(",", ".")
        parts = time_str.split(":")
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds_parts = parts[2].split(".")
        seconds = int(seconds_parts[0])
        milliseconds = int(seconds_parts[1]) if len(seconds_parts) > 1 else 0

        return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0

    def _seconds_to_srt_time(self, seconds: float) -> str:
        """Convert seconds to SRT time format.

        Args:
            seconds: Time in seconds as a float

        Returns:
            Time string in SRT format (HH:MM:SS,mmm)
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        milliseconds = int((seconds % 1) * 1000)

        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"

    def _fill_three_frame_gaps_srt(self, srt_content: str) -> str:
        """Fill gaps between subtitle lines if they are exactly 3 frames apart.

        Assumes 23.976/24 fps for frame duration calculation.
        Adjusts the end time of the current line to meet the start time of the next line.

        Args:
            srt_content: The content of the SRT file as a string

        Returns:
            The modified SRT content as a string
        """
        # Parse SRT content
        srt_pattern = re.compile(
            r"(\d+)\s*\n"  # Subtitle number
            r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n"  # Time
            r"((?:.*\n?)*?)\s*(?=\n\d+\s*\n|\n*$)",  # Text content
            re.MULTILINE,
        )

        events = []
        for match in srt_pattern.finditer(srt_content):
            number, start_time, end_time, text = match.groups()
            events.append((int(number), start_time, end_time, text.strip()))

        if len(events) <= 1:
            return srt_content

        # 3 frames at 24 fps = 3/24 = 0.125 seconds
        # 3 frames at 23.976 fps = 3/23.976 = 0.125125 seconds
        # Use a tolerance of 1 millisecond to account for precision
        three_frames_24fps = 3.0 / 24.0  # 0.125
        three_frames_23976fps = 3.0 / 23.976  # 0.125125
        tolerance = 0.001  # 1 millisecond tolerance

        adjusted_events = []
        for i in range(len(events)):
            number, start_time, end_time, text = events[i]

            # Check if there's a next event to compare with
            if i < len(events) - 1:
                next_start_time = events[i + 1][1]

                # Convert times to seconds for calculation
                current_end_seconds = self._srt_time_to_seconds(end_time)
                next_start_seconds = self._srt_time_to_seconds(next_start_time)

                # Calculate the gap
                gap = next_start_seconds - current_end_seconds

                # Check if gap is approximately 3 frames (at 24 or 23.976 fps)
                if (
                    abs(gap - three_frames_24fps) <= tolerance
                    or abs(gap - three_frames_23976fps) <= tolerance
                ):
                    # Fill the gap by extending the end time to the next start time
                    end_time = next_start_time
                    self.write_debug(
                        f"  Filled 3-frame gap: extended line ending at "
                        f"{current_end_seconds:.3f}s to {next_start_seconds:.3f}s"
                    )

            adjusted_events.append((number, start_time, end_time, text))

        # Rebuild SRT content
        srt_lines = []
        for number, start_time, end_time, text in adjusted_events:
            srt_lines.append(f"{number}\n{start_time} --> {end_time}\n{text}\n")

        return "\n".join(srt_lines)

    def _process_srt_file(self, srt_path: Path) -> bool:
        """Process a single SRT file to fill 3-frame gaps.

        Args:
            srt_path: Path to the SRT file to process

        Returns:
            True if processing was successful, False otherwise
        """
        if not srt_path.exists():
            self.report_error(f"SRT file not found: {srt_path}")
            return False

        try:
            # Read SRT content
            with open(srt_path, "r", encoding="utf-8-sig") as f:
                srt_content = f.read()

            # Fill gaps
            modified_content = self._fill_three_frame_gaps_srt(srt_content)

            # Write back to file
            with open(srt_path, "w", encoding="utf-8-sig") as f:
                f.write(modified_content)

            self.write_debug(f"Processed {srt_path.name} for 3-frame gaps")
            return True

        except Exception as e:
            self.report_error(f"Failed to process {srt_path}: {e}")
            return False

    def run(self, info: Dict) -> Tuple[List, Dict]:
        """Run the SRT gap filling process.

        Args:
            info: yt-dlp info dictionary containing file information

        Returns:
            Tuple of (files_to_delete, updated_info)
        """
        self.to_screen("Filling 3-frame gaps in SRT subtitles")

        # Get subtitle file paths from yt-dlp metadata
        file_paths: Dict[str, str] = info.get("__files_to_move", {})
        if not file_paths:
            self.write_debug("No subtitle files found in metadata")
            return [], info

        processed_count = 0

        for original_path, current_path in file_paths.items():
            current_file = Path(current_path)

            # Only process SRT files
            if not current_file.suffix.lower() == ".srt":
                continue

            self.write_debug(f"Processing SRT file: {current_file}")

            # Fill gaps
            if self._process_srt_file(current_file):
                processed_count += 1

        if processed_count > 0:
            self.to_screen(
                f"Successfully processed {processed_count} SRT files for 3-frame gaps"
            )

        return [], info
