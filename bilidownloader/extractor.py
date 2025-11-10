import subprocess as sp
import traceback
from html import unescape
from io import BytesIO
from json import loads as jloads
from pathlib import Path
from re import IGNORECASE
from re import search as rsearch
from re import sub as rsub
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

import requests as reqs
from fake_useragent import UserAgent
from PIL import Image
from rich.console import Console
from rich.table import Column, Table, box
from yt_dlp import YoutubeDL as YDL

from bilidownloader.alias import SERIES_ALIASES
from bilidownloader.api import BiliApi, BiliHtml
from bilidownloader.constants import (
    DEFAULT_COOKIES,
    DEFAULT_HISTORY,
    DEFAULT_WATCHLIST,
    REINSTALL_ARGS,
    available_res,
)
from bilidownloader.filesystem import find_command
from bilidownloader.fontmanager import initialize_fonts, loop_font_lookup
from bilidownloader.history import History
from bilidownloader.ui import prn_done, prn_error, prn_info, push_notification
from bilidownloader.utils import (
    BenchClock,
    Chapter,
    DataExistError,
    check_package,
    format_human_time,
    format_mkvmerge_time,
    int_to_abc,
    langcode_to_str,
    pluralize,
    sanitize_filename,
)
from bilidownloader.utils import (
    SubtitleLanguage as SubLang,
)
from bilidownloader.watchlist import Watchlist

ua = UserAgent()
uagent = ua.chrome


class BiliProcess:
    def __init__(
        self,
        cookie: Path = DEFAULT_COOKIES,
        history: Path = DEFAULT_HISTORY,
        watchlist: Path = DEFAULT_WATCHLIST,
        resolution: available_res = 1080,  # type: ignore
        is_avc: bool = False,
        download_pv: bool = False,
        ffmpeg_path: Optional[Path] = None,
        mkvpropedit_path: Optional[Path] = None,
        mkvmerge_path: Optional[Path] = None,
        notification: bool = False,
        srt: bool = False,
        dont_thumbnail: bool = False,
        dont_rescale: bool = False,
        dont_convert: bool = False,
        subtitle_lang: SubLang = SubLang.en,
        only_audio: bool = False,
    ) -> None:
        """
        Initialize BiliProcess object
        Args:
            cookie (Path, optional): Path to the cookie file
            history (Path, optional): Path to the history file. Defaults to DEFAULT_HISTORY.
            watchlist (Path, optional): Path to the watchlist file. Defaults to DEFAULT_WATCHLIST.
            resolution (available_res, optional): Video resolution. Defaults to 1080.
            is_avc (bool, optional): Use AVC codec. Defaults to False.
            download_pv (bool, optional): Download PV. Defaults to False.
            ffmpeg_path (Optional[Path], optional): Path to ffmpeg. Defaults to None.
            mkvpropedit_path (Optional[Path], optional): Path to mkvpropedit. Defaults to None.
            mkvmerge_path (Optional[Path], optional): Path to mkvmerge. Defaults to None.
            notification (bool, optional): Enable notification. Defaults to False.
            srt (bool, optional): Use SRT subtitles. Defaults to False.
            dont_thumbnail (bool, optional): Disable thumbnail download. Defaults to False.
            dont_rescale (bool, optional): Disable rescaling. Defaults to False.
            dont_convert (bool, optional): Disable SRT to ASS conversion. Defaults to False.
            subtitle_lang (SubLang, optional): Subtitle language. Defaults to SubLang.en.
            only_audio (bool, optional): Only download audio. Defaults to False.
        """
        self.watchlist = watchlist
        self.history = history
        self.cookie = cookie
        self.resolution = resolution
        self.is_avc = is_avc
        self.download_pv = download_pv
        self.ffmpeg_path = ffmpeg_path
        self.mkvpropedit_path = mkvpropedit_path
        self.mkvmerge_path = mkvmerge_path
        self.notification = notification
        self.srt = srt
        self.dont_thumbnail = dont_thumbnail
        self.dont_rescale = dont_rescale
        self.dont_convert = dont_convert
        self.subtitle_lang = subtitle_lang.value
        self.only_audio = only_audio

        if not srt and srt == check_package("ass"):
            # fmt: off
            prn_error((
                "`ass` package is not found inside the environment, "
                "please reinstall `bilidownloader` by executing this command to "
                "install the required package:"
            ))
            prn_error(REINSTALL_ARGS)
            # fmt: on
            prn_info("Reverting to use SRT")
            self.srt = True
        else:
            initialize_fonts()

    @staticmethod
    def ep_url(season_id: Union[int, str], episode_id: Union[int, str]) -> str:
        """
        Convert known IDs into proper, English episode URL.

        Args:
            season_id (Union[int, str]): Season ID
            episode_id (Union[int, str]): Episode ID

        Returns:
            str: English episode URL
        """
        return f"https://www.bilibili.tv/en/play/{season_id}/{episode_id}"

    def _get_video_info(self, episode_url: str) -> Union[Any, Dict[str, Any], None]:
        """
        Get video information from yt-dlp.

        Args:
            episode_url (str): URL to the episode

        Returns:
            Union[Any, Dict[str, Any], None]: Video information
        """
        ydl_opts = {
            "cookiefile": str(self.cookie),
            "extract_flat": "discard_in_playlist",
            "forcejson": True,
            "fragment_retries": 10,
            "ignoreerrors": "only_download",
            "noprogress": True,
            "postprocessors": [
                {"key": "FFmpegConcat", "only_multi_video": True, "when": "playlist"}
            ],
            "retries": 10,
            "simulate": True,
            # Do not show details
            "verbose": False,
            "quiet": True,
            "referer": "https://www.bilibili.tv/",
        }
        if self.ffmpeg_path:
            ydl_opts["ffmpeg_location"] = str(self.ffmpeg_path)
        with YDL(ydl_opts) as ydl:  # type: ignore
            return ydl.extract_info(episode_url, download=False)

    @staticmethod
    def _get_episode_chapters(raw_info: Dict[str, Any]) -> List[Chapter]:
        """
        Get chapters from video metadata.

        Args:
            raw_info (Dict[str, Any]): Video metadata

        Returns:
            List[Chapter]: List of chapters
        """
        try:
            return [Chapter(**chs) for chs in raw_info["chapters"]]
        except Exception as _:
            return []

    @staticmethod
    def _sms(seconds: float) -> int:
        """
        Converts seconds to milliseconds.

        Args:
            seconds (float): The number of seconds to convert.

        Returns:
            int: The number of milliseconds."""
        return int(seconds * 1000)

    def _compare_time(self, chapter: Chapter) -> float:
        """
        Compares the start and end time of a chapter.

        Args:
            chapter (Chapter): The chapter to compare.

        Returns:
            float: The difference between the start and end time in seconds.
        """
        seconds = self._sms(chapter.end_time) - self._sms(chapter.start_time)
        return seconds / 1000

    def _format_chapter(self, chapter: Chapter, title: str) -> str:
        """
        Formats a chapter into FFmpeg metadata format.

        Args:
            chapter (Chapter): The chapter to format.
            title (str): The title of the chapter.

        Returns:
            str: The formatted chapter block.
        """
        start_ms = self._sms(chapter.start_time)
        end_ms = self._sms(chapter.end_time) - 1  # Subtract 1 ms for precision

        # Return the formatted chapter string
        return f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={start_ms}\nEND={end_ms}\ntitle={title}\n"

    @staticmethod
    def _deformat_chapter(chapter: List[str] | str) -> List[Chapter]:
        """
        Deformats a chapter from FFmpeg metadata format.

        Args:
            chapter (List[str]): The chapter to deformat.

        Returns:
            List[Chapter]: The deformatted chapter block.
        """
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
        """
        Converts a list of chapters to mkvmerge format.

        Args:
            chapters (List[Chapter]): The list of chapters to convert.

        Returns:
            :ost[str]: The chapters in mkvmerge format.
        """
        mkv_chapters: List[str] = []
        for i, chapter in enumerate(chapters):
            mkv_chapters.append(
                (
                    f"CHAPTER{i + 1:02d}={format_mkvmerge_time(chapter.start_time)}\n"
                    f"CHAPTER{i + 1:02d}NAME={chapter.title}"
                )
            )
        return mkv_chapters

    def _embed_chapters(self, chapters: List[Chapter], video_path: Path) -> Path:
        """
        Creates chapter metadata and merges it into the video file.

        Args:
            chapters (List[Chapter]): The list of chapters to process.
            video_path (Path): The path to the video file.

        Returns:
            Path: The path to the video file with added chapters.
        """
        prn_info(f"Creating chapters for {video_path.name}")
        # 1. Extract metadata and calculate the total duration
        metadata_path = video_path.with_suffix(".txt")
        mkvpropedit = (
            str(self.mkvpropedit_path) if self.mkvpropedit_path else "mkvpropedit"
        )
        metadata_path.write_text("")

        # Get video duration using ffprobe
        # fmt: off
        ffprobe = find_command("ffprobe")
        if not ffprobe and self.ffmpeg_path:
            # try replacing 
            ffprobe = self.ffmpeg_path.with_stem("ffprobe")
        if not ffprobe or not ffprobe.exists():
            prn_error((
                "ffprobe is not found in the system, make sure it's available "
                "in your ffmpeg directory/installation"
            ))
            return video_path
        result = sp.run([
            str(ffprobe), "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ], capture_output=True, text=True)
        # fmt: on
        total_duration = float(result.stdout.strip())

        # 1B. Remove existing chapters and metadata from the video
        prn_info(f"Removing existing metadata from {video_path.name}, if any")
        # fmt: off
        sp.run([
            mkvpropedit, str(video_path),
            "--edit", "track:v1",
            "--delete", "name",
            "--edit", "track:a1",
            "--delete", "name",
            "--delete", "language",
            # "--delete-attachments", "mime-type:font/ttf",
            # "--delete-attachments", "mime-type:font/otf",
            "--tags", "all:",
            "--chapters", "",
            "--quiet",
        ], check=True)
        # fmt: on

        # 2. Format and modify chapter information
        formatted_chapters: List[str] = []
        part_index = 1

        def pidx(index: int) -> tuple[str, int]:
            return f"Part {int_to_abc(index)}", index + 1

        if len(chapters) == 2:
            chapters[0].title = "Episode"
            chapters[1].title = "Outro"

        for i, chapter in enumerate(chapters):
            compr = self._compare_time(chapter)
            title = chapter.title

            try:
                next_chapter = chapters[i + 1]
            except IndexError as _:
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

            # Format the current chapter
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
        except IndexError as _:
            prn_error("This video does not have any chapters")
            prn_info(f"Removing {metadata_path.name}")
            metadata_path.unlink(True)
            return video_path

        def fmt_timing(
            title: str, start: float, end: float
        ) -> Tuple[str, str, str, float, str]:
            """
            Format timing for table

            Args:
                title (str): Chapter title
                start (float): Chapter start time
                end (float): Chapter end time

            Returns:
                Tuple[str, str, str, float, str]: Formatted timing
            """
            dur = end - start
            return (
                title,
                format_human_time(start),
                format_human_time(end),
                round(dur, 2),
                format_human_time(dur),
            )

        # 3. Write the modified metadata file
        prn_info(f"Chapters to write: {len(formatted_chapters)}")
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

            Console().print(table)
        except Exception as _:
            for title, start, end, _, hdur in fdform:
                prn_info(f"  - {title}: {start} -[{hdur}]-> {end}")
        metadata_path.write_text("\n".join(self._to_mkvmerge_chapter(deform)))

        # 4. Merge changes to the video
        # fmt: off
        sp.run([
            mkvpropedit, str(video_path),
            "--chapters", str(metadata_path),
            "--quiet",
        ], check=True)
        # fmt: on
        prn_done("Chapters have been added to the video file")

        prn_info(f"Removing {metadata_path.name}")
        metadata_path.unlink(True)

        return Path(video_path)

    def _add_audio_language(
        self,
        video_path: Path,
        language: Optional[Literal["ind", "jpn", "chi", "tha", "und"]],
    ) -> List[str]:
        """
        Adds an audio language to the video file.

        Args:
            video_path (Path): The path to the video file.
            language (str): The language to add to the video file.

        Returns:
            List[str]: mkvpropedit args
        """
        prn_info(
            f"Adding audio language '{language}' to {video_path.name} using mkvpropedit"
        )
        code = {
            "chi": "Chinese (中文)",
            "jpn": "Japanese (日本語)",
            "ind": "Indonesian (bahasa Indonesia)",
            "tha": "Thai (ไทย)",
            None: "Undetermined",
        }
        lang_title = code[language]
        language = language or "und"
        # fmt: off
        return [
            "--edit", "track:a1",
            "--set", f"language={language}",
            "--set", f"name={lang_title}",
        ]

    def _set_default_subtitle(
        self,
        raw_data: Dict[str, Any],
        video_path: Path,
        language: Literal["en", "id", "ms", "th", "vi", "zh-Hans", "zh-Hant"] = "en",
    ) -> List[str]:
        """
        Sets the default subtitle for the video file.

        Args:
            video_path (Path): The path to the video file.
            language (str): The language to set as the default subtitle.

        Returns:
            List[str]: mkvpropedit args
        """

        lcodex = {
            "en": "eng",
            "id": "ind",
            "ms": "may",
            "th": "tha",
            "vi": "vie",
            "zh-Hans": "chi",
            "zh-Hant": "chi",
        }
        flang = lcodex.get(language, "eng")

        def fail(msg: str) -> List[str]:
            prn_error(msg)
            return []

        # get all name of keys in raw_data["subtitles"]
        try:
            keys = raw_data.get("subtitles", {}).keys()
            # covert dict_keys to list
            keys = list(keys)
        except Exception as _:
            keys = []
        if not keys:
            return fail(
                "Failed to get subtitle index from yt-dlp. Does the video have subtitles?"
            )

        prn_info(f"Setting default subtitle to '{flang}' for {video_path.name}")
        # get the subtitle track number from the video file using mkvmerge as json
        mkvmerge = self.mkvmerge_path or find_command("mkvmerge")
        if not mkvmerge:
            return fail(
                "mkvmerge is not found in the system, try to install it first or check the path"
            )

        # fmt: off
        result = sp.run([
            mkvmerge, "-J", str(video_path)
        ], capture_output=True, text=True)
        # fmt: on

        if result.returncode != 0:
            return fail("Failed to get subtitle track number")

        set_track: Optional[Tuple[str, str]] = None
        unset_track: List[Tuple[str, str]] = []

        try:
            data = jloads(result.stdout)
            for track in data["tracks"]:
                if track["type"] == "subtitles":
                    track_lang = track["properties"]["language"]
                    if track_lang == "zh" or track_lang == "chi":
                        track_lang = keys[track["id"] - 2]
                    if track_lang == flang:
                        set_track = (str(track["id"] + 1), track_lang)
                    else:
                        unset_track.append((str(track["id"] + 1), track_lang))
        except Exception as _:
            return fail("Failed to get subtitle track number")

        if not set_track and len(unset_track) > 0:
            prn_error(
                f"Subtitle track for '{flang}' not found, using the first subtitle track as default"
            )
            set_track = unset_track.pop(0)

        # set the subtitle track as default
        if set_track:
            unset_: List[str] = []
            # fmt: off
            for track in unset_track:
                unset_ += [
                    "--edit", f"track:{track[0]}",
                    "--set", "flag-default=0",
                    "--set", f"language={track[1]}",
                    "--set", f"name={langcode_to_str(track[1])}",
                ]
            return [
                "--edit", f"track:{set_track[0]}",
                "--set", "flag-default=1",
                "--set", f"language={set_track[1]}",
                "--set", f"name={langcode_to_str(set_track[1])}",
                *unset_,
            ]
            # fmt: on
        else:
            return fail("Failed to set subtitle track as default")

    @staticmethod
    def _resize_thumbnail_for_mkv(image_data: bytes) -> bytes:
        """
        Resize thumbnail to MKV maximum cover specifications (600x600).

        According to Matroska specifications, cover art should be resized to
        a maximum of 600x600 pixels for optimal compatibility and file size.

        Args:
            image_data (bytes): Original image data

        Returns:
            bytes: Resized image data as PNG
        """
        try:
            # Open image from bytes
            image = Image.open(BytesIO(image_data))

            # Convert to RGB if necessary (handles RGBA, P mode, etc.)
            if image.mode not in ("RGB", "RGBA"):
                if image.mode == "P":
                    # Convert palette mode to RGBA first to preserve transparency
                    image = image.convert("RGBA")
                else:
                    image = image.convert("RGB")

            # Calculate new size maintaining aspect ratio
            original_width, original_height = image.size
            max_size = 600

            # Only resize if image is larger than max_size
            if original_height > max_size:
                new_height = max_size
                new_width = int((max_size * original_width) / original_height)

                # Use LANCZOS for high-quality downsampling
                image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Save to bytes as PNG (lossless and widely supported)
            output = BytesIO()

            # If image has transparency (RGBA), keep it; otherwise convert to RGB
            if image.mode == "RGBA":
                image.save(output, format="PNG", optimize=True)
            else:
                # Convert RGBA to RGB if no transparency is actually used
                if image.mode == "RGBA":
                    # Check if alpha channel has any transparency
                    alpha = image.split()[3]
                    if alpha.getextrema()[0] == 255:  # No transparency
                        image = image.convert("RGB")

                image.save(output, format="PNG", optimize=True)

            return output.getvalue()

        except Exception as e:
            prn_error(f"Failed to resize thumbnail: {e}")
            # Return original data if resizing fails
            return image_data

    def _insert_thumbnail(self, raw_info: Dict[str, Any]) -> List[str]:
        """
        Inserts a thumbnail into the video file.

        Args:
            raw_info (Dict[str, Any]): Video metadata.

        Returns:
            List[str]: mkvpropedit args
        """
        thumbnail = raw_info.get("thumbnail")
        if not thumbnail:
            return []

        prn_info("Downloading thumbnail and adding it to the video file")
        thumbnail_path = Path("thumbnail.png")

        with reqs.get(thumbnail) as resp:
            # Resize thumbnail to MKV specifications before saving
            resized_thumbnail_data = self._resize_thumbnail_for_mkv(resp.content)
            thumbnail_path.write_bytes(resized_thumbnail_data)

        # fmt: off
        return [
            "--attachment-name", "cover_land.png",
            "--attachment-mime-type", "image/png",
            "--add-attachment", str(thumbnail_path),
        ]
        # fmt: on

    def _execute_mkvpropedit(
        self,
        video_path: Path,
        audio_args: List[str],
        sub_args: List[str],
        font_args: List[str],
        attachment_args: List[str],
    ) -> Path:
        """
        Executes mkvpropedit on the video file.

        Args:
            video_path (Path): The path to the video file.
            audio_args (List[str]): mkvpropedit args for audio.
            sub_args (List[str]): mkvpropedit args for subtitle.
            font_args (List[str]): mkvpropedit args for fonts to import

        Returns:
            Path: The path to the video file with added metadata.
        """

        mkvpropedit = (
            str(self.mkvpropedit_path) if self.mkvpropedit_path else "mkvpropedit"
        )
        if not audio_args and not sub_args:
            return video_path

        prn_info(f"Executing mkvpropedit on {video_path.name}")
        # fmt: off
        sp.run([
            mkvpropedit, str(video_path),
            *audio_args,
            *sub_args,
            *font_args,
            *attachment_args,
            "--quiet", "--add-track-statistics-tags",
        ], check=True)
        # fmt: on
        prn_done(f"Metadata has been added to {video_path.name}")

        return video_path

    def download_episode(
        self,
        episode_url: str,
    ) -> Tuple[Path, Any, Optional[Literal["ind", "jpn", "chi", "tha"]]]:
        """Download episode from Bilibili with yt-dlp

        Args:
            episode_url (str): URL to the episode

        Returns:
            Path: Path to downloaded episode
            Any: Data output from yt-dlp
        """
        prn_info("Resolving some metadata information of the link, may take a while")
        html = BiliHtml(cookie_path=self.cookie, user_agent=uagent)
        resp = html.get(episode_url)

        ep_url = rsearch(r"play/(\d+)/(\d+)", episode_url)
        series_id = ep_url.group(1) if ep_url else None
        ftitle = rsearch(
            r"<title>(.*)</title>", resp.content.decode("utf-8"), IGNORECASE
        )
        if ftitle:
            title = rsub(
                r"\s+(?:E\d+|PV\d*|SP\d*|OVA\d*).*$",
                "",
                ftitle.group(1),
            )
            title = sanitize_filename(unescape(title))
        else:
            title = ftitle

        if series_id and series_id in SERIES_ALIASES:
            title = sanitize_filename(SERIES_ALIASES[series_id])

        # look for .bstar-meta__area class to get country of origin
        language: Optional[Literal["ind", "jpn", "chi", "tha"]] = None
        language = "chi" if "Chinese Mainland" in resp.text else language
        if language is None:
            language = "jpn" if "Japan" in resp.text else language
        jp_dub = ["JP Ver", "JPN Dub"]
        ch_dub = ["Dub CN", "พากย์จีน"]
        id_dub = ["Dub Indo", "ID dub"]
        th_dub = ["Thai Dub", "TH dub"]
        if any(x.lower() in str(title).lower() for x in jp_dub):
            language = "jpn"
        elif any(x.lower() in str(title).lower() for x in ch_dub):
            language = "chi"
        elif any(x.lower() in str(title).lower() for x in id_dub):
            language = "ind"
        elif any(x.lower() in str(title).lower() for x in th_dub):
            language = "tha"

        codec = "avc1" if self.is_avc else "hev1"

        ydl_opts = {
            "cookiefile": str(self.cookie),
            "extract_flat": "discard_in_playlist",
            "force_print": {"after_move": ["filepath"]},
            "format": f"bv*[vcodec^={codec}][height={self.resolution}]+ba",
            "fragment_retries": 10,
            "ignoreerrors": "only_download",
            "merge_output_format": "mkv",
            "final_ext": "mkv",
            "outtmpl": {
                "default": "[%(extractor)s] {inp} - E%(episode_number)s [%(resolution)s, %(vcodec)s].%(ext)s".format(
                    inp=title
                )
            },
            "postprocessors": [],
            "retries": 10,
            "subtitlesformat": "srt" if self.srt else "ass/srt",
            "subtitleslangs": ["all"],
            "updatetime": False,
            "writesubtitles": True,
            "referer": "https://www.bilibili.tv/",
        }

        # Build postprocessors list in the correct order
        postprocessors = []

        # Add subtitle embedding
        postprocessors.append(
            {"already_have_subtitle": False, "key": "FFmpegEmbedSubtitle"}
        )

        # Add metadata processor
        postprocessors.append(
            {
                "add_chapters": False,
                "add_infojson": None,
                "add_metadata": False,
                "key": "FFmpegMetadata",
            }
        )

        # Add concat processor
        postprocessors.append(
            {"key": "FFmpegConcat", "only_multi_video": True, "when": "playlist"}
        )

        ep_num = "0"

        ydl_opts["postprocessors"] = postprocessors
        if self.only_audio:
            ydl_opts["format"] = "ba"
            del ydl_opts["subtitlesformat"]
            del ydl_opts["subtitleslangs"]
            del ydl_opts["writesubtitles"]
        if self.ffmpeg_path:
            ydl_opts["ffmpeg_location"] = str(self.ffmpeg_path)
        if self.mkvmerge_path:
            ydl_opts["mkvmerge_path"] = str(self.mkvmerge_path)
        with YDL(ydl_opts) as ydl:  # type: ignore
            ydl.params["quiet"] = True
            ydl.params["verbose"] = False
            metadata = ydl.extract_info(episode_url, download=False)
            try:
                if metadata is None:
                    raise NameError()
                is_pv = metadata["title"].startswith("PV")  # type: ignore
                if is_pv and not self.download_pv:
                    raise NameError()
            except AttributeError:
                raise ReferenceError(
                    f"{episode_url} does not have preferred resolution of {self.resolution}"
                )
            except (TypeError, NameError):
                raise NameError(
                    f"{episode_url} is a PV. Explicitly enable the switch if you want to download it."
                )
            if "entries" in metadata:
                raise ReferenceError(
                    f"{episode_url} is a Playlist URL, not episode. To avoid unwanted err, please use other command"
                )
            ep_num = f"E{metadata.get('episode_number', 0):02d}" if metadata else ""
            if not metadata["title"].startswith("E"):  # type: ignore
                ep_num = metadata["title"].split(" - ")[0] if metadata else ep_num  # type: ignore
            if self.notification:
                push_notification(
                    title=str(title),
                    index=ep_num,
                )
            prn_info(
                f'Downloading "{title}" {ep_num} at {self.resolution}P using codec {codec.upper()}'
            )
            # replace output format
            ydl.params["outtmpl"]["default"] = (
                "[%(extractor)s] {inp} - {ep} [%(resolution)s, %(vcodec)s].%(ext)s".format(  # type: ignore
                    inp=title,
                    ep=ep_num,
                )
            )
            final_path = ydl.prepare_filename(metadata)
            ydl.params["quiet"] = False
            ydl.params["verbose"] = True

            # Add ASS rescaler if conditions are met
            if not self.srt and not self.only_audio and not self.dont_rescale:
                if check_package("ass"):
                    try:
                        from assresample import SSARescaler
                    except ImportError:
                        from bilidownloader.assresample import SSARescaler
                    ydl.add_post_processor(SSARescaler(), when="before_dl")

            # Add SRT to ASS converter if needed (must run before FFmpegEmbedSubtitle)
            if not self.srt and not self.only_audio and not self.dont_convert:
                if check_package("ass"):
                    try:
                        from srttoass import SRTToASSConverter
                    except ImportError:
                        from bilidownloader.srttoass import SRTToASSConverter
                    ydl.add_post_processor(SRTToASSConverter(), when="before_dl")
                else:
                    # fmt: off
                    prn_error((
                        "`ass` package is not found inside the environment, "
                        "please reinstall `bilidownloader` by executing this "
                        "command to install the required package:"
                    ))
                    prn_error(REINSTALL_ARGS)
                    # fmt: on
                    prn_info("Reverting to use SRT")
                    self.srt = True
                    self.dont_rescale = False

            # Add SRT gap filler for direct SRT subtitles
            if self.srt and not self.only_audio:
                try:
                    from srtgapfill import SRTGapFiller
                except ImportError:
                    from bilidownloader.srtgapfill import SRTGapFiller
                ydl.add_post_processor(SRTGapFiller(), when="before_dl")

            ydl.download([episode_url])

        metadata["btitle"] = title  # type: ignore

        return (Path(".") / final_path, metadata, language)

    def process_episode(self, episode_url: str, forced: bool = False) -> Optional[Path]:
        """
        Process episode from Bilibili

        Args:
            episode_url (str): URL to the episode
            forced (bool, optional): Force download. Defaults to False.

        Returns:
            Optional[Path]: Path to downloaded episode
        """
        clock = BenchClock()
        tries = 0
        history = History(self.history)
        # use English episode url from other kind of URL using regex from play/{season_id}/{episode_id}
        # example: https://www.bilibili.tv/play/2114220/1337943578 -> https://www.bilibili.tv/en/play/2114220/13379435
        # convert using self.ep_url(season_id, episode_id)
        ep_url = rsearch(r"play/(\d+)/(\d+)", episode_url)
        if ep_url:
            episode_url = self.ep_url(ep_url.group(1), ep_url.group(2))
        else:
            raise ValueError("Invalid episode URL")
        while True:
            if tries > 2:
                prn_error(
                    "Application have tried to retry for 3 times already, terminating"
                )
                break
            try:
                if not forced:
                    history.check_history(episode_url)
                loc, data, language = self.download_episode(episode_url)
                chapters = self._get_episode_chapters(data)
                final = self._embed_chapters(chapters, loc)
                aud_args = self._add_audio_language(final, language)
                font_args: List[str] = []
                # Handle fonts for ASS files (either original ASS or converted from SRT)
                if not self.srt or not self.dont_convert:
                    font_json = Path("fonts.json")
                    if font_json.exists():
                        font_json, font_args = loop_font_lookup(font_json, font_args)
                        font_json.unlink(True)
                sub_args = self._set_default_subtitle(data, final, self.subtitle_lang)  # type: ignore
                if not self.dont_thumbnail and not self.only_audio:
                    attachment_args = self._insert_thumbnail(data)
                else:
                    attachment_args = []
                final = self._execute_mkvpropedit(
                    final, aud_args, sub_args, font_args, attachment_args
                )
                Path("thumbnail.png").unlink(True)
                if not forced:
                    # Extract metadata for history
                    series_id = ep_url.group(1) if ep_url else None
                    episode_id = ep_url.group(2) if ep_url else None
                    series_title = data.get(
                        "btitle", data.get("series", f"Series {series_id}")
                    )

                    # Use alias if available
                    if series_id and series_id in SERIES_ALIASES:
                        series_title = SERIES_ALIASES[series_id]

                    episode_idx = (
                        str(data.get("episode_number", ""))
                        if data.get("episode_number")
                        else ""
                    )

                    history.write_history(
                        episode_url,
                        series_id=series_id,
                        series_title=series_title,
                        episode_idx=episode_idx,
                        episode_id=episode_id,
                    )
                else:
                    prn_info("Forced download, skipping adding to history")
                clock.echo_format(f"Downloaded {final.name}")
                if self.notification:
                    push_notification(
                        data["btitle"], data.get("episode_number", ""), final
                    )
                return final
            except (ReferenceError, NameError) as err:
                prn_error(str(err))
                break
            except DataExistError:
                prn_error(
                    f"Episode ({episode_url}) was ripped previously. "
                    f'Modify "{str(self.history)}" to proceed.'
                )
                break
            except (KeyboardInterrupt, SystemExit):
                print()
                prn_error("Interrupt signal received, stopping process")
                exit(1)
            except Exception as _:
                prn_error("An exception has been thrown:")
                prn_error(traceback.format_exc())
                prn_info("Retrying...")
                tries += 1

    def process_playlist(self, playlist_url: str, forced: bool = False) -> List[Path]:
        """
        Process playlist from Bilibili

        Args:
            playlist_url (str): URL to the playlist
            forced (bool, optional): Force download. Defaults to False.

        Returns:
            List[Path]: List of downloaded episodes
        """
        clock = BenchClock()
        try:
            data = self._get_video_info(playlist_url)
        except Exception as _:
            data = None
        if data is None:
            raise ValueError(f"We cannot process {playlist_url} at the moment!")
        final: List[Optional[Path]] = []
        total = len(data["entries"])
        for entry in data["entries"]:
            prn_info(f"Processing {len(final) + 1}/{total}")
            final.append(
                self.process_episode(
                    self.ep_url(data["id"], entry["id"]),
                    forced=forced,
                )
            )
            print()
        nnfinal = [f for f in final if f is not None]
        flen = len(nnfinal)
        clock.echo_format(f"Downloaded {pluralize(flen, 'episode')} from playlist")
        return nnfinal

    def process_watchlist(self, forced: bool = False) -> List[Path]:
        """
        Process watchlist from Bilibili

        Args:
            forced (bool, optional): Force download. Defaults to False.

        Returns:
            List[Path]: List of downloaded episodes
        """
        final: List[Path] = []
        wl = Watchlist(self.watchlist)
        api = BiliApi()
        clock = BenchClock()

        if forced:
            prn_info("Forced switch is enabled, ignoring history")
        else:
            prn_info("Downloading watchlist")

        for card in api.get_all_available_shows():
            for sid, title in wl.list:
                if sid != card.season_id:
                    continue
                print()
                # Use alias if available
                display_title = SERIES_ALIASES.get(sid, title)
                if "-" in card.index_show:
                    prn_info(f"Downloading {display_title} as a playlist")
                    final.extend(
                        self.process_playlist(
                            f"https://www.bilibili.tv/en/play/{card.season_id}",
                            forced=forced,
                        )
                    )
                else:
                    prn_info(f"Downloading {display_title}, {card.index_show}")
                    ep = self.process_episode(
                        self.ep_url(card.season_id, card.episode_id),
                        forced=forced,
                    )
                    if ep is not None:
                        final.append(ep)

        nnfinal = [f for f in final if f is not None]
        flen = len(nnfinal)
        clock.echo_format(
            f"Downloaded {pluralize(flen, 'episode')} from watchlist queue"
        )
        return nnfinal
