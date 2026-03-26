from typing import Any, List, Tuple


class FlickerFiller:
    """
    Fills distracting flicker gaps (1-100ms) between subtitle events while
    preserving 0ms gaps (intentional consecutive subtitles).
    
    This is useful for fixing rapid subtitle flickering that occurs when
    subtitles transition too quickly (< 100ms) between lines, making them
    hard to read. It specifically avoids filling 0ms gaps which are often
    intentional for proper sentence splitting.
    """

    # Flicker detection thresholds
    MIN_FLICKER_MS = 1  # Minimum gap to be considered a flicker
    MAX_FLICKER_MS = 100  # Maximum gap considered distracting

    def __init__(
        self,
        min_gap_ms: int = 1,
        max_gap_ms: int = 100,
        tolerance: float = 0.001,
    ) -> None:
        """
        Initializes the FlickerFiller.

        Args:
            min_gap_ms (int): Minimum gap in milliseconds to be considered for filling.
                             Defaults to 1ms (ignores 0ms gaps).
            max_gap_ms (int): Maximum gap in milliseconds to be filled.
                             Defaults to 100ms.
            tolerance (float): Tolerance in seconds for gap detection.
                              Defaults to 0.001 (1ms).
        """
        self.min_gap_ms = min_gap_ms
        self.max_gap_ms = max_gap_ms
        self.tolerance = tolerance

    def fill_flicker_gaps(
        self, events: List[Tuple[float, float, Any]]
    ) -> List[Tuple[float, float, Any]]:
        """
        Fill distracting gaps between subtitle lines (1-100ms).

        Args:
            events: A list of tuples, where each tuple represents a subtitle event:
                    (start_seconds: float, end_seconds: float, original_event_data: Any)

        Returns:
            A new list of tuples with adjusted end times for events where flickers
            were filled.
        """
        if len(events) <= 1:
            return list(events)

        adjusted_events = []
        for i in range(len(events)):
            current_start, current_end, current_data = events[i]
            new_end = current_end

            if i < len(events) - 1:
                next_start, _, _ = events[i + 1]
                gap_seconds = next_start - current_end
                gap_ms = gap_seconds * 1000

                # Fill gaps in the flicker range (min_gap_ms < gap <= max_gap_ms)
                # Preserve 0ms gaps (intentional consecutive subtitles)
                if (
                    self.min_gap_ms < gap_ms <= self.max_gap_ms
                    or (gap_ms > 0 and gap_ms < self.min_gap_ms)
                ):
                    # Extend to next start time to eliminate the gap
                    new_end = next_start

            adjusted_events.append((current_start, new_end, current_data))

        return adjusted_events


class GenericGapFiller:
    """
    Provides a generic method to fill 1-3 frame gaps between subtitle events.
    This class assumes that input event times are in seconds (float).
    """

    # Constants for frame gap detection
    ONE_FRAME_24FPS = 1.0 / 24.0  # 0.0417 seconds
    THREE_FRAMES_24FPS = 3.0 / 24.0  # 0.125 seconds
    ONE_FRAME_23976FPS = 1.0 / 23.976  # 0.0417 seconds
    THREE_FRAMES_23976FPS = 3.0 / 23.976  # 0.125125 seconds
    TOLERANCE = 0.01  # 1 centisecond tolerance for ASS, 1 millisecond for SRT

    def __init__(self, tolerance: float = 0.01) -> None:
        """
        Initializes the GenericGapFiller.

        Args:
            tolerance (float): The tolerance for gap detection.
                               Defaults to 0.01 (1 centisecond) suitable for ASS.
                               Use 0.001 (1 millisecond) for SRT.
        """
        self.TOLERANCE = tolerance

    def fill_frame_gaps(
        self, events: List[Tuple[float, float, Any]]
    ) -> List[Tuple[float, float, Any]]:
        """
        Fill gaps between subtitle lines if they are approximately 1-3 frames apart.

        Args:
            events: A list of tuples, where each tuple represents a subtitle event:
                    (start_seconds: float, end_seconds: float, original_event_data: Any)
                    `original_event_data` can be the original ASS event object, SRT text, etc.

        Returns:
            A new list of tuples with adjusted end times for events where gaps were filled.
        """
        if len(events) <= 1:
            return list(events)  # Return a copy to ensure immutability if needed

        adjusted_events = []
        for i in range(len(events)):
            current_start, current_end, current_data = events[i]
            new_end = current_end

            if i < len(events) - 1:
                next_start, _, _ = events[i + 1]

                gap = next_start - current_end

                # Check if gap is between 1-3 frames at either 24fps or 23.976fps
                # At 24fps: 1 frame = 0.0417s, 3 frames = 0.125s
                # At 23.976fps: 1 frame = 0.0417s, 3 frames = 0.125125s
                if (
                    self.ONE_FRAME_24FPS - self.TOLERANCE
                    <= gap
                    <= self.THREE_FRAMES_24FPS + self.TOLERANCE
                    or self.ONE_FRAME_23976FPS - self.TOLERANCE
                    <= gap
                    <= self.THREE_FRAMES_23976FPS + self.TOLERANCE
                ):
                    # Fill the gap by extending the end time to the next start time
                    new_end = next_start

            adjusted_events.append((current_start, new_end, current_data))

        return adjusted_events
