"""Unified subtitle I/O using pysubs2.

Provides a consistent interface for loading, saving, and manipulating
subtitle files in various formats (SRT, ASS, SSA, etc.).
"""

import re
from pathlib import Path

import pysubs2
from pysubs2 import SSAFile, SSAStyle


class SubtitleStyle:
    """Predefined subtitle styles."""

    DEFAULT = SSAStyle(
        fontname="Noto Sans",
        fontsize=80,
        primarycolor="&H00FFFFFF",
        secondarycolor="&H00FFFFFF",
        outlinecolor="&H00000000",
        backcolor="&H80000000",
        bold=True,
        italic=False,
        underline=False,
        strikeout=False,
        scalex=100,
        scaley=100,
        spacing=0,
        angle=0,
        borderstyle=1,
        outline=4,
        shadow=1.2,
        alignment=2,
        marginl=153,
        marginr=153,
        marginv=64,
        encoding=1,
    )

    THAI = SSAStyle(
        fontname="Arial",
        fontsize=80,
        primarycolor="&H00FFFFFF",
        secondarycolor="&H00FFFFFF",
        outlinecolor="&H00000000",
        backcolor="&H80000000",
        bold=True,
        italic=False,
        underline=False,
        strikeout=False,
        scalex=100,
        scaley=100,
        spacing=0,
        angle=0,
        borderstyle=1,
        outline=4,
        shadow=1.2,
        alignment=2,
        marginl=153,
        marginr=153,
        marginv=64,
        encoding=1,
    )

    ZH_HANS = SSAStyle(
        fontname="Noto Sans CJK SC",
        fontsize=80,
        primarycolor="&H00FFFFFF",
        secondarycolor="&H00FFFFFF",
        outlinecolor="&H00000000",
        backcolor="&H80000000",
        bold=False,
        italic=False,
        underline=False,
        strikeout=False,
        scalex=100,
        scaley=100,
        spacing=0,
        angle=0,
        borderstyle=1,
        outline=4,
        shadow=1.2,
        alignment=2,
        marginl=153,
        marginr=153,
        marginv=64,
        encoding=1,
    )

    ZH_HANT = SSAStyle(
        fontname="Noto Sans CJK TC",
        fontsize=80,
        primarycolor="&H00FFFFFF",
        secondarycolor="&H00FFFFFF",
        outlinecolor="&H00000000",
        backcolor="&H80000000",
        bold=False,
        italic=False,
        underline=False,
        strikeout=False,
        scalex=100,
        scaley=100,
        spacing=0,
        angle=0,
        borderstyle=1,
        outline=4,
        shadow=1.2,
        alignment=2,
        marginl=153,
        marginr=153,
        marginv=64,
        encoding=1,
    )

    ARABIC = SSAStyle(
        fontname="Noto Naskh Arabic",
        fontsize=120,
        primarycolor="&H00FFFFFF",
        secondarycolor="&H00FFFFFF",
        outlinecolor="&H00000000",
        backcolor="&H80000000",
        bold=False,
        italic=False,
        underline=False,
        strikeout=False,
        scalex=100,
        scaley=100,
        spacing=0,
        angle=0,
        borderstyle=1,
        outline=4,
        shadow=1.2,
        alignment=2,
        marginl=153,
        marginr=153,
        marginv=64,
        encoding=1,
    )


class SubtitleIO:
    """Unified subtitle file I/O using pysubs2."""

    @staticmethod
    def load(filepath: Path) -> SSAFile:
        """Load subtitle file in any supported format.

        Args:
            filepath: Path to subtitle file

        Returns:
            SSAFile object with loaded subtitles
        """
        subs = pysubs2.load(str(filepath))
        SubtitleIO.split_speaker_dialogues(subs)
        return subs

    @staticmethod
    def save(subs: SSAFile, filepath: Path) -> None:
        """Save subtitle file in appropriate format.

        Args:
            subs: SSAFile object to save
            filepath: Path where to save (format detected from extension)
        """
        subs.save(str(filepath))

    @staticmethod
    def apply_style(
        subs: SSAFile,
        style: SSAStyle | None = None,
        is_thai: bool = False,
        lang_code: str | None = None,
        style_name: str | None = None,
    ) -> None:
        """Apply or update style in subtitle file.

        Args:
            subs: SSAFile object to update
            style: SSAStyle object to apply (overrides lang_code)
            is_thai: Whether to use Thai style defaults (for backwards compatibility)
            lang_code: Language code (e.g., 'ar', 'zh-Hans', 'zh-Hant', 'th')
            style_name: Override the style name
        """
        if style is None:
            if lang_code:
                if lang_code == "ar":
                    style = SubtitleStyle.ARABIC
                elif lang_code in ("zh-Hans", "zh"):
                    style = SubtitleStyle.ZH_HANS
                elif lang_code == "zh-Hant":
                    style = SubtitleStyle.ZH_HANT
                elif lang_code == "th":
                    style = SubtitleStyle.THAI
                else:
                    style = SubtitleStyle.DEFAULT
            else:
                style = SubtitleStyle.THAI if is_thai else SubtitleStyle.DEFAULT

        if style_name is None:
            if lang_code:
                if lang_code == "ar":
                    style_name = "Default-Arabic"
                elif lang_code in ("zh-Hans", "zh"):
                    style_name = "Default-ZH-Hans"
                elif lang_code == "zh-Hant":
                    style_name = "Default-ZH-Hant"
                elif lang_code == "th":
                    style_name = "Default-Thai"
                else:
                    style_name = "Default"
            else:
                style_name = "Default-Thai" if is_thai else "Default"

        subs.styles[style_name] = style

        for event in subs.events:
            event.style = style_name

    @staticmethod
    def convert_srt_to_ass(
        srt_subs: SSAFile,
        is_thai: bool = False,
    ) -> SSAFile:
        """Convert SRT subtitles to ASS format with styling.

        Args:
            srt_subs: SSAFile loaded from SRT
            is_thai: Whether to apply Thai styling

        Returns:
            SSAFile with ASS formatting and styles applied
        """
        style = SubtitleStyle.THAI if is_thai else SubtitleStyle.DEFAULT
        style_name = "Default-Thai" if is_thai else "Default"
        srt_subs.styles[style_name] = style

        for event in srt_subs.events:
            event.style = style_name

        return srt_subs

    @staticmethod
    def split_speaker_dialogues(subs: SSAFile) -> None:
        """Split lines representing speaker split with a line break (\\N).

        Args:
            subs: SSAFile object to process
        """
        for event in subs.events:
            if not event.text:
                continue
            # Match lines starting with a dash, optionally preceded by ASS style tags/whitespace
            if re.match(r"^(?:\{[^}]*\}|\s)*-\s*", event.text):
                # Replace ' - ' (space-dash-space) with '\\N- '
                event.text = re.sub(r"\s+-\s+", r"\\N- ", event.text)
