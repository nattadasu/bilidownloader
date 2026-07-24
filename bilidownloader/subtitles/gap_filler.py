"""Subtitle gap filling utilities for readability enhancement.

Provides frame-rate aware gap detection and filling to improve subtitle readability
by eliminating distracting rapid transitions between consecutive subtitle lines.
"""

from pysubs2 import SSAFile


class FlickerFiller:
    """Fills distracting subtitle flicker gaps by aligning adjacent subtitle cues in-place.

    Targets gaps up to 225ms (standard duration for ~5 frames at 24fps)
    and pushes the start times of the subsequent cues backward to meet the end times of the
    previous cues.
    """

    MAX_GAP_MS = 225

    def fill_flicker_gaps(self, subs: SSAFile) -> int:
        """Fill timing gaps in-place on a pysubs2 SSAFile.

        Adjacent cues separated by <= MAX_GAP_MS ms are pushed together so that
        the start time of the second cue equals the end time of the first.

        Returns:
            Number of gaps filled.
        """
        if not subs.events or len(subs.events) < 2:
            return 0

        filled = 0
        sorted_events = sorted(subs.events, key=lambda e: e.start)

        for i in range(len(sorted_events) - 1):
            curr = sorted_events[i]
            nxt = sorted_events[i + 1]

            gap = nxt.start - curr.end
            if 0 < gap <= self.MAX_GAP_MS:
                nxt.start = curr.end
                filled += 1

        return filled

    def merge_identical_subtitle_lines(
        self, subs: SSAFile, tolerance_ms: int = 0
    ) -> int:
        """Merge consecutive subtitle events with identical text in-place.

        Args:
            subs: The pysubs2 SSAFile object to process.
            tolerance_ms: Maximum time difference in ms for merging.

        Returns:
            Number of lines merged.
        """
        if not subs.events:
            return 0

        original_count = len(subs.events)
        merged_events = []

        for event in subs.events:
            if not event.text.strip():
                continue

            if merged_events:
                prev = merged_events[-1]
                if (
                    prev.text.strip() == event.text.strip()
                    and prev.style == event.style
                ):
                    time_diff = abs(event.start - prev.end)
                    if time_diff <= tolerance_ms:
                        prev.end = max(prev.end, event.end)
                        continue

            merged_events.append(event)

        subs.events = merged_events
        return original_count - len(subs.events)
