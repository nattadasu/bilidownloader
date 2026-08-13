"""yt-dlp Post-processors for subtitle processing (rescaling, conversion, and gap filling)."""

import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pysubs2
from yt_dlp.postprocessor import PostProcessor

from bilidownloader.commons.metadata import __VERSION__
from bilidownloader.commons.ui import prn_info
from bilidownloader.subtitles.gap_filler import FlickerFiller
from bilidownloader.subtitles.processors.arabic import ArabicProcessor
from bilidownloader.subtitles.processors.english import EnglishProcessor
from bilidownloader.subtitles.subtitle_io import SubtitleIO


def extract_lang_code(file_path: Path) -> str:
    """Extract language code from subtitle file name (e.g., file.en.ass -> en)."""
    lang_match = re.search(
        r"\.([a-z]{2}(?:-[A-Za-z]+)?)\.(?:ass|srt)$", file_path.name, re.IGNORECASE
    )
    return lang_match.group(1) if lang_match else "unknown"


class ASSHTMLSanitizer(HTMLParser):
    """A syntactical HTML parser that converts HTML tags to ASS override tags or strips them."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.result: list[str] = []
        self.tag_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in ("i", "em"):
            self.result.append(r"{\i1}")
            self.tag_stack.append("i")
        elif tag_lower in ("b", "strong"):
            self.result.append(r"{\b1}")
            self.tag_stack.append("b")
        elif tag_lower in ("u", "ins"):
            self.result.append(r"{\u1}")
            self.tag_stack.append("u")
        elif tag_lower in ("s", "strike", "del"):
            self.result.append(r"{\s1}")
            self.tag_stack.append("s")
        elif tag_lower == "br":
            self.result.append(r"\N")
        elif tag_lower == "font":
            self.tag_stack.append("font")
            attr_dict = {k.lower(): (v or "") for k, v in attrs}
            color = attr_dict.get("color")
            if color:
                ass_color = self._parse_html_color(color)
                if ass_color:
                    self.result.append(rf"{{\c{ass_color}}}")
                else:
                    self.result.append(r"{\c}")
            else:
                self.result.append(r"{\c}")
        else:
            self.tag_stack.append(tag_lower)

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in ("i", "em"):
            self.result.append(r"{\i0}")
            if "i" in self.tag_stack:
                self.tag_stack.remove("i")
        elif tag_lower in ("b", "strong"):
            self.result.append(r"{\b0}")
            if "b" in self.tag_stack:
                self.tag_stack.remove("b")
        elif tag_lower in ("u", "ins"):
            self.result.append(r"{\u0}")
            if "u" in self.tag_stack:
                self.tag_stack.remove("u")
        elif tag_lower in ("s", "strike", "del"):
            self.result.append(r"{\s0}")
            if "s" in self.tag_stack:
                self.tag_stack.remove("s")
        elif tag_lower == "font":
            self.result.append(r"{\c}")
            if "font" in self.tag_stack:
                self.tag_stack.remove("font")
        else:
            if tag_lower in self.tag_stack:
                self.tag_stack.remove(tag_lower)

    def handle_data(self, data: str) -> None:
        self.result.append(data)

    def handle_entityref(self, name: str) -> None:
        self.result.append(html.unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        self.result.append(html.unescape(f"&#{name};"))

    @staticmethod
    def _parse_html_color(color_str: str) -> str | None:
        """Convert HTML color (#RRGGBB or #RGB) to ASS BGR hex format (&HBBGGRR&)."""
        color_str = color_str.strip().lstrip("#")
        if len(color_str) == 3:
            color_str = "".join(c * 2 for c in color_str)
        if len(color_str) == 6 and all(
            c in "0123456789abcdefABCDEF" for c in color_str
        ):
            r, g, b = color_str[0:2], color_str[2:4], color_str[4:6]
            return f"&H{b.upper()}{g.upper()}{r.upper()}&"
        return None


def sanitize_html(text: str) -> str:
    """Syntactically parse and dynamically convert/sanitize HTML tags in subtitle text into ASS format.

    Preserves native ASS override tags (e.g. {\\i1}, {\\pos(...)}) while properly parsing HTML
    structures (including nested tags, HTML entities, font colors, linebreaks, and malformed tags).
    """
    if not text:
        return text

    # Unescape HTML entities (e.g., &amp;, &lt;, &gt;, &quot;, &#39;, &nbsp;)
    text = html.unescape(text)

    # Tokenize text into ASS override tag blocks {...} and non-ASS segments
    # Match any {...} block vs text outside
    tokens = re.split(r"(\{[^}]*\})", text)
    processed_parts = []

    for token in tokens:
        if token.startswith("{") and token.endswith("}"):
            # Preserve native ASS tag block intact
            processed_parts.append(token)
        elif "<" in token or ">" in token or "&" in token:
            try:
                parser = ASSHTMLSanitizer()
                parser.feed(token)
                processed_parts.append("".join(parser.result))
            except Exception:
                # Fallback: strip any remaining HTML angle brackets if parsing fails
                processed_parts.append(re.sub(r"</?[a-zA-Z][^>]*>", "", token))
        else:
            processed_parts.append(token)

    result = "".join(processed_parts)
    # Clean up redundant empty ASS override tags like {}
    result = re.sub(r"\{\}", "", result)

    # Whitespace sanitization:
    # 1. Normalize horizontal whitespace (multiple spaces/tabs -> single space) per line
    # 2. Strip leading and trailing whitespace around ASS linebreaks (\N) and text boundaries
    # 3. Strip whitespace immediately inside ASS formatting tag boundaries (e.g., {\i1} text {\i0} -> {\i1}text{\i0})
    lines = result.split(r"\N")
    cleaned_lines = []
    for line in lines:
        # Collapse multiple spaces or tabs into a single space
        line = re.sub(r"[ \t]+", " ", line)
        # Strip trailing space right after start tag and leading space right before end tag
        line = re.sub(r"(\{\\[a-zA-Z0-9]+\})\s+", r"\1", line)
        line = re.sub(r"\s+(\{\\[a-zA-Z0-9]+0\})", r"\1", line)
        cleaned_lines.append(line.strip())

    result = r"\N".join(cleaned_lines)
    # Collapse multiple consecutive linebreaks (\N\N -> \N)
    result = re.sub(r"(\\N)+", r"\\N", result)

    return result


def apply_language_processing(
    subs, lang_code: str, pp: PostProcessor, is_ass: bool = True
) -> tuple[int, int]:
    """Apply language processing (and HTML sanitization for ASS format) to subtitles."""
    merged_count = 0
    split_count = 0

    no_mods = getattr(pp, "no_mods", False)

    # Exclusively sanitize HTML tags for ASS subtitles
    if is_ass:
        for event in subs.events:
            if event.text:
                event.text = sanitize_html(event.text)

    if lang_code == "ar" and not no_mods:
        for event in subs.events:
            event.text = ArabicProcessor.process_arabic_subtitle(event.text)
    elif (lang_code == "en" or lang_code.startswith("en-")) and not no_mods:
        orig_count = len(subs.events)
        subs.events = EnglishProcessor.merge_continuation_lines(subs.events)
        merged_count = orig_count - len(subs.events)
        if merged_count > 0:
            pp.write_debug(
                f"    [{lang_code}] merged {merged_count} continuation line(s)"
            )

        for event in subs.events:
            if event.text:
                original = event.text
                patched = EnglishProcessor.process_english_subtitle(original)
                if patched != original:
                    split_count += 1
                    pp.write_debug(
                        f"    [{lang_code}] split: {original!r} -> {patched!r}"
                    )
                    event.text = patched

    return merged_count, split_count


class SRTToASSConverter(PostProcessor):
    """A yt-dlp post-processor for converting SRT subtitles to ASS format."""

    def __init__(
        self, *args, is_chinese: bool = False, no_mods: bool = False, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.gap_filler = FlickerFiller(is_chinese=is_chinese)
        self.no_mods = no_mods

    def _convert_srt_file(
        self, srt_path: Path, play_res_x: int = 1920, play_res_y: int = 1080
    ) -> tuple[Path, int]:
        if not srt_path.exists():
            self.report_error(f"SRT file not found: {srt_path}")
            return None, 0

        ass_path = srt_path.with_suffix(".ass")
        try:
            lang_code = extract_lang_code(srt_path)
            subs = SubtitleIO.load(srt_path)

            # Apply language line-splitting & merging
            merged_count, split_count = apply_language_processing(subs, lang_code, self)

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

            # Apply gap filling and identical lines merging
            gaps_filled = self.gap_filler.fill_flicker_gaps(subs)
            identical_merged = self.gap_filler.merge_identical_subtitle_lines(subs)
            merged_count += identical_merged

            # Apply styling based on language code
            SubtitleIO.apply_style(subs, lang_code=lang_code)

            # Save as ASS
            SubtitleIO.save(subs, ass_path)

            try:
                srt_path.unlink()
                msg_parts = [f"[{lang_code}]"]
                if gaps_filled > 0:
                    msg_parts.append(f"filled {gaps_filled} gap(s)")
                if merged_count > 0:
                    msg_parts.append(f"merged {merged_count} line(s)")
                if split_count > 0:
                    msg_parts.append(f"split {split_count} line(s)")

                if len(msg_parts) > 1:
                    self.write_debug("  " + ", ".join(msg_parts))
                else:
                    self.write_debug(f"  [{lang_code}] converted")
            except Exception as e:
                self.write_debug(
                    f"Converted {srt_path.name} to {ass_path.name} but failed to remove SRT file: {e}"
                )

            return ass_path, gaps_filled
        except Exception as e:
            self.report_error(f"Failed to convert {srt_path}: {e}")
            return None, 0

    def run(self, info: dict) -> tuple[list, dict]:
        self.to_screen("Converting SRT subtitles to ASS format")
        file_paths = info.get("__files_to_move", {})
        if not file_paths:
            self.write_debug("No subtitle files found in metadata")
            return [], info

        converted_count = 0
        total_gaps_filled = 0
        new_file_paths = {}
        requested_subtitles = info.get("requested_subtitles", {})

        for original_path, current_path in file_paths.items():
            current_file = Path(current_path)
            if current_file.suffix.lower() != ".srt":
                new_file_paths[original_path] = current_path
                continue

            ass_path, gaps_filled = self._convert_srt_file(current_file)
            if ass_path:
                converted_count += 1
                total_gaps_filled += gaps_filled
                new_ass_path_str = str(ass_path)
                new_file_paths[str(Path(original_path).with_suffix(".ass"))] = (
                    new_ass_path_str
                )

                # Update requested_subtitles so yt-dlp's downstream embedder knows about the converted file
                for sub_info in requested_subtitles.values():
                    if sub_info.get("filepath") == current_path:
                        sub_info["filepath"] = new_ass_path_str
                        sub_info["ext"] = "ass"

                # Track converted files to avoid rescaling later
                if "__converted_from_srt" not in info:
                    info["__converted_from_srt"] = set()
                info["__converted_from_srt"].add(new_ass_path_str)
            else:
                new_file_paths[original_path] = current_path

        info["__files_to_move"] = new_file_paths
        if converted_count > 0:
            self.to_screen(
                f"Converted {converted_count} SRT file(s) to ASS, filled {total_gaps_filled} gap(s) total"
            )

        return [], info


class SSARescaler(PostProcessor):
    """A yt-dlp post-processor for rescaling ASS/SSA subtitle files."""

    SIZE_MODIFIER = 0.8

    def _rescale_styles(self, subs, used_styles: set[str]) -> int:
        styles_to_keep = {
            name: style for name, style in subs.styles.items() if name in used_styles
        }
        unused_styles = len(subs.styles) - len(styles_to_keep)
        if unused_styles:
            subs.styles = styles_to_keep

        rescaled_count = 0
        maroon_color = pysubs2.Color(r=8, g=34, b=0, a=0)
        black_color = pysubs2.Color(r=0, g=0, b=0, a=0)

        for style in subs.styles.values():
            style.fontsize = int(style.fontsize * self.SIZE_MODIFIER)
            style.outline = style.outline * self.SIZE_MODIFIER
            style.shadow = style.shadow * self.SIZE_MODIFIER

            if style.outlinecolor == maroon_color:
                style.outlinecolor = black_color
            rescaled_count += 1

        return rescaled_count

    def run(self, info: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
        self.to_screen("Rescaling ASS/SSA subtitles (fontsize, border, shadow) by 0.8x")
        file_paths = info.get("__files_to_move", {})
        if not file_paths:
            self.write_debug("No subtitle files found in metadata")
            return [], info

        for sub_file in file_paths.values():
            if not sub_file.endswith(".ass"):
                continue

            try:
                subs = SubtitleIO.load(Path(sub_file))
            except Exception as e:
                self.report_error(f"Failed to load {sub_file}: {e}")
                continue

            # Skip rescaling for subtitles converted from SRT
            if sub_file in info.get("__converted_from_srt", set()):
                self.write_debug(
                    f"  [{extract_lang_code(Path(sub_file))}] skipped rescaling"
                )
                continue

            used_styles: set[str] = {event.style for event in subs.events if event.text}

            # Rescale styles
            styles_changed = self._rescale_styles(subs, used_styles)

            try:
                SubtitleIO.save(subs, Path(sub_file))
                msg_parts = [f"[{extract_lang_code(Path(sub_file))}]"]
                if styles_changed:
                    msg_parts.append(f"styles rescaled ({styles_changed})")
                if len(msg_parts) > 1:
                    self.write_debug("  " + ", ".join(msg_parts))
            except Exception as e:
                self.report_error(f"Failed to save {sub_file}: {e}")
                continue

        return [], info


class ASSProcessor(PostProcessor):
    """A yt-dlp post-processor for processing ASS/SSA subtitles (metadata, gap filling, merging/splitting)."""

    def __init__(
        self, *args, is_chinese: bool = False, no_mods: bool = False, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.gap_filler = FlickerFiller(is_chinese=is_chinese)
        self.no_mods = no_mods

    def run(self, info: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
        self.to_screen("Processing ASS/SSA subtitles (gap filling, line optimization)")
        file_paths = info.get("__files_to_move", {})
        if not file_paths:
            self.write_debug("No subtitle files found in metadata")
            return [], info

        for sub_file in file_paths.values():
            if not sub_file.endswith(".ass"):
                continue

            try:
                subs = SubtitleIO.load(Path(sub_file))
            except Exception as e:
                self.report_error(f"Failed to load {sub_file}: {e}")
                continue

            if subs.info:
                subs.info["Title"] = (
                    f"Modified with github:nattadasu/bilidownloader v{__VERSION__}"
                )

            lang_code = extract_lang_code(Path(sub_file))

            # Apply language line-splitting & merging
            merged_count, split_count = apply_language_processing(subs, lang_code, self)

            # Fill flicker gaps and merge identical lines
            gaps_filled = self.gap_filler.fill_flicker_gaps(subs)
            identical_merged = self.gap_filler.merge_identical_subtitle_lines(subs)
            merged_count += identical_merged

            try:
                SubtitleIO.save(subs, Path(sub_file))
                msg_parts = [f"[{lang_code}]"]
                if gaps_filled > 0:
                    msg_parts.append(f"filled {gaps_filled} gap(s)")
                if merged_count > 0:
                    msg_parts.append(f"merged {merged_count} line(s)")
                if split_count > 0:
                    msg_parts.append(f"split {split_count} line(s)")
                if len(msg_parts) > 1:
                    self.write_debug("  " + ", ".join(msg_parts))
            except Exception as e:
                self.report_error(f"Failed to save {sub_file}: {e}")
                continue

        return [], info


class FontCollector(PostProcessor):
    """A yt-dlp post-processor for collecting fonts used in ASS/SSA subtitle files."""

    def run(self, info: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
        self.to_screen("Collecting fonts used in ASS/SSA subtitles")
        file_paths = info.get("__files_to_move", {})
        if not file_paths:
            self.write_debug("No subtitle files found in metadata")
            return [], info

        all_fonts_found: set[str] = set()

        for sub_file in file_paths.values():
            if not sub_file.endswith(".ass"):
                continue

            try:
                subs = SubtitleIO.load(Path(sub_file))
            except Exception as e:
                self.report_error(f"Failed to load {sub_file}: {e}")
                continue

            used_styles: set[str] = set()
            for event in subs.events:
                if not event.text:
                    continue
                used_styles.add(event.style)
                # Find fonts used directly in override tags
                font_tags = re.findall(r"\\fn([^\\}]+)", event.text)
                for font in font_tags:
                    all_fonts_found.add(font.strip())
                # Find bold override tags to map to Bold fonts
                if "\\b1" in event.text or "\\b700" in event.text:
                    style = subs.styles.get(event.style)
                    if style:
                        all_fonts_found.add(f"{style.fontname}::Bold")

            for style_name, style in subs.styles.items():
                if style_name in used_styles:
                    all_fonts_found.add(style.fontname)
                    if style.bold:
                        all_fonts_found.add(f"{style.fontname}::Bold")

        if all_fonts_found:
            fonts_json_path = "fonts.json"
            try:
                if Path(fonts_json_path).exists():
                    with open(fonts_json_path, "r", encoding="utf-8") as f:
                        existing_fonts = json.load(f)
                        all_fonts_found = set(all_fonts_found) | set(existing_fonts)

                with open(fonts_json_path, "w", encoding="utf-8") as f:
                    json.dump(sorted(all_fonts_found), f, indent=2)
                self.write_debug(f"Font list saved to {fonts_json_path}")
                prn_info(f"Collected {len(all_fonts_found)} fonts")
                for font in sorted(all_fonts_found):
                    self.write_debug(f"  - {font}")
            except Exception as e:
                self.report_error(f"Failed to save fonts.json: {e}")

        return [], info


class SRTModifier(PostProcessor):
    """A yt-dlp post-processor for applying language-specific split/merge modifications to SRT subtitles."""

    def __init__(self, *args, no_mods: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.no_mods = no_mods

    def run(self, info: dict) -> tuple[list, dict]:
        self.to_screen("Applying language processing to SRT subtitles")
        file_paths = info.get("__files_to_move", {})
        if not file_paths:
            return [], info

        for current_path in file_paths.values():
            current_file = Path(current_path)
            if current_file.suffix.lower() != ".srt":
                continue

            try:
                subs = SubtitleIO.load(current_file)
                lang_code = extract_lang_code(current_file)
                merged_count, split_count = apply_language_processing(
                    subs, lang_code, self, is_ass=False
                )
                SubtitleIO.save(subs, current_file)

                msg_parts = [f"[{lang_code}]"]
                if merged_count > 0:
                    msg_parts.append(f"merged {merged_count} line(s)")
                if split_count > 0:
                    msg_parts.append(f"split {split_count} line(s)")
                if len(msg_parts) > 1:
                    self.write_debug("  " + ", ".join(msg_parts))
            except Exception as e:
                self.report_error(f"Failed to process {current_file}: {e}")

        return [], info


class SRTGapFiller(PostProcessor):
    """A yt-dlp post-processor for filling flicker gaps in SRT subtitles."""

    def __init__(self, *args, is_chinese: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.gap_filler = FlickerFiller(is_chinese=is_chinese)

    def run(self, info: dict) -> tuple[list, dict]:
        self.to_screen("Filling flicker gaps in SRT subtitles")
        file_paths = info.get("__files_to_move", {})
        if not file_paths:
            return [], info

        processed_count = 0
        total_gaps_filled = 0

        for current_path in file_paths.values():
            current_file = Path(current_path)
            if current_file.suffix.lower() != ".srt":
                continue

            try:
                subs = SubtitleIO.load(current_file)
                lang_code = extract_lang_code(current_file)
                gaps_filled = self.gap_filler.fill_flicker_gaps(subs)
                identical_merged = self.gap_filler.merge_identical_subtitle_lines(subs)
                SubtitleIO.save(subs, current_file)

                if gaps_filled > 0 or identical_merged > 0:
                    processed_count += 1
                    total_gaps_filled += gaps_filled
                    msg_parts = [f"[{lang_code}]"]
                    if gaps_filled > 0:
                        msg_parts.append(f"filled {gaps_filled} gap(s)")
                    if identical_merged > 0:
                        msg_parts.append(f"merged {identical_merged} identical line(s)")
                    self.write_debug("  " + ", ".join(msg_parts))
            except Exception as e:
                self.report_error(f"Failed to process {current_file}: {e}")

        if processed_count > 0:
            self.to_screen(
                f"Processed {processed_count} SRT file(s), filled {total_gaps_filled} gap(s) total"
            )

        return [], info


class ASSModifier(PostProcessor):
    """A yt-dlp post-processor for applying language modifications and setting title metadata in ASS/SSA subtitles."""

    def __init__(self, *args, no_mods: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.no_mods = no_mods

    def run(self, info: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
        self.to_screen(
            "Applying language processing and metadata updates to ASS/SSA subtitles"
        )
        file_paths = info.get("__files_to_move", {})
        if not file_paths:
            return [], info

        for sub_file in file_paths.values():
            if not sub_file.endswith(".ass"):
                continue

            try:
                subs = SubtitleIO.load(Path(sub_file))
            except Exception as e:
                self.report_error(f"Failed to load {sub_file}: {e}")
                continue

            if subs.info:
                subs.info["Title"] = (
                    f"Modified with github:nattadasu/bilidownloader v{__VERSION__}"
                )

            lang_code = extract_lang_code(Path(sub_file))
            merged_count, split_count = apply_language_processing(subs, lang_code, self)

            try:
                SubtitleIO.save(subs, Path(sub_file))
                msg_parts = [f"[{lang_code}]"]
                if merged_count > 0:
                    msg_parts.append(f"merged {merged_count} line(s)")
                if split_count > 0:
                    msg_parts.append(f"split {split_count} line(s)")
                if len(msg_parts) > 1:
                    self.write_debug("  " + ", ".join(msg_parts))
            except Exception as e:
                self.report_error(f"Failed to save {sub_file}: {e}")

        return [], info


class ASSGapFiller(PostProcessor):
    """A yt-dlp post-processor for filling flicker gaps in ASS/SSA subtitles."""

    def __init__(self, *args, is_chinese: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.gap_filler = FlickerFiller(is_chinese=is_chinese)

    def run(self, info: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
        self.to_screen("Filling flicker gaps in ASS/SSA subtitles")
        file_paths = info.get("__files_to_move", {})
        if not file_paths:
            return [], info

        processed_count = 0
        total_gaps_filled = 0

        for sub_file in file_paths.values():
            if not sub_file.endswith(".ass"):
                continue

            try:
                subs = SubtitleIO.load(Path(sub_file))
            except Exception as e:
                self.report_error(f"Failed to load {sub_file}: {e}")
                continue

            lang_code = extract_lang_code(Path(sub_file))
            gaps_filled = self.gap_filler.fill_flicker_gaps(subs)
            identical_merged = self.gap_filler.merge_identical_subtitle_lines(subs)

            try:
                SubtitleIO.save(subs, Path(sub_file))
                if gaps_filled > 0 or identical_merged > 0:
                    processed_count += 1
                    total_gaps_filled += gaps_filled
                    msg_parts = [f"[{lang_code}]"]
                    if gaps_filled > 0:
                        msg_parts.append(f"filled {gaps_filled} gap(s)")
                    if identical_merged > 0:
                        msg_parts.append(f"merged {identical_merged} identical line(s)")
                    self.write_debug("  " + ", ".join(msg_parts))
            except Exception as e:
                self.report_error(f"Failed to save {sub_file}: {e}")

        if processed_count > 0:
            self.to_screen(
                f"Processed {processed_count} ASS file(s), filled {total_gaps_filled} gap(s) total"
            )

        return [], info
