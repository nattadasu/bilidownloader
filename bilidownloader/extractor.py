import subprocess as sp
from html import unescape
from os import remove, rename
from pathlib import Path
from re import IGNORECASE
from re import search as rsearch
from re import sub as rsub
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from fake_useragent import UserAgent
from yt_dlp import YoutubeDL as YDL
from yt_dlp import postprocessor as postproc

try:
    from api import BiliApi, BiliHtml
    from common import (
        DEFAULT_HISTORY,
        DEFAULT_WATCHLIST,
        Chapter,
        DataExistError,
        available_res,
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
    from bilidownloader.common import (
        DEFAULT_HISTORY,
        DEFAULT_WATCHLIST,
        Chapter,
        DataExistError,
        available_res,
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


class SSARescaler(postproc.PostProcessor):
    def run(self, info) -> tuple[list[Any], Any]:
        # Replace string from "Noto Sans,100" to "Noto Sans,65" on all
        # subtitle files
        def return_dump() -> tuple[list[Any], Any]:
            return [], info

        self.to_screen("Changing subtitle font size")
        fpath: dict[str, str] = info.get("__files_to_move", {})
        if len(fpath) == 0:
            self.report_error("No filepath found in the metadata")
            return return_dump()
        for _, sub_file in fpath.items():
            if not sub_file.endswith("ass"):
                self.report_warning(f"{sub_file} is skipped as it's not SSA file")
                continue
            with open(sub_file, "r", encoding="utf-8") as file:
                content = file.read()
            content = content.replace("Noto Sans,100", "Noto Sans,65")
            with open(sub_file, "w", encoding="utf-8") as file:
                file.write(content)
            self.to_screen(f"{sub_file} has been properly formatted")
        return return_dump()


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

    @staticmethod
    def ep_url(season_id: Union[int, str], episode_id: Union[int, str]) -> str:
        return f"https://www.bilibili.tv/en/play/{season_id}/{episode_id}"

    def _get_video_info(self, episode_url: str) -> Union[Any, Dict[str, Any], None]:
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
        }
        if self.ffmpeg_path:
            ydl_opts["ffmpeg_location"] = str(self.ffmpeg_path)
        with YDL(ydl_opts) as ydl:
            return ydl.extract_info(episode_url, download=False)

    @staticmethod
    def _get_episode_chapters(raw_info: Dict[str, Any]) -> List[Chapter]:
        try:
            return [Chapter(**chs) for chs in raw_info["chapters"]]
        except Exception as _:
            return []

    @staticmethod
    def _format_chapter(chapter: Chapter, title: str) -> str:
        """
        Formats a chapter into FFmpeg metadata format.

        Args:
            chapter (Chapter): The chapter to format.
            title (str): The title of the chapter.

        Returns:
            str: The formatted chapter block.
        """
        start_ms = int(chapter.start_time * 1000)
        end_ms = int(chapter.end_time * 1000) - 1  # Subtract 1 ms for precision

        # Return the formatted chapter string
        return f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={start_ms}\nEND={end_ms}\ntitle={title}\n"

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
        # fmt: off
        sp.run([
            ffmpeg, "-v", "error",
            "-i", str(video_path),
            "-f", "ffmetadata",
            str(metadata_path),
        ], check=True)
        # fmt: on
        with open(metadata_path, "r", encoding="utf-8") as file:
            content = file.read().replace("Packed by Bilibili XCoder v2.0.2", "")
        with open(metadata_path, "w", encoding="utf-8") as file:
            file.write(content)

        # Get video duration using ffprobe
        # fmt: off
        result = sp.run([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ], capture_output=True, text=True)
        # fmt: on
        total_duration = float(result.stdout.strip())

        # 2. Format and modify chapter information
        formatted_chapters = []
        part_index = 1

        for i, chapter in enumerate(chapters):
            if chapter.title not in ["Intro", "Outro"]:
                title = f"Part {part_index}"
                part_index += 1
            else:
                title = chapter.title

            # Format the current chapter
            formatted_chapters.append(self._format_chapter(chapter, title))

            # Add parts between chapters if there's a gap
            if i < len(chapters) - 1:
                next_chapter = chapters[i + 1]
                if chapter.end_time < next_chapter.start_time - 0.001:
                    gap_chapter = Chapter(
                        start_time=chapter.end_time,
                        end_time=next_chapter.start_time,
                        title=f"Part {part_index}",
                    )
                    formatted_chapters.append(
                        self._format_chapter(gap_chapter, gap_chapter.title)
                    )
                    part_index += 1

        # Append final chapter that runs to the end of the video
        try:
            if chapters[-1].end_time < total_duration:
                is_under_minute = total_duration - chapters[-1].end_time <= 60
                final_chapter = Chapter(
                    start_time=chapters[-1].end_time,
                    end_time=total_duration,
                    title="Preview" if is_under_minute else f"Part {part_index}",
                )
                formatted_chapters.append(
                    self._format_chapter(final_chapter, final_chapter.title)
                )
        except IndexError as _:
            prn_error("This video does not have any chapters")

        # 3. Write the modified metadata file
        with open(metadata_path, "a") as meta_file:
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

        prn_info(f"Removing {str(metadata_path.absolute())}")
        remove(metadata_path)
        remove(video_path)
        prn_info(f"Renaming {output_path} to {video_path}")
        rename(output_path, video_path)

        return Path(video_path)

    def _add_audio_language(
        self,
        video_path: Path,
        language: Optional[Literal["ind", "jpn", "chi", "tha", "und"]]
    ) -> Path:
        """
        Adds an audio language to the video file.

        Args:
            video_path (Path): The path to the video file.
            language (str): The language to add to the video file.

        Returns:
            Path: The path to the video file with the added audio language.
        """
        prn_info(
            f"Adding audio language '{language}' to {str(video_path.absolute())} using mkvpropedit"
        )
        mkvpropedit = (
            str(self.mkvpropedit_path) if self.mkvpropedit_path else "mkvpropedit"
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
        sp.run([
            mkvpropedit, str(video_path),
            "--edit", "track:a1",
            "--set", f"language={language}",
            "--set", f"name={lang_title}",
            "--quiet",
        ], check=True)

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
            if tries > 3:
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
                final = self._add_audio_language(final, language)
                if not forced:
                    history.write_history(episode_url)
                else:
                    prn_info("Forced download, skipping adding to history")
                prn_info(f"Downloaded {str(final.absolute())}")
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
            except KeyboardInterrupt:
                prn_error("Interrupt signal received, stopping process")
                exit(1)
            except Exception as err:
                prn_error("An exception has been thrown:")
                prn_error(str(err))
                prn_info("Retrying...")
                tries += 1

    def process_playlist(self, playlist_url: str, forced: bool = False) -> List[Path]:
        data = self._get_video_info(playlist_url)
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
        final: List[Path] = []
        wl = Watchlist(self.watchlist)
        api = BiliApi()

        if forced:
            prn_info("Forced switch is enabled, ignoring history")
        else:
            prn_info("Downloading watchlist")

        for sid, title in wl.list:
            for card in api.get_all_available_shows():
                if sid == card.season_id:
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
