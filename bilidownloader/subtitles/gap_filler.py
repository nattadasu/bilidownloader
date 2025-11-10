from typing import Any, List, Tuple


class GenericGapFiller:
    """
    Provides a generic method to fill 3-frame gaps between subtitle events.
    This class assumes that input event times are in seconds (float).
    """

    # Constants for 3-frame gap detection
    THREE_FRAMES_24FPS = 3.0 / 24.0  # 0.125 seconds
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
        Fill gaps between subtitle lines if they are approximately 3 frames apart.

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

                if (
                    abs(gap - self.THREE_FRAMES_24FPS) <= self.TOLERANCE
                    or abs(gap - self.THREE_FRAMES_23976FPS) <= self.TOLERANCE
                ):
                    # Fill the gap by extending the end time to the next start time
                    new_end = next_start

            adjusted_events.append((current_start, new_end, current_data))

        return adjusted_events
