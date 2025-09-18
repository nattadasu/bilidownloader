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

    def __init__(self, *args, **kwargs):
        """Initialize the SRT to ASS converter.

        Args:
            *args: Arguments passed to parent PostProcessor
            **kwargs: Keyword arguments passed to parent PostProcessor
        """
        super().__init__(*args, **kwargs)

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

    def _convert_srt_to_ass_content(self, srt_content: str) -> str:
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
""".format(style=self.DEFAULT_STYLE)

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

            # Create ASS dialogue line
            event_line = f"Dialogue: 0,{ass_start},{ass_end},dialogue,,0,0,0,,{text}"
            events.append(event_line)

        return ass_header + "\n".join(events)

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
            # Collect fonts from converted ASS files
            fonts_found = ["Noto Sans"]

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
