"""Advanced SubStation Alpha (ASS/SSA) subtitle rescaling post-processor for yt-dlp.

This module provides functionality to rescale ASS/SSA subtitle files by adjusting
font sizes, borders, and shadows, while collecting used fonts and removing unused
styles for optimization.
"""

import re
from datetime import timedelta
from json import dumps, loads
from math import floor, modf
from os import path
from typing import Any, Callable, Dict, List, Set, Tuple, Union

from ass import Document as AssDocument
from ass import parse_string as ass_loads
from yt_dlp.postprocessor import PostProcessor


class SSARescaler(PostProcessor):
    """A yt-dlp post-processor for rescaling ASS/SSA subtitle files.

    This class rescales font sizes, borders, and shadows in ASS/SSA subtitle files
    to improve readability while collecting all used fonts and removing unused styles.
    It also provides detailed logging when yt-dlp is run with the --verbose flag.

    Attributes:
        SIZE_MODIFIER (float): The scaling factor applied to font sizes and other elements.
    """

    SIZE_MODIFIER: float = 0.8

    def _ass_time_to_seconds(self, time_obj: Any) -> float:
        """Convert ASS time object to seconds.

        Args:
            time_obj: Time object from the ass library (timedelta)

        Returns:
            Time in seconds as a float
        """
        return time_obj.total_seconds()

    def _seconds_to_ass_time(self, seconds: float) -> Any:
        """Convert seconds to ASS time object.

        Args:
            seconds: Time in seconds as a float

        Returns:
            Time object (timedelta) for the ass library
        """
        return timedelta(seconds=seconds)

    def _fill_three_frame_gaps_in_document(self, events: List[Any]) -> None:
        """Fill gaps between subtitle lines if they are exactly 3 frames apart.

        Assumes 23.976/24 fps for frame duration calculation.
        Adjusts the end time of the current line to meet the start time of the next line.
        Modifies events in-place.

        Args:
            events: List of event objects from the ass library
        """
        if len(events) <= 1:
            return

        # 3 frames at 24 fps = 3/24 = 0.125 seconds (12.5 centiseconds)
        # 3 frames at 23.976 fps = 3/23.976 = 0.125125 seconds (12.5125 centiseconds)
        # Use a tolerance of 1 centisecond to account for precision loss
        three_frames_24fps = 3.0 / 24.0  # 0.125
        three_frames_23976fps = 3.0 / 23.976  # 0.125125
        tolerance = 0.01  # 1 centisecond tolerance

        for i in range(len(events) - 1):
            current_event = events[i]
            next_event = events[i + 1]

            # Convert times to seconds for calculation
            current_end_seconds = self._ass_time_to_seconds(current_event.end)
            next_start_seconds = self._ass_time_to_seconds(next_event.start)

            # Calculate the gap
            gap = next_start_seconds - current_end_seconds

            # Check if gap is approximately 3 frames (at 24 or 23.976 fps)
            if (
                abs(gap - three_frames_24fps) <= tolerance
                or abs(gap - three_frames_23976fps) <= tolerance
            ):
                # Fill the gap by extending the end time to the next start time
                current_event.end = next_event.start
                self.write_debug(
                    f"  Filled 3-frame gap: extended line ending at "
                    f"{current_end_seconds:.3f}s to {next_start_seconds:.3f}s"
                )

    def _add_font_if_new(
        self, font_name: str, all_fonts_found: Set[str], context: str = ""
    ) -> None:
        """Add a font to the collection if it's not already present.

        Args:
            font_name: The name of the font to add.
            all_fonts_found: Set of all fonts already discovered.
            context: Optional context string for debug messages (e.g., "inline ", "style ").
        """
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
        """Add Noto Sans Italic if not already present.

        Args:
            all_fonts_found: Set of all fonts already discovered.
            context: Context string explaining why the italic font is being added.
        """
        if "Noto Sans Italic" not in all_fonts_found:
            self.write_debug(f"  {context}, adding 'Noto Sans::Italic'")
            all_fonts_found.add("Noto Sans::Italic")

    def _process_inline_fonts(
        self, line_text: str, has_italic_tag: bool, all_fonts_found: Set[str]
    ) -> bool:
        """Process inline font tags and detect Noto Sans + italic combinations.

        Args:
            line_text: The text content of the subtitle line.
            has_italic_tag: Whether the line contains italic formatting tags.
            all_fonts_found: Set of all fonts already discovered.

        Returns:
            True if inline fonts were found in the line, False otherwise.
        """
        font_pattern = re.compile(r"\\fn\s*([^\\}]+)")
        inline_fonts = font_pattern.findall(line_text)

        if inline_fonts:
            fonts_on_this_line = {font.strip() for font in inline_fonts}
            for font in fonts_on_this_line:
                self._add_font_if_new(font, all_fonts_found, "inline ")

                # Check if Noto Sans is used with italic tag
                if font == "Noto Sans" and has_italic_tag:
                    self._add_noto_italic_if_needed(
                        all_fonts_found, "Found inline italic tag with Noto Sans"
                    )

        return bool(inline_fonts)

    def _process_style_font_with_italic(
        self,
        line_style_name: str,
        styles: List[Any],
        has_italic_tag: bool,
        all_fonts_found: Set[str],
    ) -> None:
        """Check if style-defined Noto Sans font is used with inline italic tags.

        Args:
            line_style_name: The name of the style used by the current line.
            styles: List of all style definitions in the subtitle file.
            has_italic_tag: Whether the line contains italic formatting tags.
            all_fonts_found: Set of all fonts already discovered.
        """
        if not has_italic_tag:
            return

        line_style = next((s for s in styles if s.name == line_style_name), None)
        if line_style and line_style.fontname == "Noto Sans":
            self._add_noto_italic_if_needed(
                all_fonts_found,
                f"Found italic tag with style-defined Noto Sans font '{line_style_name}'",
            )

    def _process_style_definitions(
        self, styles: List[Any], used_styles: Set[str], all_fonts_found: Set[str]
    ) -> List[Any]:
        """Process style definitions and detect style-level italic Noto Sans.

        Args:
            styles: List of all style definitions in the subtitle file.
            used_styles: Set of style names that are actually used in the subtitle.
            all_fonts_found: Set of all fonts already discovered.

        Returns:
            List of filtered styles containing only those that are actually used.
        """
        filtered_styles = [style for style in styles if style.name in used_styles]

        for style in filtered_styles:
            self.write_debug(f"Processing Style: '{style.name}'")

            # Add the base font name from the style definition
            self._add_font_if_new(style.fontname, all_fonts_found, "style ")

            # Check if style uses Noto Sans with italic enabled
            if style.fontname == "Noto Sans" and style.italic:
                self._add_noto_italic_if_needed(
                    all_fonts_found, "Found italic style using Noto Sans"
                )

        return filtered_styles

    def _rescale_value(self, value_str: str) -> Union[int, float]:
        """Convert string value, multiply by size modifier, and return appropriate numeric type.

        Args:
            value_str: String representation of the numeric value to rescale.

        Returns:
            Rescaled value as int if no fractional part exists, otherwise rounded float.
        """
        rescaled_value = float(value_str) * self.SIZE_MODIFIER
        fractional_part, _ = modf(rescaled_value)
        # Return an int if there's no fractional part, otherwise a rounded float
        return (
            int(rescaled_value) if fractional_part == 0.0 else round(rescaled_value, 2)
        )

    def _create_tag_replacer(self) -> Callable[[re.Match[str]], str]:
        """Create a function to replace ASS tags with rescaled values.

        Returns:
            A function that takes a regex match and returns the rescaled tag string.
        """

        def replacer(match: re.Match[str]) -> str:
            r"""Replace ASS tags (\fs, \bord, \shad) with rescaled values.

            Args:
                match: Regex match object containing tag name and value.

            Returns:
                Rescaled tag string or original string if conversion fails.
            """
            tag_name = match.group(1)  # 'fs', 'bord', or 'shad'
            value_str = match.group(2)  # The numeric part as a string
            try:
                modified_value = self._rescale_value(value_str)
                if value_str != str(modified_value):
                    self.write_debug(
                        f"  Rescaled inline tag '\\{tag_name}': {value_str} -> {modified_value}"
                    )
                return f"\\{tag_name}{modified_value}"
            except (ValueError, TypeError):
                # If conversion fails, return the original matched string
                return match.group(0)

        return replacer

    def run(self, info: Dict[str, Any]) -> Tuple[List[Any], Dict[str, Any]]:
        """Process ASS/SSA subtitle files to rescale font sizes, borders, and shadows.

        This method rescales subtitle elements, collects used font names, removes unused
        styles, and provides verbose output on changes when yt-dlp is run with --verbose.

        Args:
            info: Dictionary containing file information from yt-dlp, including
                  "__files_to_move" with subtitle file paths.

        Returns:
            Tuple containing an empty list and the original info dictionary,
            as required by yt-dlp's PostProcessor interface.
        """

        def return_dump() -> Tuple[List[Any], Dict[str, Any]]:
            """Return the standard post-processor response."""
            return [], info

        self.to_screen("Rescaling subtitle values and collecting fonts")

        # Get subtitle file paths from yt-dlp metadata
        file_paths: Dict[str, str] = info.get("__files_to_move", {})
        if not file_paths:
            self.report_error("No subtitle filepaths found in the metadata")
            return return_dump()

        # This set will collect unique font names across all processed files
        all_fonts_found: Set[str] = set()

        for _, sub_file in file_paths.items():
            if not sub_file.endswith(".ass"):
                self.report_warning(f"Skipping non-ASS file: {sub_file}")
                continue
            self.write_debug(f"Processing file: {sub_file}")

            try:
                # Use utf-8-sig to handle potential BOM (Byte Order Mark)
                with open(sub_file, "r", encoding="utf-8-sig") as file:
                    content = file.read()
                    ass_document: AssDocument = ass_loads(content)
            except Exception as e:
                self.report_error(f"Failed to read or parse {sub_file}: {e}")
                continue

            # Update document metadata
            ass_document.fields["Title"] = (
                "Modified with github:nattadasu/bilidownloader"
            )

            # Create tag pattern and replacer function
            tag_pattern = re.compile(r"\\(fs|bord|shad)([\d\.]+)")
            tag_replacer = self._create_tag_replacer()
            italic_pattern = re.compile(r"\\i1")
            used_styles: Set[str] = set()

            self.write_debug(
                "Scanning events for used styles, inline fonts, and tags..."
            )

            # Process all subtitle events/lines
            for line in ass_document.events:
                # Collect the names of all styles that are actually in use
                used_styles.add(line.style)

                # Check for italic tags in the line text
                has_italic_tag = bool(italic_pattern.search(line.text))

                # Process inline fonts and detect Noto Sans + italic combinations
                has_inline_fonts = self._process_inline_fonts(
                    line.text, has_italic_tag, all_fonts_found
                )

                # Check if italic tag is used with style-defined Noto Sans font
                if not has_inline_fonts:
                    self._process_style_font_with_italic(
                        line.style, ass_document.styles, has_italic_tag, all_fonts_found
                    )

                # Use regex substitution to modify all tags at once
                line.text = tag_pattern.sub(tag_replacer, line.text)

            # Process and filter styles
            self._process_styles(ass_document, used_styles, all_fonts_found)

            # Fill 3-frame gaps between subtitle lines
            self.write_debug("Filling 3-frame gaps between subtitle lines...")
            self._fill_three_frame_gaps_in_document(ass_document.events)

            # Write changes back to file
            try:
                with open(sub_file, "w", encoding="utf-8-sig") as file:
                    ass_document.dump_file(file)
                self.to_screen(f"  Successfully processed and rescaled: {sub_file}")
            except Exception as e:
                self.report_error(f"Failed to write changes to {sub_file}: {e}")

        # Save collected fonts to JSON file
        self._save_fonts_to_json(all_fonts_found)

        return return_dump()

    def _process_styles(
        self,
        ass_document: AssDocument,
        used_styles: Set[str],
        all_fonts_found: Set[str],
    ) -> None:
        """Process and rescale ASS document styles.

        Args:
            ass_document: The ASS document to process.
            used_styles: Set of style names that are actually used.
            all_fonts_found: Set of all fonts already discovered.
        """
        self.write_debug("Processing and rescaling styles...")

        # Get all style names before filtering to find unused ones
        original_style_names = {style.name for style in ass_document.styles}
        removed_styles = original_style_names - used_styles

        if removed_styles:
            self.write_debug(
                f"Removing {len(removed_styles)} unused styles: "
                f"{', '.join(sorted(list(removed_styles)))}"
            )
        else:
            self.write_debug("No unused styles to remove.")

        # Process style definitions and filter to used styles only
        ass_document.styles = self._process_style_definitions(
            ass_document.styles, used_styles, all_fonts_found
        )

        # Rescale style properties
        for style in ass_document.styles:
            self._rescale_style_properties(style)
            self._apply_style_modifications(style, ass_document)

    def _rescale_style_properties(self, style: Any) -> None:
        """Rescale font size, outline, and shadow properties of a style.

        Args:
            style: The ASS style object to rescale.
        """
        # Rescale font size
        original_fontsize = style.fontsize
        style.fontsize = int(original_fontsize * self.SIZE_MODIFIER)
        if original_fontsize != style.fontsize:
            self.write_debug(
                f"  Rescaled Fontsize: {original_fontsize} -> {style.fontsize}"
            )

        # Rescale outline
        original_outline = style.outline
        style.outline = round(original_outline * self.SIZE_MODIFIER, 2)
        if original_outline != style.outline:
            self.write_debug(
                f"  Rescaled Outline: {original_outline} -> {style.outline}"
            )

        # Rescale shadow
        original_shadow = style.shadow
        style.shadow = round(original_shadow * self.SIZE_MODIFIER, 2)
        if original_shadow != style.shadow:
            self.write_debug(f"  Rescaled Shadow: {original_shadow} -> {style.shadow}")

    def _apply_style_modifications(self, style: Any, ass_document: AssDocument) -> None:
        """Apply additional style modifications like margins and outline color.

        Args:
            style: The ASS style object to modify.
            ass_document: The ASS document containing resolution information.
        """
        # Set outline color to black
        style.outline_color.r = 0x00
        style.outline_color.g = 0x00
        style.outline_color.b = 0x00

        # Apply margins for non-hyphenated style names
        if "-" not in style.name:
            horizontal_offset = floor(ass_document.info["PlayResX"] * 0.08)
            vertical_offset = floor(ass_document.info["PlayResY"] * 0.06)

            style.margin_r = horizontal_offset
            style.margin_l = horizontal_offset
            style.margin_v = vertical_offset

    def _save_fonts_to_json(self, all_fonts_found: Set[str]) -> None:
        """Save the collected fonts to a JSON file.

        Args:
            all_fonts_found: Set of all fonts discovered during processing.
        """
        if all_fonts_found:
            self.write_debug(
                f"Found a total of {len(all_fonts_found)} unique fonts across all files."
            )
            for font in sorted(list(all_fonts_found)):
                self.write_debug(f"  - {font}")
            try:
                # loads existing fonts from fonts.json
                if path.exists("fonts.json"):
                    with open("fonts.json", "r", encoding="utf-8") as file:
                        existing_fonts = set(loads(file.read()))
                        all_fonts_found.update(existing_fonts)
                with open("fonts.json", "w", encoding="utf-8") as file:
                    # Convert set to a sorted list for consistent JSON output
                    file.write(dumps(sorted(list(all_fonts_found)), indent=2))
                self.to_screen("Font list saved to fonts.json")
            except Exception as e:
                self.report_error(f"Failed to write fonts.json: {e}")
