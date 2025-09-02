import re
from json import dumps
from math import modf, floor
from typing import Any

from ass import parse_string as ass_loads
from yt_dlp.postprocessor import PostProcessor


class SSARescaler(PostProcessor):
    def run(self, info) -> tuple[list[Any], Any]:
        """
        Processes ASS/SSA subtitle files to rescale font sizes, borders, and shadows.
        It also collects all used font names, removes unused styles, and provides
        verbose output on changes when yt-dlp is run with --verbose.
        """
        def return_dump() -> tuple[list[Any], Any]:
            return [], info

        self.to_screen("Rescaling subtitle values and collecting fonts")
        fpath: dict[str, str] = info.get("__files_to_move", {})
        if not fpath:
            self.report_error("No subtitle filepaths found in the metadata")
            return return_dump()

        # This set will collect unique font names across all processed files
        all_fonts_found = set()

        for _, sub_file in fpath.items():
            if not sub_file.endswith(".ass"):
                self.report_warning(f"Skipping non-ASS file: {sub_file}")
                continue
            self.write_debug(f"Processing file: {sub_file}")

            try:
                # Use utf-8-sig to handle potential BOM (Byte Order Mark)
                with open(sub_file, "r", encoding="utf-8-sig") as file:
                    content = file.read()
                    ass = ass_loads(content)
            except Exception as e:
                self.report_error(f"Failed to read or parse {sub_file}: {e}")
                continue

            ass.fields["Title"] = "Modified with github:nattadasu/bilidownloader"
            size_mod = 0.8

            def valmod(value_str: str) -> int | float:
                """Converts string value, multiplies by size_mod, and returns int or float."""
                val = float(value_str) * size_mod
                frac, _ = modf(val)
                # Return an int if there's no fractional part, otherwise a rounded float
                return int(val) if frac == 0.0 else round(val, 2)

            # This single regex handles \fs, \bord, and \shad tags.
            tag_pattern = re.compile(r"\\(fs|bord|shad)([\d\.]+)")

            def replacer(match: re.Match) -> str:
                """
                This function is called for every match of tag_pattern.
                It modifies the numeric value and returns the updated tag string.
                """
                tag_name = match.group(1)  # 'fs', 'bord', or 'shad'
                value_str = match.group(2) # The numeric part as a string
                try:
                    modified_value = valmod(value_str)
                    self.write_debug(f"  Rescaled inline tag '\\{tag_name}': {value_str} -> {modified_value}")
                    return f"\\{tag_name}{modified_value}"
                except (ValueError, TypeError):
                    # If conversion fails, return the original matched string
                    return match.group(0)

            font_pattern = re.compile(r"\\fn\s*([^\\}]+)")
            used_styles = set()

            self.write_debug("Scanning events for used styles, inline fonts, and tags...")

            for line in ass.events:
                # Collect the names of all styles that are actually in use
                used_styles.add(line.style)

                # Find all inline font names (\fn) in the event text
                inline_fonts = font_pattern.findall(line.text)
                if inline_fonts:
                    fonts_on_this_line = {font.strip() for font in inline_fonts}
                    for font in fonts_on_this_line:
                        # Only log if it's a font we haven't seen before
                        if font not in all_fonts_found:
                            self.write_debug(f"  Found new inline font: '{font}'")
                            all_fonts_found.add(font)

                # Use re.sub with the replacer to modify all tags at once
                line.text = tag_pattern.sub(replacer, line.text)

            # --- Process Styles ---
            self.write_debug("Processing and rescaling styles...")

            # Get all style names before filtering to find unused ones
            original_style_names = {style.name for style in ass.styles}
            removed_styles = original_style_names - used_styles

            if removed_styles:
                self.write_debug(f"Removing {len(removed_styles)} unused styles: {', '.join(sorted(list(removed_styles)))}")
            else:
                self.write_debug("No unused styles to remove.")

            # Filter the styles list to keep only the ones that were used in events
            ass.styles = [style for style in ass.styles if style.name in used_styles]

            for style in ass.styles:
                self.write_debug(f"Processing Style: '{style.name}'")

                # Add the base font name from the style definition
                if style.fontname not in all_fonts_found:
                    self.write_debug(f"  Found new style font: '{style.fontname}'")
                    all_fonts_found.add(style.fontname)

                # Rescale style properties and log changes
                original_fontsize = style.fontsize
                style.fontsize = int(original_fontsize * size_mod)
                self.write_debug(f"  Rescaled Fontsize: {original_fontsize} -> {style.fontsize}")

                original_outline = style.outline
                style.outline = round(original_outline * size_mod, 2)
                self.write_debug(f"  Rescaled Outline: {original_outline} -> {style.outline}")

                original_shadow = style.shadow
                style.shadow = round(original_shadow * size_mod, 2)
                self.write_debug(f"  Rescaled Shadow: {original_shadow} -> {style.shadow}")

                # Other modifications
                style.outline_color.r = 0x00
                style.outline_color.g = 0x00
                style.outline_color.b = 0x00
                if '-' not in style.name:
                    offset = floor(ass.info['PlayResX'] * 0.08)
                    style.margin_r = offset
                    style.margin_l = offset
                    style.margin_v = floor(ass.info['PlayResY'] * 0.06)

            # --- Write Changes ---
            try:
                with open(sub_file, "w", encoding="utf-8-sig") as file:
                    ass.dump_file(file)
                self.to_screen(f"  Successfully processed and rescaled: {sub_file}")
            except Exception as e:
                self.report_error(f"Failed to write changes to {sub_file}: {e}")

        if all_fonts_found:
            self.write_debug(f"Found a total of {len(all_fonts_found)} unique fonts across all files.")
            for font in sorted(list(all_fonts_found)):
                self.write_debug(f"  - {font}")
            try:
                with open("fonts.json", "w", encoding="utf-8") as file:
                    # Convert set to a sorted list for consistent JSON output
                    file.write(dumps(sorted(list(all_fonts_found)), indent=2))
                self.to_screen("Font list saved to fonts.json")
            except Exception as e:
                self.report_error(f"Failed to write fonts.json: {e}")

        return return_dump()
