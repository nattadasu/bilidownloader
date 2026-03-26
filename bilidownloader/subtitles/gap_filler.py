"""Subtitle gap filling utilities for readability enhancement.

Provides frame-rate aware gap detection and filling to improve subtitle readability
by eliminating distracting rapid transitions between consecutive subtitle lines.
"""

from typing import Any, List, Tuple


# Frame rate constants (in seconds per frame)
FRAME_RATE_24FPS = 24.0
FRAME_RATE_23976FPS = 23.976
ONE_FRAME_24FPS = 1.0 / FRAME_RATE_24FPS
THREE_FRAMES_24FPS = 3.0 / FRAME_RATE_24FPS
FOUR_FRAMES_24FPS = 4.0 / FRAME_RATE_24FPS
ONE_FRAME_23976FPS = 1.0 / FRAME_RATE_23976FPS
THREE_FRAMES_23976FPS = 3.0 / FRAME_RATE_23976FPS
FRAME_GAP_TOLERANCE = 0.01


class FlickerFiller:
    """Fills distracting subtitle flicker gaps while preserving intentional 0ms gaps.

    Targets gaps up to 4 frames at 24fps (~167ms) and extends subtitle end times
    to eliminate rapid transitions that reduce readability. Preserves 0ms gaps
    which are often intentional for sentence splitting.
    """

    def __init__(self, max_gap_frames: float = 4.0, fps: float = FRAME_RATE_24FPS) -> None:
        """Initialize the FlickerFiller.

        Args:
            max_gap_frames: Maximum gap in frames to fill. Defaults to 4 frames.
            fps: Frame rate in frames per second. Defaults to 24fps.
        """
        self.max_gap_seconds = max_gap_frames / fps

    def fill_flicker_gaps(
        self, events: List[Tuple[float, float, Any]]
    ) -> List[Tuple[float, float, Any]]:
        """Fill distracting gaps between subtitle lines.

        Args:
            events: List of (start_seconds, end_seconds, event_data) tuples.

        Returns:
            List of tuples with adjusted end times for filled gaps.
        """
        if len(events) <= 1:
            return list(events)

        adjusted_events = []
        for i in range(len(events)):
            current_start, current_end, current_data = events[i]
            new_end = current_end

            if i < len(events) - 1:
                next_start = events[i + 1][0]
                gap_seconds = next_start - current_end

                if 0 < gap_seconds <= self.max_gap_seconds:
                    new_end = next_start

            adjusted_events.append((current_start, new_end, current_data))

        return adjusted_events


class GenericGapFiller:
    """Fills 1-3 frame gaps between subtitle events at 24/23.976fps."""

    def __init__(self, tolerance: float = FRAME_GAP_TOLERANCE) -> None:
        """Initialize the GenericGapFiller.

        Args:
            tolerance: Gap detection tolerance in seconds. Defaults to 0.01s.
        """
        self.tolerance = tolerance

    def fill_frame_gaps(
        self, events: List[Tuple[float, float, Any]]
    ) -> List[Tuple[float, float, Any]]:
        """Fill gaps of 1-3 frames at 24/23.976fps.

        Args:
            events: List of (start_seconds, end_seconds, event_data) tuples.

        Returns:
            List of tuples with adjusted end times for filled gaps.
        """
        if len(events) <= 1:
            return list(events)

        adjusted_events = []
        for i in range(len(events)):
            current_start, current_end, current_data = events[i]
            new_end = current_end

            if i < len(events) - 1:
                next_start = events[i + 1][0]
                gap = next_start - current_end

                if (
                    ONE_FRAME_24FPS - self.tolerance
                    <= gap
                    <= THREE_FRAMES_24FPS + self.tolerance
                    or ONE_FRAME_23976FPS - self.tolerance
                    <= gap
                    <= THREE_FRAMES_23976FPS + self.tolerance
                ):
                    new_end = next_start

            adjusted_events.append((current_start, new_end, current_data))

        return adjusted_events
