import subprocess as sp
from html import unescape
from json import loads as jloads
from os import remove, rename
from pathlib import Path
from re import IGNORECASE
from re import search as rsearch
from re import sub as rsub
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from fake_useragent import UserAgent
from matplotlib import font_manager as font
from rich.console import Console
from rich.table import Column, Table, box
from yt_dlp import YoutubeDL as YDL

try:
    from api import BiliApi, BiliHtml
    from assresample import SSARescaler
    from common import (
        DEFAULT_HISTORY,
        DEFAULT_WATCHLIST,
        Chapter,
        DataExistError,
        available_res,
        find_command,
        format_human_time,
        prn_done,
        prn_error,
        prn_info,
        push_notification,
        sanitize_filename,
    )
    from history import History
    from watchlist import Watchlist
except ImportError:
    from bilidownloader.api import BiliApi, BiliHtml
    from bilidownloader.assresample import SSARescaler
    from bilidownloader.common import (
        DEFAULT_HISTORY,
        DEFAULT_WATCHLIST,
        Chapter,
        DataExistError,
        available_res,
        find_command,
        format_human_time,
        prn_done,
        prn_error,
        prn_info,
        push_notification,
        sanitize_filename,
    )
    from bilidownloader.history import History
    from bilidownloader.watchlist import Watchlist


ua = UserAgent()
uagent = ua.chrome


def find_font_by_query(font_name: str) -> Path | None:
    """
    Find font file from font name

    Args:
        font_name (str): Font name

    Returns:
        Path: Path to the font file
    """
    try:
        fc_ = font.findfont(
            font.FontProperties(family=font_name),
            fallback_to_default=False,
            rebuild_if_missing=False,
        )
    except Exception as _:
        return None

    # if font is not found, return None
    if not fc_:
        return None

    # return absolute path
    return Path(fc_).absolute()


def int_to_abc(number: int) -> str:
    """
    Convert integer to capital alphabet

    Args:
        number (int): Number to convert

    Returns:
        str: Alphabet
    """
    # if over 26, use base26 in A-Z:
    if number > 26:
        return int_to_abc((number - 1) // 26) + chr((number - 1) % 26 + ord("A"))
    return chr(number + ord("A") - 1)

class BiliProcess:
    def __init__(
        self,
        cookie: Path,
        history: Path = DEFAULT_HISTORY,
        watchlist: Path = DEFAULT_WATCHLIST,
        resolution: available_res = 1080,  # type: ignore
        is_avc: bool = False,
        download_pv: bool = False,
        ffmpeg_path: Optional[Path] = None,
        mkvpropedit_path: Optional[Path] = None,
        notification: bool = False,
        srt: bool = False,
        dont_rescale: bool = False,
        subtitle_lang: Optional[
            Literal["eng", "ind", "may", "tha", "vie", "zht", "zhs"]
        ] = None,
    ):
        self.watchlist = watchlist
        self.history = history
        self.cookie = cookie
        self.resolution = resolution
        self.is_avc = is_avc
        self.download_pv = download_pv
        self.ffmpeg_path = ffmpeg_path
        self.mkvpropedit_path = mkvpropedit_path
        self.notification = notification
        self.srt = srt
        self.dont_rescale = dont_rescale
        self.subtitle_lang = subtitle_lang

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
        with YDL(ydl_opts) as ydl:
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

    def _create_ffmpeg_chapters(
        self, chapters: List[Chapter], video_path: Path
    ) -> Path:
        """
        Creates chapter metadata and merges it into the video file.

        Args:
            chapters (List[Chapter]): The list of chapters to process.
            video_path (Path): The path to the video file.

        Returns:
            Path: The path to the video file with added chapters.
        """
        prn_info(f"Creating chapters for {str(video_path.absolute())}")
        # 1. Extract metadata and calculate the total duration
        metadata_path = video_path.with_suffix(".meta")
        ffmpeg = str(self.ffmpeg_path) if self.ffmpeg_path else "ffmpeg"
        mkvpropedit = (
            str(self.mkvpropedit_path) if self.mkvpropedit_path else "mkvpropedit"
        )
        with open(metadata_path, "w", encoding="utf-8") as file:
            file.write(";FFMETADATA1\n")

        # Get video duration using ffprobe
        # fmt: off
        ffprobe = find_command("ffprobe")
        if not ffprobe:
            prn_error("ffprobe is not found in the system, try to install it first or check the path")
            return video_path
        result = sp.run([
            str(ffprobe), "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ], capture_output=True, text=True)
        # fmt: on
        total_duration = float(result.stdout.strip())

        # 1B. Remove existing chapters from the video
        prn_info(f"Removing existing chapters from {str(video_path.absolute())}, if any")
        # fmt: off
        sp.run([
            mkvpropedit, str(video_path),
            "--chapter", "",
            "--quiet",
        ], check=True)

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
        with open(metadata_path, "a") as meta_file:
            # Reformatted chapters from deformatted chapters
            formatted_chapters = [self._format_chapter(ch, ch.title) for ch in deform]
            meta_file.write("\n".join(formatted_chapters))

        # 4. Merge changes to the video
        output_path = video_path.with_stem(video_path.stem + "_temp")
        # fmt: off
        sp.run([
            ffmpeg, "-v", "error",
            "-i", str(video_path),
            "-i", str(metadata_path),
            "-map", "0",
            "-map_metadata", "1",
            "-codec", "copy",
            str(output_path),
        ], check=True)
        # fmt: on
        prn_done("Chapters have been added to the video file")

        prn_info(f"Removing {str(metadata_path.absolute())}")
        remove(metadata_path)
        remove(video_path)
        prn_info(f"Renaming {output_path} to {video_path}")
        rename(output_path, video_path)

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
            f"Adding audio language '{language}' to {str(video_path.absolute())} using mkvpropedit"
        )
        code = {
            "chi": "Chinese",
            "jpn": "Japanese",
            "ind": "Indonesian",
            "tha": "Thai",
            None: "Undetermined",
        }
        lang_title = code[language]
        language = language or "und"
        # fmt: off
        return [
            "--edit", "track:a1",
            "--set", f"language={language}",
            "--set", f"name={lang_title}",
            "--quiet",
        ]

    def _set_default_subtitle(
        self,
        video_path: Path,
        language: Optional[
            Literal["eng", "ind", "may", "tha", "vie", "zht", "zhs"]
        ] = None,
    ) -> List[str]:
        """
        Sets the default subtitle for the video file.

        Args:
            video_path (Path): The path to the video file.
            language (str): The language to set as the default subtitle.

        Returns:
            List[str]: mkvpropedit args
        """

        def fail(msg: str) -> List[str]:
            prn_error(msg)
            return []

        if not language:
            return fail(
                f"Skipping setting default subtitle for {str(video_path.absolute())}"
            )
        prn_info(
            f"Setting default subtitle to '{language}' for {str(video_path.absolute())}"
        )
        # get the subtitle track number from the video file using mkvmerge as json
        mkvmerge = find_command("mkvmerge")
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

        set_track: Optional[str] = None
        unset_track: List[str] = []

        try:
            data = jloads(result.stdout)
            for track in data["tracks"]:
                if track["type"] == "subtitles":
                    if track["properties"]["language"] == language:
                        set_track = str(track["id"] + 1)
                    else:
                        unset_track.append(str(track["id"] + 1))
        except Exception as _:
            return fail("Failed to get subtitle track number")

        # set the subtitle track as default
        if set_track:
            prn_info(f"Setting track {set_track} as default subtitle")
            unset_: List[str] = []
            for track in unset_track:
                unset_ += ["--edit", f"track:{track}", "--set", "flag-default=0"]
            # fmt: off
            return [
                "--edit", f"track:{set_track}",
                "--set", "flag-default=1",
                *unset_,
                "--quiet",
            ]
            # fmt: on
        else:
            return fail("Specified subtitle track is not found in the video file")

    def _execute_mkvpropedit(
        self,
        video_path: Path,
        audio_args: List[str],
        sub_args: List[str],
        font_args: List[str],
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

        prn_info(f"Executing mkvpropedit on {str(video_path.absolute())}")
        # fmt: off
        sp.run([
            mkvpropedit, str(video_path),
            *audio_args,
            *sub_args,
            *font_args,
            "--quiet",
            "--add-track-statistics-tags",
        ], check=True)
        # fmt: on
        prn_done(f"Metadata has been added to {str(video_path.absolute())}")

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
        prn_info("Fetching metadata from episode's page")
        html = BiliHtml(cookie_path=self.cookie, user_agent=uagent)
        resp = html.get(episode_url)

        ftitle = rsearch(
            r"<title>(.*)</title>", resp.content.decode("utf-8"), IGNORECASE
        )
        if ftitle:
            title = rsub(
                r"\s*E(?:\d+)(?:\s*\-\s*.*)?\s*\-\s*Bstation$", "", ftitle.group(1)
            )
            title = sanitize_filename(unescape(title))
        else:
            title = ftitle

        # look for .bstar-meta__area class to get country of origin
        language: Optional[Literal["ind", "jpn", "chi", "tha"]] = None
        language = "chi" if "Chinese Mainland" in resp.text else language
        if language is None:
            language = "jpn" if "Japan" in resp.text else language
        jp_dub = ["JP Ver", "JPN Dub"]
        id_dub = ["Dub Indo", "ID dub"]
        th_dub = ["Thai Dub", "TH dub"]
        if any(x.lower() in str(title).lower() for x in jp_dub):
            language = "jpn"
        elif any(x.lower() in str(title).lower() for x in id_dub):
            language = "ind"
        elif any(x.lower() in str(title).lower() for x in th_dub):
            language = "tha"

        codec = "avc1" if self.is_avc else "hev1"

        prn_info(f"Start downloading {title}")
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
            "postprocessors": [
                {"already_have_subtitle": False, "key": "FFmpegEmbedSubtitle"},
                {
                    "add_chapters": False,
                    "add_infojson": None,
                    "add_metadata": False,
                    "key": "FFmpegMetadata",
                },
                {"key": "FFmpegConcat", "only_multi_video": True, "when": "playlist"},
            ],
            "retries": 10,
            "subtitlesformat": "srt" if self.srt else "ass/srt",
            "subtitleslangs": ["all"],
            "updatetime": False,
            "writesubtitles": True,
            "referer": "https://www.bilibili.tv/",
        }
        if self.ffmpeg_path:
            ydl_opts["ffmpeg_location"] = str(self.ffmpeg_path)
        with YDL(ydl_opts) as ydl:
            ydl.params["quiet"] = True
            ydl.params["verbose"] = False
            prn_info("Fetching required metadata")
            metadata = ydl.extract_info(episode_url, download=False)
            if metadata is None:
                raise Exception()
            if "entries" in metadata:
                raise ReferenceError(
                    f"{episode_url} is a Playlist URL, not episode. To avoid unwanted err, please use other command"
                )
            if metadata["title"].startswith("PV") and not self.download_pv:
                raise NameError(
                    f"{episode_url} is a PV. Explicitly enable the switch if you want to download it."
                )
            if self.notification:
                push_notification(
                    title=str(title),
                    index=metadata.get("episode_number", "") if metadata else "",
                )
            prn_info("Downloading episode now")
            ydl.params["quiet"] = False
            ydl.params["verbose"] = True
            if not (self.dont_rescale or self.srt):
                ydl.add_post_processor(SSARescaler(), when="before_dl")
            ydl.download([episode_url])

        metadata["btitle"] = title

        return (
            Path(
                f"./[{metadata['extractor']}] {title} - E{metadata['episode_number']} [{metadata['resolution']}, {metadata['vcodec']}].mkv"
            ),
            metadata,
            language,
        )

    def process_episode(self, episode_url: str, forced: bool = False) -> Optional[Path]:
        """
        Process episode from Bilibili

        Args:
            episode_url (str): URL to the episode
            forced (bool, optional): Force download. Defaults to False.

        Returns:
            Optional[Path]: Path to downloaded episode
        """
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
                final = self._create_ffmpeg_chapters(chapters, loc)
                aud_args = self._add_audio_language(final, language)
                font_args: List[str] = []
                font_json = Path("fonts.json")
                try:
                    with open(font_json, "r", encoding="utf-8") as file:
                        fonts: List[str] = jloads(file.read())
                except Exception as _:
                    fonts: List[str] = []
                for font in fonts:
                    fpath = find_font_by_query(font)
                    if fpath:
                        # fmt: off
                        font_args += [
                            "--attachment-name", font,
                            "--add-attachment", str(fpath),
                        ]
                        # fmt: on
                font_json.unlink(True)
                sub_args = self._set_default_subtitle(final, self.subtitle_lang)  # type: ignore
                final = self._execute_mkvpropedit(final, aud_args, sub_args, font_args)
                if not forced:
                    history.write_history(episode_url)
                else:
                    prn_info("Forced download, skipping adding to history")
                prn_done(f"Downloaded {str(final.absolute())}")
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
            except Exception as err:
                prn_error("An exception has been thrown:")
                prn_error(str(err))
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
        try:
            data = self._get_video_info(playlist_url)
        except Exception as _:
            data = None
        if data is None:
            raise ValueError(f"We cannot process {playlist_url} at the moment!")
        final = []
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
        return final

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

        if forced:
            prn_info("Forced switch is enabled, ignoring history")
        else:
            prn_info("Downloading watchlist")

        for card in api.get_all_available_shows():
            for sid, title in wl.list:
                if sid != card.season_id:
                    continue
                print()
                if "-" in card.index_show:
                    prn_info(f"Downloading {title} as a playlist")
                    final.extend(
                        self.process_playlist(
                            f"https://www.bilibili.tv/en/play/{card.season_id}",
                            forced=forced,
                        )
                    )
                else:
                    prn_info(f"Downloading {title}, {card.index_show}")
                    ep = self.process_episode(
                        self.ep_url(card.season_id, card.episode_id),
                        forced=forced,
                    )
                    if ep is not None:
                        prn_done(
                            f"Downloaded {title}, {card.index_show} to ({str(ep.absolute())})"
                        )
                        final.append(ep)

        return final
