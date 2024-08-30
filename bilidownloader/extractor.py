import subprocess as sp
from html import unescape
from os import remove, rename
from pathlib import Path
from re import IGNORECASE
from re import search as rsearch
from re import sub as rsub
from time import sleep
from typing import Any, Dict, List, Tuple, Union
from traceback import format_exception

from api import BiliApi, BiliHtml
from common import (
    DEFAULT_HISTORY,
    DEFAULT_WATCHLIST,
    Chapter,
    DataExistError,
    available_res,
    sanitize_filename
)
from history import History
from watchlist import Watchlist
from yt_dlp import YoutubeDL as YDL
from survey import printers


class BiliProcess:
    def __init__(
        self,
        cookie: Path,
        history: Path = DEFAULT_HISTORY,
        watchlist: Path = DEFAULT_WATCHLIST,
        resolution: available_res = 1080,
        is_avc: bool = False,
        download_pv: bool = False,
    ):
        self.watchlist = watchlist
        self.history = history
        self.cookie = cookie
        self.resolution = resolution
        self.is_avc = is_avc
        self.download_pv = download_pv

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
            "quiet": True,
            "retries": 10,
            "simulate": True,
        }
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
        printers.info(f"Creating chapters for {str(video_path.absolute())}")
        # 1. Extract metadata and calculate the total duration
        metadata_path = video_path.with_suffix(".meta")
        sp.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(video_path),
                "-f",
                "ffmetadata",
                str(metadata_path),
            ],
            check=True,
        )

        # Get video duration using ffprobe
        result = sp.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
        )
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
                final_chapter = Chapter(
                    start_time=chapters[-1].end_time,
                    end_time=total_duration,
                    title=f"Part {part_index}",
                )
                formatted_chapters.append(
                    self._format_chapter(final_chapter, final_chapter.title)
                )
        except IndexError as _:
            printers.fail("This video does not have any chapters")

        # 3. Write the modified metadata file
        with open(metadata_path, "a") as meta_file:
            meta_file.write("\n".join(formatted_chapters))

        # 4. Merge changes to the video
        output_path = video_path.with_stem(video_path.stem + "_temp")
        sp.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(video_path),
                "-i",
                str(metadata_path),
                "-map",
                "0",
                "-map_metadata",
                "1",
                "-codec",
                "copy",
                str(output_path),
            ],
            check=True,
        )

        printers.info(f"Removing {str(metadata_path.absolute())}")
        remove(metadata_path)
        remove(video_path)
        printers.info(f"Renaming {output_path} to {video_path}")
        rename(output_path, video_path)

        return Path(video_path)

    def download_episode(
        self,
        episode_url: str,
    ) -> Tuple[Path, Any]:
        """Download episode from Bilibili with yt-dlp

        Args:
            episode_url (str): URL to the episode

        Returns:
            Path: Path to downloaded episode
            Any: Data output from yt-dlp
        """

        metadata = self._get_video_info(episode_url)
        if not metadata:
            raise ValueError("Failed to get metadata!")
        if "entries" in metadata:
            raise ReferenceError(
                f"{episode_url} is a Playlist URL, not episode. To avoid unwanted err, please use other command"
            )
        if metadata["title"].startswith("PV") and not self.download_pv:
            raise NameError(
                f"{episode_url} is a PV. Explicitly enable the switch if you want to download it."
            )
        sleep(1)  # To avoid DDoS

        printers.info("Fetching metadata from episode's page")
        html = BiliHtml(self.cookie, metadata["requested_formats"][0]["http_headers"]["User-Agent"])
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
        codec = "avc1" if self.is_avc else "hev1"

        printers.info(f"Start downloading {title}")
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
                "default": "[%(extractor)s] {inp} - %(title)s [%(resolution)s, %(vcodec)s].%(ext)s".format(
                    inp=title
                )
            },
            "postprocessors": [
                {"key": "FFmpegVideoRemuxer", "preferedformat": "mkv"},
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
            "subtitlesformat": "ass/srt",
            "subtitleslangs": ["all"],
            "updatetime": False,
            "verbose": True,
            "writesubtitles": True,
        }
        with YDL(ydl_opts) as ydl:
            ydl.download([episode_url])
            ydl.params["verbose"] = False
            try:
                metadata = ydl.extract_info(episode_url, download=False)
            except Exception:
                metadata = metadata

        return (
            Path(
                f"./[{metadata['extractor']}] {title} - {metadata['title']} [{metadata['resolution']}, {metadata['vcodec']}].mkv"
            ),
            metadata,
        )

    def process_episode(self, episode_url: str) -> Path:
        tries = 0
        history = History(self.history)
        while True:
            if tries > 3:
                break
            try:
                history.check_history(episode_url)
                loc, data = self.download_episode(episode_url)
                chapters = self._get_episode_chapters(data)
                final =  self._create_ffmpeg_chapters(chapters, loc)
                history.write_history(episode_url)
                return final
            except (ReferenceError, NameError) as err:
                print(err)
                break
            except DataExistError as err:
                printers.fail(
                    f"Episode ({episode_url}) was ripped previously. "
                    f'Modify "{str(self.history)}" to proceed.'
                )
                printers.fail(f"Err: {err}")
                break
            except KeyboardInterrupt:
                print("Interrupt signal received, stopping process")
                exit(1)
            except Exception as err:
                print("An exception has been thrown:")
                print(err)
                print("Retrying...")
                tries += 1

    def process_playlist(self, playlist_url: str) -> List[Path]:
        data = self._get_video_info(playlist_url)
        final = []
        for entry in data["entries"]:
            final.append(
                self.process_episode(
                    self.ep_url(data["id"], entry["id"]),
                )
            )
        return final

    def process_watchlist(self) -> List[Path]:
        final: List[Path] = []
        wl = Watchlist(self.watchlist)
        print(wl.list)
        api = BiliApi()

        for sid, title in wl.list:
            for card in api.get_all_shows():
                if sid == card.season_id:
                    if "-" in card.index_show:
                        printers.info(f"Downloading {title} as a playlist")
                        final.extend(self.process_playlist(f"https://www.bilibili.tv/en/play/{card.season_id}"))
                    else:
                        printers.info(f"Downloading {title}, {card.index_show}")
                        final.append(self.process_episode(self.ep_url(card.season_id, card.episode_id)))

        return final
