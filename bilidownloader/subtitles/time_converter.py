"""Unified subtitle time format converters.

Handles conversion between seconds (float) and various subtitle time formats:
- SRT: HH:MM:SS,mmm (hours, minutes, seconds, milliseconds)
- ASS: H:MM:SS.CC (hours, minutes, seconds, centiseconds)
"""

from abc import ABC, abstractmethod


class TimeConverter(ABC):
    """Abstract base for subtitle time format converters."""

    @abstractmethod
    def to_seconds(self, time_str: str) -> float:
        """Convert time string to seconds."""

    @abstractmethod
    def from_seconds(self, seconds: float) -> str:
        """Convert seconds to time string."""


class SRTTimeConverter(TimeConverter):
    """SRT time format converter (HH:MM:SS,mmm)."""

    def to_seconds(self, time_str: str) -> float:
        """Convert SRT time string to seconds.

        Args:
            time_str: Time in format HH:MM:SS,mmm

        Returns:
            Time in seconds as float
        """
        time_str = time_str.replace(",", ".")
        parts = time_str.split(":")
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds_parts = parts[2].split(".")
        seconds = int(seconds_parts[0])
        milliseconds = int(seconds_parts[1]) if len(seconds_parts) > 1 else 0

        return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0

    def from_seconds(self, seconds: float) -> str:
        """Convert seconds to SRT time format.

        Args:
            seconds: Time in seconds

        Returns:
            Time string in format HH:MM:SS,mmm
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        milliseconds = int((seconds % 1) * 1000)

        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


class ASSTimeConverter(TimeConverter):
    """ASS time format converter (H:MM:SS.CC)."""

    def to_seconds(self, time_str: str) -> float:
        """Convert ASS time string to seconds.

        Args:
            time_str: Time in format H:MM:SS.CC

        Returns:
            Time in seconds as float
        """
        parts = time_str.split(":")
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds_parts = parts[2].split(".")
        seconds = int(seconds_parts[0])
        centiseconds = int(seconds_parts[1]) if len(seconds_parts) > 1 else 0

        return hours * 3600 + minutes * 60 + seconds + centiseconds / 100.0

    def from_seconds(self, seconds: float) -> str:
        """Convert seconds to ASS time format.

        Args:
            seconds: Time in seconds

        Returns:
            Time string in format H:MM:SS.CC
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centiseconds = int((seconds % 1) * 100)

        return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"
