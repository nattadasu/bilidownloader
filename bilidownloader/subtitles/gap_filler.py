"""Subtitle gap filling utilities for readability enhancement.

Provides frame-rate aware gap detection and filling to improve subtitle readability
by eliminating distracting rapid transitions between consecutive subtitle lines.
"""

from typing import Any, List, Tuple

# Frame rate constants (in seconds per frame)
FRAME_RATE_24FPS = 24.0


class FlickerFiller:
    """Fills distracting subtitle flicker gaps while preserving intentional 0ms gaps.

    Targets gaps up to 4 frames at 24fps (~167ms) and extends subtitle end times
    to eliminate rapid transitions that reduce readability. Preserves 0ms gaps
    which are often intentional for sentence splitting.
    """

    def __init__(
        self, max_gap_frames: float = 4.0, fps: float = FRAME_RATE_24FPS
    ) -> None:
        """Initialize the FlickerFiller.

        Args:
            max_gap_frames: Maximum gap in frames to fill. Defaults to 4 frames.
            fps: Frame rate in frames per second. Defaults to 24fps.
        """
        self.max_gap_seconds = max_gap_frames / fps

    def fill_flicker_gaps(
        self, events: List[Tuple[float, float, Any]]
    ) -> tuple[List[Tuple[float, float, Any]], int]:
        """Fill distracting gaps between subtitle lines.

        Args:
            events: List of (start_seconds, end_seconds, event_data) tuples.

        Returns:
            Tuple of (adjusted_events, gaps_filled_count).
        """
        if len(events) <= 1:
            return list(events), 0

        adjusted_events = []
        gaps_filled = 0

        for i in range(len(events)):
            current_start, current_end, current_data = events[i]
            new_end = current_end

            if i < len(events) - 1:
                next_start = events[i + 1][0]
                gap_seconds = next_start - current_end

                if 0 < gap_seconds <= self.max_gap_seconds:
                    new_end = next_start
                    gaps_filled += 1

            adjusted_events.append((current_start, new_end, current_data))

        return adjusted_events, gaps_filled
