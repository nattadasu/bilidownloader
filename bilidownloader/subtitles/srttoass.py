"""SRT to ASS converter post-processor for yt-dlp.

Converts SRT subtitle files to ASS format with proper styling and language-specific processing.
"""

import json
import re
from pathlib import Path
from re import search as rsearch
from typing import Dict, List, Optional, Tuple

from yt_dlp.postprocessor import PostProcessor

from bilidownloader.commons.metadata import __VERSION__
from bilidownloader.commons.ui import prn_info
from bilidownloader.commons.utils import langcode_to_str
from bilidownloader.subtitles.arabic_processor import ArabicProcessor
from bilidownloader.subtitles.gap_filler import FlickerFiller
from bilidownloader.subtitles.subtitle_io import SubtitleIO


class SRTToASSConverter(PostProcessor):
    """A yt-dlp post-processor for converting SRT subtitles to ASS format."""

    def __init__(self, *args, **kwargs):
        """Initialize the SRT to ASS converter."""
        super().__init__(*args, **kwargs)
        self.gap_filler = FlickerFiller()

    def _convert_srt_file(
        self, srt_path: Path, play_res_x: int = 1920, play_res_y: int = 1080
    ) -> Tuple[Optional[Path], int]:
        """Convert a single SRT file to ASS format.

        Args:
            srt_path: Path to the SRT file to convert
            play_res_x: Video width resolution for script info (default: 1920)
            play_res_y: Video height resolution for script info (default: 1080)

        Returns:
            Tuple of (ass_file_path or None, gaps_filled_count)
        """
        if not srt_path.exists():
            self.report_error(f"SRT file not found: {srt_path}")
            return None, 0

        ass_path = srt_path.with_suffix(".ass")

        try:
            # Extract language code from filename
            lang_match = rsearch(r"\.([a-z]{2}(?:-[A-Za-z]+)?)\.srt$", srt_path.name)
            lang_code = lang_match.group(1) if lang_match else None

            # Load SRT
            subs = SubtitleIO.load(srt_path)

            # Apply Arabic RTL processing if needed
            if lang_code == "ar":
                for event in subs.events:
                    event.text = ArabicProcessor.process_arabic_subtitle(event.text)

            # Set script info for ASS file
            if not subs.info:
                subs.info = {}
            subs.info["Title"] = (
                f"Modified with github:nattadasu/bilidownloader v{__VERSION__} (converted from SRT)"
            )
            subs.info["ScriptType"] = "v4.00+"
            subs.info["WrapStyle"] = "0"
            subs.info["ScaledBorderAndShadow"] = "yes"
            subs.info["YCbCr Matrix"] = "TV.709"
            subs.info["PlayResX"] = str(play_res_x)
            subs.info["PlayResY"] = str(play_res_y)

            # Apply gap filling
            events = SubtitleIO.extract_events(subs)
            adjusted_events, gaps_filled = self.gap_filler.fill_flicker_gaps(events)
            SubtitleIO.update_events(subs, adjusted_events)

            # Apply styling based on language code
            SubtitleIO.apply_style(subs, lang_code=lang_code)

            # Save as ASS
            SubtitleIO.save(subs, ass_path)

            # Remove the original SRT file after successful conversion
            try:
                srt_path.unlink()
                lang_display = lang_code if lang_code else "unknown"
                if gaps_filled > 0:
                    self.write_debug(f"  [{lang_display}] filled {gaps_filled} gap(s)")
                else:
                    self.write_debug(f"  [{lang_display}] converted")
            except Exception as e:
                self.write_debug(
                    f"Converted {srt_path.name} to {ass_path.name} but failed to remove SRT file: {e}"
                )

            return ass_path, gaps_filled

        except Exception as e:
            self.report_error(f"Failed to convert {srt_path}: {e}")
            return None, 0

    def run(self, info: Dict) -> Tuple[List, Dict]:
        """Run the SRT to ASS conversion process.

        Args:
            info: yt-dlp info dictionary containing file information

        Returns:
            Tuple of (files_to_delete, updated_info)
        """
        # Get subtitle file paths from yt-dlp metadata
        file_paths: Dict[str, str] = info.get("__files_to_move", {})
        if not file_paths:
            self.write_debug("No subtitle files found in metadata")
            return [], info

        # Try to get video resolution from yt-dlp info
        play_res_x = 1920  # Default width
        play_res_y = 1080  # Default height
        if "width" in info and "height" in info and info["width"] and info["height"]:
            play_res_x = int(info["width"])
            play_res_y = int(info["height"])

        lang_names = []
        has_srt_files = False
        for current_path in file_paths.values():
            current_file = Path(current_path)
            if not current_file.suffix.lower() == ".srt":
                continue
            has_srt_files = True
            lang_match = re.search(
                r"\.([a-z]{2}(?:-[A-Za-z]+)?)\.srt$", current_file.name
            )
            if lang_match:
                lang_code = lang_match.group(1)
                lang_names.append(langcode_to_str(lang_code))

        if not has_srt_files:
            self.write_debug("No SRT files to convert")
            return [], info

        # Show conversion message before processing
        if lang_names:
            prn_info(f"Converting SRT to ASS for: {', '.join(lang_names)}")

        converted_files = []
        fonts_found = set()
        total_gaps_filled = 0

        # Create a copy of the items to avoid modifying dict during iteration
        file_paths_items = list(file_paths.items())

        for original_path, current_path in file_paths_items:
            current_file = Path(current_path)

            # Only process SRT files
            if not current_file.suffix.lower() == ".srt":
                continue

            # Detect language and collect required fonts
            lang_match = re.search(
                r"\.([a-z]{2}(?:-[A-Za-z]+)?)\.srt$", current_file.name
            )
            lang_code = lang_match.group(1) if lang_match else None

            if lang_code == "ar":
                fonts_found.add("Noto Naskh Arabic")
            elif lang_code in ("zh-Hans", "zh"):
                fonts_found.add("Noto Sans CJK SC")
            elif lang_code == "zh-Hant":
                fonts_found.add("Noto Sans CJK TC")
            elif lang_code == "th":
                fonts_found.add("Arial")
                fonts_found.add("Arial::Bold")
            else:
                fonts_found.add("Noto Sans")
                fonts_found.add("Noto Sans::Bold")

            ass_file, gaps_filled = self._convert_srt_file(
                current_file, play_res_x, play_res_y
            )
            if ass_file:
                converted_files.append(ass_file)
                total_gaps_filled += gaps_filled

                # Update file paths in info dict
                new_original = original_path.replace(".srt", ".ass")
                file_paths[new_original] = str(ass_file)

                # Remove old SRT entry
                if original_path in file_paths:
                    del file_paths[original_path]

        # Also update any other subtitle-related fields in info
        if "requested_subtitles" in info:
            for lang, sub_info in info["requested_subtitles"].items():
                if not (sub_info and "filepath" in sub_info):
                    continue
                filepath = sub_info["filepath"]
                if not filepath.endswith(".srt"):
                    # Check if we converted this file
                    continue
                for converted_file in converted_files:
                    if converted_file.stem != Path(filepath).stem:
                        continue
                    sub_info["filepath"] = str(converted_file)
                    break

        if converted_files:
            # Save fonts list for later use by font manager
            fonts_json_path = Path("fonts.json")
            try:
                # get existing fonts array, if any
                if fonts_json_path.exists():
                    with open(fonts_json_path, "r", encoding="utf-8") as f:
                        existing_fonts = json.load(f)
                        fonts_found = list(set(fonts_found) | set(existing_fonts))
                with open(fonts_json_path, "w", encoding="utf-8") as f:
                    json.dump(sorted(list(fonts_found)), f, indent=2)
            except Exception as e:
                self.report_error(f"Failed to save fonts.json: {e}")

            self.to_screen(
                f"Converted {len(converted_files)} SRT file(s) to ASS, filled {total_gaps_filled} gap(s) total"
            )

        return [], info
