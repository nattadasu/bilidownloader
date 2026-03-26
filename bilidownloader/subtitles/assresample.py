"""Advanced SubStation Alpha (ASS/SSA) subtitle rescaling post-processor for yt-dlp.

This module provides functionality to rescale ASS/SSA subtitle files by adjusting
font sizes, borders, and shadows, while collecting used fonts and removing unused
styles for optimization.
"""

import json
import re
from math import modf
from pathlib import Path
from re import search as rsearch
from typing import Any, Dict, List, Set, Tuple

import pysubs2
from yt_dlp.postprocessor import PostProcessor

from bilidownloader.commons.ui import prn_info
from bilidownloader.commons.utils import format_log_time
from bilidownloader.subtitles.gap_filler import FlickerFiller
from bilidownloader.subtitles.subtitle_io import SubtitleIO


class SSARescaler(PostProcessor):
    """A yt-dlp post-processor for rescaling ASS/SSA subtitle files.

    This class rescales font sizes, borders, and shadows in ASS/SSA subtitle files
    to improve readability while collecting all used fonts and removing unused styles.
    """

    SIZE_MODIFIER: float = 0.8

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gap_filler = FlickerFiller()

    def _event_time_to_seconds(self, event_time_ms: int) -> float:
        """Convert event time (milliseconds) to seconds."""
        return event_time_ms / 1000.0

    def _add_font_if_new(
        self, font_name: str, all_fonts_found: Set[str], context: str = ""
    ) -> None:
        """Add a font to the collection if it's not already present."""
        if font_name not in all_fonts_found:
            debug_msg = (
                f"  Found new {context}font: '{font_name}'"
                if context
                else f"  Found new font: '{font_name}'"
            )
            self.write_debug(debug_msg)
            all_fonts_found.add(font_name)

    def _add_noto_italic_if_needed(
        self, all_fonts_found: Set[str], context: str
    ) -> None:
        """Add Noto Sans Italic if not already present."""
        if "Noto Sans Italic" not in all_fonts_found:
            self.write_debug(f"  {context}, adding 'Noto Sans::Italic'")
            all_fonts_found.add("Noto Sans::Italic")

    def _add_noto_bold_if_needed(self, all_fonts_found: Set[str], context: str) -> None:
        """Add Noto Sans Bold if not already present."""
        if "Noto Sans Bold" not in all_fonts_found:
            self.write_debug(f"  {context}, adding 'Noto Sans::Bold'")
            all_fonts_found.add("Noto Sans::Bold")

    def _add_noto_bold_italic_if_needed(
        self, all_fonts_found: Set[str], context: str
    ) -> None:
        """Add Noto Sans Bold Italic if not already present."""
        if "Noto Sans Bold Italic" not in all_fonts_found:
            self.write_debug(f"  {context}, adding 'Noto Sans::Bold Italic'")
            all_fonts_found.add("Noto Sans::Bold Italic")

    def _add_arial_italic_if_needed(
        self, all_fonts_found: Set[str], context: str
    ) -> None:
        """Add Arial Italic if not already present."""
        if "Arial Italic" not in all_fonts_found:
            self.write_debug(f"  {context}, adding 'Arial::Italic'")
            all_fonts_found.add("Arial Italic")

    def _add_arial_bold_if_needed(
        self, all_fonts_found: Set[str], context: str
    ) -> None:
        """Add Arial Bold if not already present."""
        if "Arial Bold" not in all_fonts_found:
            self.write_debug(f"  {context}, adding 'Arial::Bold'")
            all_fonts_found.add("Arial Bold")

    def _add_arial_bold_italic_if_needed(
        self, all_fonts_found: Set[str], context: str
    ) -> None:
        """Add Arial Bold Italic if not already present."""
        if "Arial Bold Italic" not in all_fonts_found:
            self.write_debug(f"  {context}, adding 'Arial::Bold Italic'")
            all_fonts_found.add("Arial Bold Italic")

    def _collect_fonts_from_inline_tags(
        self,
        text: str,
        all_fonts_found: Set[str],
        event_index: int,
    ) -> None:
        """Collect font names from inline ASS tags.

        Args:
            text: The text content with inline tags
            all_fonts_found: Set to collect fonts
            event_index: Event index for logging
        """
        fn_pattern = re.compile(r"\\fn([^\\}]+)")
        for match in fn_pattern.finditer(text):
            font_name = match.group(1).strip()
            self._add_font_if_new(font_name, all_fonts_found, "inline ")

    def _rescale_value(self, value_str: str) -> float:
        """Rescale a numeric value by SIZE_MODIFIER.

        Args:
            value_str: String representation of the value

        Returns:
            Rescaled value (int if no fractional part, else float)
        """
        rescaled_value = float(value_str) * self.SIZE_MODIFIER
        fractional_part, _ = modf(rescaled_value)
        return (
            int(rescaled_value) if fractional_part == 0.0 else round(rescaled_value, 2)
        )

    def _rescale_inline_tags(
        self,
        line_text: str,
        event_index: int,
        start_time_ms: int,
        end_time_ms: int,
    ) -> str:
        """Rescale inline ASS tags in a line of text.

        Args:
            line_text: The text content containing inline tags
            event_index: The index of this event
            start_time_ms: Start time in milliseconds
            end_time_ms: End time in milliseconds

        Returns:
            Modified text with rescaled tags
        """
        tag_pattern = re.compile(r"\\(fs|bord|shad)([\d\.]+)")

        start_seconds = self._event_time_to_seconds(start_time_ms)
        end_seconds = self._event_time_to_seconds(end_time_ms)
        start_frames = int(start_seconds * 24)
        end_frames = int(end_seconds * 24)

        modifications = []

        def replacer(match: re.Match[str]) -> str:
            tag_name = match.group(1)
            value_str = match.group(2)
            try:
                modified_value = self._rescale_value(value_str)
                if value_str != str(modified_value):
                    modifications.append((tag_name, value_str, modified_value))
                return f"\\{tag_name}{modified_value}"
            except (ValueError, TypeError):
                return match.group(0)

        modified_text = tag_pattern.sub(replacer, line_text)

        if modifications:
            time_str = (
                f"{format_log_time(start_seconds)}-{format_log_time(end_seconds)}"
            )
            frame_str = f"f{start_frames}-f{end_frames}"
            self.write_debug(f"  Event #{event_index + 1} ({time_str}, {frame_str}):")
            for tag_name, old_val, new_val in modifications:
                self.write_debug(f"    \\{tag_name}: {old_val} -> {new_val}")

        return modified_text

    def _collect_fonts_from_styles(
        self, subs: pysubs2.SSAFile, all_fonts_found: Set[str]
    ) -> None:
        """Collect font names from all styles in the subtitle file.

        Args:
            subs: SSAFile object
            all_fonts_found: Set to collect fonts
        """
        for style in subs.styles.values():
            if style.fontname:
                self._add_font_if_new(style.fontname, all_fonts_found, "style ")

    def _process_events(
        self,
        subs: pysubs2.SSAFile,
        all_fonts_found: Set[str],
        used_styles: Set[str],
    ) -> None:
        """Process subtitle events: rescale tags, collect fonts, track used styles.

        Args:
            subs: SSAFile object
            all_fonts_found: Set to collect fonts
            used_styles: Set to track used style names
        """
        for event_index, event in enumerate(subs.events):
            # Track used styles
            used_styles.add(event.style)

            # Get the event's style for formatting info
            event_style = subs.styles.get(event.style)
            style_is_italic = False
            style_is_bold = False

            if event_style:
                style_is_italic = event_style.italic in [True, -1, 1]
                style_is_bold = event_style.bold in [True, -1, 1]

            # Rescale inline tags
            event.text = self._rescale_inline_tags(
                event.text, event_index, event.start, event.end
            )

            # Collect inline fonts
            self._collect_fonts_from_inline_tags(
                event.text, all_fonts_found, event_index
            )

            # Detect and collect fonts for formatting tags
            has_italic = bool(re.search(r"\\i1", event.text))
            has_not_italic = bool(re.search(r"\\i0", event.text))
            has_bold = bool(re.search(r"\\b1", event.text))
            has_not_bold = bool(re.search(r"\\b0", event.text))

            if event_style and event_style.fontname:
                font_base = event_style.fontname

                if style_is_italic and has_not_italic:
                    self._add_font_if_new(font_base, all_fonts_found, "style ")
                elif not style_is_italic and has_italic:
                    if "Noto Sans" in font_base:
                        self._add_noto_italic_if_needed(
                            all_fonts_found,
                            f"Event #{event_index + 1}: italic tag found",
                        )
                    elif "Arial" in font_base:
                        self._add_arial_italic_if_needed(
                            all_fonts_found,
                            f"Event #{event_index + 1}: italic tag found",
                        )

                if style_is_bold and has_not_bold:
                    self._add_font_if_new(font_base, all_fonts_found, "style ")
                elif not style_is_bold and has_bold:
                    if "Noto Sans" in font_base:
                        self._add_noto_bold_if_needed(
                            all_fonts_found,
                            f"Event #{event_index + 1}: bold tag found",
                        )
                    elif "Arial" in font_base:
                        self._add_arial_bold_if_needed(
                            all_fonts_found,
                            f"Event #{event_index + 1}: bold tag found",
                        )

                if (has_italic and has_bold) or (
                    not style_is_italic
                    and has_italic
                    and not style_is_bold
                    and has_bold
                ):
                    if "Noto Sans" in font_base:
                        self._add_noto_bold_italic_if_needed(
                            all_fonts_found,
                            f"Event #{event_index + 1}: bold+italic tags found",
                        )
                    elif "Arial" in font_base:
                        self._add_arial_bold_italic_if_needed(
                            all_fonts_found,
                            f"Event #{event_index + 1}: bold+italic tags found",
                        )

    def _rescale_styles(self, subs: pysubs2.SSAFile, used_styles: Set[str]) -> int:
        """Rescale style properties (font size, outline, shadow).

        Args:
            subs: SSAFile object
            used_styles: Set of style names in use

        Returns:
            Number of styles that were rescaled
        """
        styles_to_keep = {}
        for style_name in used_styles:
            if style_name in subs.styles:
                styles_to_keep[style_name] = subs.styles[style_name]

        unused_styles = set(subs.styles.keys()) - used_styles
        if unused_styles:
            subs.styles = styles_to_keep

        rescaled_count = 0
        for style in subs.styles.values():
            style.fontsize = int(style.fontsize * self.SIZE_MODIFIER)
            style.outline = style.outline * self.SIZE_MODIFIER
            style.shadow = style.shadow * self.SIZE_MODIFIER
            rescaled_count += 1

        return rescaled_count

    def run(self, info: Dict[str, Any]) -> Tuple[List[Any], Dict[str, Any]]:
        """Process ASS/SSA subtitle files to rescale font sizes, borders, and shadows."""
        self.to_screen("Rescaling ASS/SSA subtitles (fontsize, border, shadow) by 0.8x")

        # Get subtitle file paths from yt-dlp metadata
        file_paths: Dict[str, str] = info.get("__files_to_move", {})
        if not file_paths:
            self.write_debug("No subtitle files found in metadata")
            return [], info

        all_fonts_found: Set[str] = set()

        for _, sub_file in file_paths.items():
            if not sub_file.endswith(".ass"):
                continue

            try:
                # Load with pysubs2
                subs = pysubs2.load(sub_file)
            except Exception as e:
                self.report_error(f"Failed to load {sub_file}: {e}")
                continue

            # Update title
            if subs.info:
                subs.info["Title"] = "Modified with github:nattadasu/bilidownloader"

            used_styles: Set[str] = set()

            # Collect fonts from styles
            self._collect_fonts_from_styles(subs, all_fonts_found)

            # Process events
            self._process_events(subs, all_fonts_found, used_styles)

            # Fill flicker gaps
            events = SubtitleIO.extract_events(subs)
            adjusted_events, gaps_filled = self.gap_filler.fill_flicker_gaps(events)
            SubtitleIO.update_events(subs, adjusted_events)

            # Rescale styles and track changes
            styles_changed = self._rescale_styles(subs, used_styles)

            # Extract language code from filename
            lang_match = rsearch(r"\.([a-z]{2}(?:-[A-Za-z]+)?)\.ass$", sub_file)
            lang_code = lang_match.group(1) if lang_match else "unknown"

            # Save file
            try:
                pysubs2.save(subs, sub_file)
                msg_parts = [f"[{lang_code}]"]
                if styles_changed:
                    msg_parts.append(f"styles rescaled ({styles_changed})")
                if gaps_filled > 0:
                    msg_parts.append(f"filled {gaps_filled} gap(s)")
                self.write_debug("  " + ", ".join(msg_parts))
            except Exception as e:
                self.report_error(f"Failed to save {sub_file}: {e}")
                continue

        # Save fonts list
        if all_fonts_found:
            fonts_json_path = "fonts.json"
            try:
                if Path(fonts_json_path).exists():
                    with open(fonts_json_path, "r", encoding="utf-8") as f:
                        existing_fonts = json.load(f)
                        all_fonts_found = set(all_fonts_found) | set(existing_fonts)

                with open(fonts_json_path, "w", encoding="utf-8") as f:
                    json.dump(sorted(list(all_fonts_found)), f, indent=2)
                self.write_debug(f"Font list saved to {fonts_json_path}")

                prn_info(f"Collected {len(all_fonts_found)} fonts")
                for font in sorted(all_fonts_found):
                    self.write_debug(f"  - {font}")
            except Exception as e:
                self.report_error(f"Failed to save fonts.json: {e}")

        return [], info
