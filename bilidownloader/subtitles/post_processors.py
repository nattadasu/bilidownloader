"""yt-dlp Post-processors for subtitle processing (rescaling, conversion, and gap filling)."""

import json
import re
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


def apply_language_processing(
    subs, lang_code: str, pp: PostProcessor
) -> tuple[int, int]:
    """Apply clausal splitting and line merging to subtitles based on language."""
    merged_count = 0
    split_count = 0

    if lang_code == "ar":
        for event in subs.events:
            event.text = ArabicProcessor.process_arabic_subtitle(event.text)
    elif lang_code == "en" or lang_code.startswith("en-"):
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

    def __init__(self, *args, is_chinese: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.gap_filler = FlickerFiller(is_chinese=is_chinese)

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

    def __init__(self, *args, is_chinese: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.gap_filler = FlickerFiller(is_chinese=is_chinese)

    def _process_events(
        self, subs, all_fonts_found: set[str], used_styles: set[str]
    ) -> None:
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

    def _collect_fonts_from_styles(
        self, subs, all_fonts_found: set[str], used_styles: set[str]
    ) -> None:
        for style_name, style in subs.styles.items():
            if style_name in used_styles:
                all_fonts_found.add(style.fontname)
                if style.bold:
                    all_fonts_found.add(f"{style.fontname}::Bold")

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

        all_fonts_found: set[str] = set()

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

            used_styles: set[str] = set()
            self._process_events(subs, all_fonts_found, used_styles)
            self._collect_fonts_from_styles(subs, all_fonts_found, used_styles)

            # Fill flicker gaps and merge identical lines
            gaps_filled = self.gap_filler.fill_flicker_gaps(subs)
            identical_merged = self.gap_filler.merge_identical_subtitle_lines(subs)
            merged_count += identical_merged

            # Rescale styles
            styles_changed = self._rescale_styles(subs, used_styles)

            try:
                SubtitleIO.save(subs, Path(sub_file))
                msg_parts = [f"[{lang_code}]"]
                if styles_changed:
                    msg_parts.append(f"styles rescaled ({styles_changed})")
                if gaps_filled > 0:
                    msg_parts.append(f"filled {gaps_filled} gap(s)")
                if merged_count > 0:
                    msg_parts.append(f"merged {merged_count} line(s)")
                if split_count > 0:
                    msg_parts.append(f"split {split_count} line(s)")
                self.write_debug("  " + ", ".join(msg_parts))
            except Exception as e:
                self.report_error(f"Failed to save {sub_file}: {e}")
                continue

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


class SRTGapFiller(PostProcessor):
    """A yt-dlp post-processor for filling flicker gaps in SRT subtitles."""

    def __init__(self, *args, is_chinese: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.gap_filler = FlickerFiller(is_chinese=is_chinese)

    def _process_srt_file(self, srt_path: Path) -> tuple[bool, int]:
        if not srt_path.exists():
            self.report_error(f"SRT file not found: {srt_path}")
            return False, 0

        try:
            subs = SubtitleIO.load(srt_path)
            lang_code = extract_lang_code(srt_path)

            # Apply language line-splitting & merging
            merged_count, split_count = apply_language_processing(subs, lang_code, self)

            # Fill flicker gaps and merge identical lines
            gaps_filled = self.gap_filler.fill_flicker_gaps(subs)
            identical_merged = self.gap_filler.merge_identical_subtitle_lines(subs)
            merged_count += identical_merged

            # Write back to file
            SubtitleIO.save(subs, srt_path)

            msg_parts = [f"[{lang_code}]"]
            if gaps_filled > 0:
                msg_parts.append(f"filled {gaps_filled} gap(s)")
            if merged_count > 0:
                msg_parts.append(f"merged {merged_count} line(s)")
            if split_count > 0:
                msg_parts.append(f"split {split_count} line(s)")

            if len(msg_parts) > 1:
                self.write_debug("  " + ", ".join(msg_parts))
            return True, gaps_filled
        except Exception as e:
            self.report_error(f"Failed to process {srt_path}: {e}")
            return False, 0

    def run(self, info: dict) -> tuple[list, dict]:
        self.to_screen("Filling flicker gaps (4 frames @24fps ~167ms) in SRT subtitles")
        file_paths = info.get("__files_to_move", {})
        if not file_paths:
            self.write_debug("No subtitle files found in metadata")
            return [], info

        processed_count = 0
        total_gaps_filled = 0

        for current_path in file_paths.values():
            current_file = Path(current_path)
            if current_file.suffix.lower() != ".srt":
                continue

            success, gaps_filled = self._process_srt_file(current_file)
            if success:
                processed_count += 1
                total_gaps_filled += gaps_filled

        if processed_count > 0:
            self.to_screen(
                f"Processed {processed_count} SRT file(s), filled {total_gaps_filled} gap(s) total"
            )

        return [], info
