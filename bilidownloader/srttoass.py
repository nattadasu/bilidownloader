"""SRT to ASS subtitle converter for bilidownloader.

This module provides functionality to convert SRT subtitle files to ASS format
with custom styling and proper font management integration.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from yt_dlp.postprocessor import PostProcessor


class SRTToASSConverter(PostProcessor):
    """A yt-dlp post-processor for converting SRT subtitles to ASS format.

    This class converts SRT subtitle files to ASS format using ffmpeg,
    applies custom styling, and ensures proper font attachment for mkv files.
    """

    # Default ASS style specification
    DEFAULT_STYLE = (
        "Style: dialogue,Noto Sans,80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,4,1.2,2,153,153,64,1"
    )
    DEFAULT_THAI_STYLE = (
        "Style: dialogue,Arial,80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,4,1.2,2,153,153,64,1"
    )

    def __init__(self, *args, **kwargs):
        """Initialize the SRT to ASS converter.

        Args:
            *args: Arguments passed to parent PostProcessor
            **kwargs: Keyword arguments passed to parent PostProcessor
        """
        super().__init__(*args, **kwargs)

    def _ass_time_to_seconds(self, time_str: str) -> float:
        """Convert ASS time format to seconds.

        Args:
            time_str: Time string in ASS format (H:MM:SS.CC)

        Returns:
            Time in seconds as a float
        """
        parts = time_str.split(":")
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds_parts = parts[2].split(".")
        seconds = int(seconds_parts[0])
        centiseconds = int(seconds_parts[1]) if len(seconds_parts) > 1 else 0

        return hours * 3600 + minutes * 60 + seconds + centiseconds / 100.0

    def _seconds_to_ass_time(self, seconds: float) -> str:
        """Convert seconds to ASS time format.

        Args:
            seconds: Time in seconds as a float

        Returns:
            Time string in ASS format (H:MM:SS.CC)
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centiseconds = int((seconds % 1) * 100)

        return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"

    def _fill_three_frame_gaps(
        self, events: List[Tuple[str, str, str]]
    ) -> List[Tuple[str, str, str]]:
        """Fill gaps between subtitle lines if they are exactly 3 frames apart.

        Assumes 23.976/24 fps for frame duration calculation.
        Adjusts the end time of the current line to meet the start time of the next line.

        Args:
            events: List of tuples (start_time, end_time, text) in ASS format

        Returns:
            List of tuples with adjusted end times
        """
        if len(events) <= 1:
            return events

        # 3 frames at 24 fps = 3/24 = 0.125 seconds (12.5 centiseconds)
        # 3 frames at 23.976 fps = 3/23.976 = 0.125125 seconds (12.5125 centiseconds)
        # Use a tolerance of 1 centisecond to account for precision loss
        three_frames_24fps = 3.0 / 24.0  # 0.125
        three_frames_23976fps = 3.0 / 23.976  # 0.125125
        tolerance = 0.01  # 1 centisecond tolerance

        adjusted_events = []
        for i in range(len(events)):
            start_time, end_time, text = events[i]

            # Check if there's a next event to compare with
            if i < len(events) - 1:
                next_start_time = events[i + 1][0]

                # Convert times to seconds for calculation
                current_end_seconds = self._ass_time_to_seconds(end_time)
                next_start_seconds = self._ass_time_to_seconds(next_start_time)

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

            adjusted_events.append((start_time, end_time, text))

        return adjusted_events

    def _parse_srt_time(self, time_str: str) -> str:
        """Convert SRT time format to ASS time format.

        Args:
            time_str: Time string in SRT format (HH:MM:SS,mmm)

        Returns:
            Time string in ASS format (H:MM:SS.mm)
        """
        # Convert SRT format "HH:MM:SS,mmm" to ASS format "H:MM:SS.mm"
        time_str = time_str.replace(",", ".")

        # Split into parts to handle hour formatting correctly
        parts = time_str.split(":")
        if len(parts) == 3:
            # Remove leading zero from hours only (not the entire string)
            hours = (
                parts[0].lstrip("0") or "0"
            )  # Keep at least one zero if hours is "00"
            # Truncate milliseconds to 2 digits for ASS format
            seconds_ms = parts[2]
            if "." in seconds_ms:
                seconds, ms = seconds_ms.split(".")
                ms = ms[:2]  # Take only first 2 digits of milliseconds
                parts[2] = f"{seconds}.{ms}"
            time_str = f"{hours}:{parts[1]}:{parts[2]}"

        return time_str

    def _convert_srt_to_ass_content(
        self, srt_content: str, style: str = DEFAULT_STYLE
    ) -> str:
        """Convert SRT content to ASS format.

        Args:
            srt_content: The content of the SRT file as a string

        Returns:
            The converted ASS content as a string
        """
        # ASS file header
        ass_header = """[Script Info]
Title: Modified with github:nattadasu/bilidownloader (converted from SRT)
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{style}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".format(style=style)

        # Parse SRT content
        srt_pattern = re.compile(
            r"(\d+)\s*\n"  # Subtitle number
            r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n"  # Time
            r"((?:.*\n?)*?)\s*(?=\n\d+\s*\n|\n*$)",  # Text content
            re.MULTILINE,
        )

        events = []
        for match in srt_pattern.finditer(srt_content):
            _, start_time, end_time, text = match.groups()

            # Convert times to ASS format
            ass_start = self._parse_srt_time(start_time)
            ass_end = self._parse_srt_time(end_time)

            # Clean up text - remove extra newlines and convert HTML tags
            text = text.strip()
            text = text.replace("<i>", "{\\i1}")
            text = text.replace("</i>", "{\\i0}")
            text = text.replace("<b>", "{\\b1}")
            text = text.replace("</b>", "{\\b0}")
            text = text.replace("<u>", "{\\u1}")
            text = text.replace("</u>", "{\\u0}")
            text = re.sub(r"<[^>]+>", "", text)  # Remove any unsupported HTML tags
            text = text.replace("\n", "\\N")  # Convert newlines to ASS format

            events.append((ass_start, ass_end, text))

        # Fill 3-frame gaps between subtitle lines
        events = self._fill_three_frame_gaps(events)

        # Create ASS dialogue lines
        event_lines = [
            f"Dialogue: 0,{start},{end},dialogue,,0,0,0,,{text}"
            for start, end, text in events
        ]

        return ass_header + "\n".join(event_lines)

    def _convert_srt_file(self, srt_path: Path) -> Optional[Path]:
        """Convert a single SRT file to ASS format.

        Args:
            srt_path: Path to the SRT file to convert

        Returns:
            Path to the converted ASS file, or None if conversion failed
        """
        if not srt_path.exists():
            self.report_error(f"SRT file not found: {srt_path}")
            return None

        ass_path = srt_path.with_suffix(".ass")

        try:
            # Read SRT content
            with open(srt_path, "r", encoding="utf-8-sig") as f:
                srt_content = f.read()

            # Convert to ASS format
            if ".th." in srt_path.name:
                ass_content = self._convert_srt_to_ass_content(
                    srt_content, style=self.DEFAULT_THAI_STYLE
                )
            else:
                ass_content = self._convert_srt_to_ass_content(srt_content)

            # Write ASS file
            with open(ass_path, "w", encoding="utf-8-sig") as f:
                f.write(ass_content)

            # Remove the original SRT file after successful conversion
            try:
                srt_path.unlink()
                self.write_debug(
                    f"Converted {srt_path.name} to {ass_path.name} and removed original SRT file"
                )
            except Exception as e:
                self.write_debug(
                    f"Converted {srt_path.name} to {ass_path.name} but failed to remove SRT file: {e}"
                )

            return ass_path

        except Exception as e:
            self.report_error(f"Failed to convert {srt_path}: {e}")
            return None

    def run(self, info: Dict) -> Tuple[List, Dict]:
        """Run the SRT to ASS conversion process.

        Args:
            info: yt-dlp info dictionary containing file information

        Returns:
            Tuple of (files_to_delete, updated_info)
        """
        self.to_screen("Converting SRT subtitles to ASS format")

        # Get subtitle file paths from yt-dlp metadata
        file_paths: Dict[str, str] = info.get("__files_to_move", {})
        if not file_paths:
            self.write_debug("No subtitle files found in metadata")
            return [], info

        converted_files = []
        fonts_found = set()

        # Create a copy of the items to avoid modifying dict during iteration
        file_paths_items = list(file_paths.items())

        for original_path, current_path in file_paths_items:
            current_file = Path(current_path)

            # Only process SRT files
            if not current_file.suffix.lower() == ".srt":
                continue

            self.write_debug(f"Converting SRT file: {current_file}")

            # Convert SRT to ASS
            if ".th." in current_file.name:
                fonts_found.add("Arial")
            else:
                fonts_found.add("Noto Sans")
            ass_file = self._convert_srt_file(current_file)
            if ass_file:
                converted_files.append(ass_file)

                # Update file paths in info dict
                new_original = original_path.replace(".srt", ".ass")
                file_paths[new_original] = str(ass_file)

                # Remove old SRT entry
                if original_path in file_paths:
                    del file_paths[original_path]

                self.write_debug(
                    f"Updated file mapping: {original_path} -> {new_original}"
                )

        # Also update any other subtitle-related fields in info
        if "requested_subtitles" in info:
            for lang, sub_info in info["requested_subtitles"].items():
                if sub_info and "filepath" in sub_info:
                    filepath = sub_info["filepath"]
                    if filepath.endswith(".srt"):
                        # Check if we converted this file
                        for converted_file in converted_files:
                            if converted_file.stem == Path(filepath).stem:
                                sub_info["filepath"] = str(converted_file)
                                self.write_debug(
                                    f"Updated requested_subtitles: {filepath} -> {converted_file}"
                                )
                                break

        if converted_files:
            # Save fonts list for later use by font manager
            fonts_json_path = Path("fonts.json")
            try:
                import json

                # get existing fonts array, if any
                if fonts_json_path.exists():
                    with open(fonts_json_path, "r", encoding="utf-8") as f:
                        existing_fonts = json.load(f)
                        fonts_found = list(set(fonts_found) | set(existing_fonts))
                with open(fonts_json_path, "w", encoding="utf-8") as f:
                    json.dump(sorted(list(fonts_found)), f, indent=2)
                self.to_screen(f"Font list saved to {fonts_json_path}")
            except Exception as e:
                self.report_error(f"Failed to save fonts.json: {e}")

            self.to_screen(
                f"Successfully converted {len(converted_files)} SRT files to ASS format"
            )

        return [], info
