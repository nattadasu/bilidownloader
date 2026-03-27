"""Arabic RTL text processing for ASS subtitles.

Implements Arabic text corrections and RTL support based on the Aegisub Arabic Ruler plugin
(https://github.com/Bilal2453/Arabic-Ruler) to properly render Arabic subtitles in ASS format.
"""

import re


class ArabicProcessor:
    """Processes Arabic text for proper RTL rendering in ASS subtitles."""

    # RTL Control Characters (from Aegisub Arabic Ruler plugin)
    # Multi-character RTL hack for proper rendering:
    # U+202E + U+202B + U+202B + U+202E + U+202B + U+202E + U+202E + U+202E
    RTL_OVERRIDE_HACK = "\u202e\u202b\u202b\u202e\u202b\u202e\u202e\u202e"

    @staticmethod
    def reverse_ltr_punctuation(text: str) -> str:
        """Reverse LTR punctuation marks at line start.

        When rendering Arabic text in some subtitle renderers, LTR characters
        (like . , : !) at the beginning appear flipped. This reverses them and
        the following text to render correctly.

        Args:
            text: Text to process

        Returns:
            Text with reversed LTR punctuation at line start
        """
        ltr_symbols = r"[.,:;!?]+"

        # Move leading LTR punctuation to end of line
        text = re.sub(f"^({ltr_symbols})(\s?)(.*)", r"\3\2\1", text)
        text = re.sub(f'^"({ltr_symbols})(\s?)(.*)"$', r'"\3\2\1"', text)
        text = re.sub(f"^'({ltr_symbols})(\s?)(.*)'$", r"'\3\2\1'", text)

        return text

    @staticmethod
    def clean_arabic_text(text: str) -> str:
        """Clean and normalize Arabic punctuation spacing.

        Fixes common punctuation issues in Arabic text:
        - Fix spacing before Arabic question mark (؟)
        - Fix spacing before Arabic exclamation marks (!)
        - Fix spacing before Arabic semicolon (؛)
        - Fix spacing before Arabic comma (،)

        Args:
            text: Text to clean

        Returns:
            Cleaned text
        """
        # Fix spacing before Arabic question mark
        text = re.sub(r"(\S)؟", r"\1 ؟", text)
        # Fix spacing before exclamation marks at end
        text = re.sub(r"([^!])!+$", r"\1 !", text)
        # Fix spacing before Arabic semicolon
        text = re.sub(r"(\S)؛", r"\1 ؛", text)
        # Fix spacing before Arabic comma
        text = re.sub(r"(\S)،", r"\1 ،", text)

        return text

    @staticmethod
    def strip_waw_space(text: str) -> str:
        """Remove extra spaces after Arabic letter Waw (و).

        The Arabic letter Waw (و) is often used as a conjunction ('and').
        This normalizes spacing after it.

        Args:
            text: Text to process

        Returns:
            Text with normalized Waw spacing
        """
        waw = "و"
        # Remove multiple spaces after Waw
        text = re.sub(f"(\s{waw})\s+", r"\1 ", text)
        # Remove spaces after Waw at line start
        text = re.sub(f"^({waw})\s+", r"\1", text)
        return text

    @staticmethod
    def convert_huh_to_what(text: str) -> str:
        """Convert Arabic 'Huh' (هاه) to 'What' (ماذا).

        Fixes a common transliteration where 'huh' should be 'what'.

        Args:
            text: Text to convert

        Returns:
            Text with conversions applied
        """
        # Replace 'Huh' with 'What'
        return text.replace("هاه", "ماذا")

    @staticmethod
    def convert_dots_to_arabic_comma(text: str) -> str:
        """Convert ASCII dots to Arabic comma where appropriate.

        Converts dots between non-punctuation characters to Arabic comma (،).

        Args:
            text: Text to convert

        Returns:
            Text with dots converted to Arabic commas
        """
        arabic_comma = "،"
        # Replace dots between non-punctuation/non-digit characters
        text = re.sub(r"([^.\d])\.([^.\d])", rf"\1{arabic_comma}\2", text)
        return text

    @staticmethod
    def insert_rtl_override(text: str) -> str:
        """Prepend RTL override character hack for proper rendering.

        Uses the Aegisub Arabic Ruler RTL control character sequence to ensure
        proper right-to-left rendering. This combines multiple RTL control
        characters for robust rendering across different subtitle renderers.

        Args:
            text: Text to process

        Returns:
            Text with RTL override hack prepended
        """
        return ArabicProcessor.RTL_OVERRIDE_HACK + text

    @staticmethod
    def process_arabic_subtitle(text: str, apply_rtl: bool = True) -> str:
        """Apply complete Arabic text processing pipeline.

        Processes Arabic subtitle text through all corrections in order:
        1. Reverse LTR punctuation
        2. Clean Arabic punctuation spacing
        3. Strip extra Waw spacing
        4. Convert 'Huh' to 'What'
        5. Convert dots to Arabic commas
        6. Insert RTL override hack (if enabled)

        Args:
            text: Original Arabic subtitle text
            apply_rtl: Whether to prepend RTL override character (default: True)

        Returns:
            Fully processed Arabic text ready for ASS rendering
        """
        # Apply corrections in order
        text = ArabicProcessor.reverse_ltr_punctuation(text)
        text = ArabicProcessor.clean_arabic_text(text)
        text = ArabicProcessor.strip_waw_space(text)
        text = ArabicProcessor.convert_huh_to_what(text)
        text = ArabicProcessor.convert_dots_to_arabic_comma(text)

        # Finally, insert RTL override hack if requested
        if apply_rtl:
            text = ArabicProcessor.insert_rtl_override(text)

        return text
