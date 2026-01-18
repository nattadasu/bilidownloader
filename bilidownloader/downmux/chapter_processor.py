"""
Chapter processing - handles chapter formatting and embedding
"""

import subprocess as sp
from io import StringIO
from pathlib import Path
from re import search as rsearch
from typing import List, Optional, Tuple

from rich.console import Console
from rich.table import Column, Table, box

from bilidownloader.commons.filesystem import find_command
from bilidownloader.commons.ui import (
    _verbose,
    prn_cmd,
    prn_dbg,
    prn_done,
    prn_error,
    prn_info,
)
from bilidownloader.commons.utils import (
    Chapter,
    format_human_time,
    format_mkvmerge_time,
    int_to_abc,
)


class ChapterProcessor:
    """Handles chapter processing and embedding into video files"""

    def __init__(
        self,
        mkvpropedit_path: Optional[Path] = None,
        ffmpeg_path: Optional[Path] = None,
    ):
        self.mkvpropedit_path = mkvpropedit_path
        self.ffmpeg_path = ffmpeg_path

    @staticmethod
    def _sms(seconds: float) -> int:
        """Convert seconds to milliseconds"""
        return int(seconds * 1000)

    def _compare_time(self, chapter: Chapter) -> float:
        """Compare start and end time of a chapter"""
        seconds = self._sms(chapter.end_time) - self._sms(chapter.start_time)
        return seconds / 1000

    def _format_chapter(self, chapter: Chapter, title: str) -> str:
        """Format a chapter into FFmpeg metadata format"""
        start_ms = self._sms(chapter.start_time)
        end_ms = self._sms(chapter.end_time) - 1

        return f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={start_ms}\nEND={end_ms}\ntitle={title}\n"

    @staticmethod
    def _deformat_chapter(chapter: List[str] | str) -> List[Chapter]:
        """Deformat a chapter from FFmpeg metadata format"""
        chapters: List[Chapter] = []
        if isinstance(chapter, str):
            chapter = [chapter]
        for ch in chapter:
            start = int((rsearch(r"START=(\d+)", ch) or [0, 0])[1])
            end = int((rsearch(r"END=(\d+)", ch) or [0, 0])[1])
            title = (rsearch(r"title=(.*)", ch) or ["", ""])[1]
            chapters.append(
                Chapter(start_time=start / 1000, end_time=end / 1000, title=title)
            )
        return chapters

    @staticmethod
    def _to_mkvmerge_chapter(chapters: List[Chapter]) -> List[str]:
        """Convert a list of chapters to mkvmerge format"""
        mkv_chapters: List[str] = []
        for i, chapter in enumerate(chapters):
            mkv_chapters.append(
                (
                    f"CHAPTER{i + 1:02d}={format_mkvmerge_time(chapter.start_time)}\n"
                    f"CHAPTER{i + 1:02d}NAME={chapter.title}"
                )
            )
        return mkv_chapters

    def embed_chapters(self, chapters: List[Chapter], video_path: Path) -> Path:
        """Create chapter metadata and merge it into the video file"""
        if not chapters:
            prn_dbg("No chapters found, skipping chapter embedding")
            return video_path

        # Verify video file exists before processing
        if not video_path.exists():
            prn_error(f"Video file not found: {video_path}. Cannot embed chapters.")
            return video_path

        prn_info("Creating chapters")

        metadata_path = video_path.with_suffix(".txt")
        mkvpropedit = (
            str(self.mkvpropedit_path) if self.mkvpropedit_path else "mkvpropedit"
        )
        metadata_path.write_text("")

        # Get video duration using ffprobe
        ffprobe = find_command("ffprobe")
        if not ffprobe and self.ffmpeg_path:
            ffprobe = self.ffmpeg_path.with_stem("ffprobe")
        if not ffprobe or not ffprobe.exists():
            prn_error(
                "ffprobe is not found in the system, make sure it's available "
                "in your ffmpeg directory/installation"
            )
            return video_path

        ffprobe_cmd = [
            str(ffprobe),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        prn_cmd(ffprobe_cmd)
        result = sp.run(
            ffprobe_cmd,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0 or not result.stdout.strip():
            prn_error(
                f"Failed to get video duration from {video_path.name}. "
                f"Skipping chapter embedding."
            )
            return video_path

        try:
            total_duration = float(result.stdout.strip())
        except ValueError:
            prn_error(
                f"Invalid duration value from ffprobe: '{result.stdout.strip()}'. "
                f"Skipping chapter embedding."
            )
            return video_path

        # Remove existing chapters and metadata from the video
        prn_dbg(f"Removing existing metadata from {video_path.name}, if any")
        mkvpropedit_cmd1 = [
            mkvpropedit,
            str(video_path),
            "--edit",
            "track:v1",
            "--delete",
            "name",
            "--edit",
            "track:a1",
            "--delete",
            "name",
            "--delete",
            "language",
            "--tags",
            "all:",
            "--chapters",
            "",
            "--verbose" if _verbose else "--quiet",
        ]
        prn_cmd(mkvpropedit_cmd1)
        sp.run(
            mkvpropedit_cmd1,
            check=True,
        )

        # Format and modify chapter information
        formatted_chapters: List[str] = []
        part_index = 1

        def pidx(index: int) -> tuple[str, int]:
            return f"Part {int_to_abc(index)}", index + 1

        if len(chapters) == 2:
            chapters[0].title = "Episode"
            chapters[1].title = "Outro"

        # Pre-process: merge short brandings into opening
        merged_chapters: List[Chapter] = []
        i = 0
        while i < len(chapters):
            chapter = chapters[i]
            compr = self._compare_time(chapter)

            # Check if this is a very short chapter (< 2s) followed by Intro
            if i + 1 < len(chapters):
                next_chapter = chapters[i + 1]

                # If current chapter is < 2s and next is Intro, merge them
                if compr < 2 and next_chapter.title == "Intro":
                    merged_chapter = Chapter(
                        start_time=chapter.start_time,
                        end_time=next_chapter.end_time,
                        title="Intro",
                    )
                    merged_chapters.append(merged_chapter)
                    i += 2
                    continue

            merged_chapters.append(chapter)
            i += 1

        chapters = merged_chapters

        for i, chapter in enumerate(chapters):
            compr = self._compare_time(chapter)
            title = chapter.title

            try:
                next_chapter = chapters[i + 1]
            except IndexError:
                next_chapter = None

            if title not in ["Intro", "Outro"]:
                title, _ = pidx(part_index)
                if compr < 25:
                    title = "Brandings"
                elif compr >= 25 and compr <= 40:
                    title = "Recap"
                elif next_chapter and next_chapter.title == "Intro":
                    title = "Prologue"
                else:
                    part_index += 1
            else:
                if title == "Intro":
                    title = "Opening"
                    if compr > 120:
                        title, part_index = pidx(part_index)
                elif title == "Outro":
                    title = "Ending"

            formatted_chapters.append(self._format_chapter(chapter, title))

            # Add parts between chapters if there's a gap
            if i < len(chapters) - 1:
                next_chapter = chapters[i + 1]
                if chapter.end_time < next_chapter.start_time - 0.001:
                    title, part_index = pidx(part_index)
                    gap_chapter = Chapter(
                        start_time=chapter.end_time,
                        end_time=next_chapter.start_time,
                        title=title,
                    )
                    formatted_chapters.append(
                        self._format_chapter(gap_chapter, gap_chapter.title)
                    )

        # Append final chapter that runs to the end of the video
        try:
            if chapters[-1].end_time < total_duration:
                drn_ = total_duration - chapters[-1].end_time
                if drn_ <= 10:
                    last_ch = self._deformat_chapter(formatted_chapters[-1])
                    last_ch[0].end_time = total_duration
                    formatted_chapters[-1] = self._format_chapter(
                        last_ch[0], last_ch[0].title
                    )
                else:
                    is_under_minute = drn_ < 60
                    title, _ = pidx(part_index)
                    final_chapter = Chapter(
                        start_time=chapters[-1].end_time,
                        end_time=total_duration,
                        title="Preview" if is_under_minute else title,
                    )
                    formatted_chapters.append(
                        self._format_chapter(final_chapter, final_chapter.title)
                    )
        except IndexError:
            prn_error("This video does not have any chapters")
            prn_dbg(f"Removing {metadata_path.name}")
            metadata_path.unlink(True)
            return video_path

        def fmt_timing(
            title: str, start: float, end: float
        ) -> Tuple[str, str, str, float, str]:
            """Format timing for table"""
            dur = end - start
            return (
                title,
                format_human_time(start),
                format_human_time(end),
                round(dur, 2),
                format_human_time(dur),
            )

        prn_dbg(f"Chapters to write: {len(formatted_chapters)}")
        deform = self._deformat_chapter(formatted_chapters)
        if len([ch for ch in deform if "Part" in ch.title]) == 1:
            for i, ch in enumerate(deform):
                if not ch.title.startswith("Part"):
                    continue
                deform[i] = Chapter(
                    start_time=ch.start_time,
                    end_time=ch.end_time,
                    title="Episode",
                )
                break
        fdform = [fmt_timing(ch.title, ch.start_time, ch.end_time) for ch in deform]
        try:
            table = Table(
                Column("Title", justify="right"),
                Column("Starts", justify="right", style="magenta"),
                Column("Ends", justify="right", style="green"),
                Column("Duration", justify="right"),
                box=box.ROUNDED,
            )
            for title, start, end, dur, hdur in fdform:
                table.add_row(title, start, end, str(int(dur)) + f"s ({hdur})")

            # Render table to string and add 6 space left indent
            table_str = StringIO()
            temp_console = Console(
                file=table_str, highlight=False, force_terminal=True, width=50
            )
            temp_console.print(table)
            for line in table_str.getvalue().splitlines():
                Console(highlight=False).print(f"       {line}")
        except Exception:
            for title, start, end, _, hdur in fdform:
                prn_info(f"  - {title}: {start} -[{hdur}]-> {end}")
        metadata_path.write_text("\n".join(self._to_mkvmerge_chapter(deform)))

        # Merge changes to the video
        prn_info("Embedding chapters into the video file")
        mkvpropedit_cmd2 = [
            mkvpropedit,
            str(video_path),
            "--chapters",
            str(metadata_path),
            "--verbose" if _verbose else "--quiet",
        ]
        prn_cmd(mkvpropedit_cmd2)
        sp.run(
            mkvpropedit_cmd2,
            check=True,
        )
        prn_done("Chapters have been added to the video file")

        prn_dbg(f"Removing {metadata_path.name}")
        metadata_path.unlink(True)

        return Path(video_path)
