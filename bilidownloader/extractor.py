import traceback
from pathlib import Path
from re import search as rsearch
from typing import List, Optional, Union

from bilidownloader.alias import SERIES_ALIASES
from bilidownloader.api import BiliApi
from bilidownloader.chapter_processor import ChapterProcessor
from bilidownloader.constants import (
    DEFAULT_COOKIES,
    DEFAULT_HISTORY,
    DEFAULT_WATCHLIST,
    REINSTALL_ARGS,
    available_res,
)
from bilidownloader.fontmanager import initialize_fonts, loop_font_lookup
from bilidownloader.history import History
from bilidownloader.metadata_editor import MetadataEditor
from bilidownloader.ui import prn_error, prn_info, push_notification
from bilidownloader.utils import (
    BenchClock,
    DataExistError,
    check_package,
    pluralize,
)
from bilidownloader.utils import (
    SubtitleLanguage as SubLang,
)
from bilidownloader.video_downloader import VideoDownloader
from bilidownloader.watchlist import Watchlist


class BiliProcess:
    """Orchestrates video download and processing workflow"""

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
        output_dir: Optional[Path] = None,
    ) -> None:
        """Initialize BiliProcess with component-based architecture"""
        self.watchlist = watchlist
        self.history = history
        self.cookie = cookie
        self.notification = notification
        self.srt = srt
        self.dont_thumbnail = dont_thumbnail
        self.dont_convert = dont_convert
        self.subtitle_lang = subtitle_lang.value
        self.only_audio = only_audio

        if not srt and srt == check_package("ass"):
            prn_error(
                (
                    "`ass` package is not found inside the environment, "
                    "please reinstall `bilidownloader` by executing this command to "
                    "install the required package:"
                )
            )
            prn_error(REINSTALL_ARGS)
            prn_info("Reverting to use SRT")
            self.srt = True
        else:
            initialize_fonts()

        # Initialize component classes
        self.downloader = VideoDownloader(
            cookie=cookie,
            resolution=resolution,
            is_avc=is_avc,
            download_pv=download_pv,
            ffmpeg_path=ffmpeg_path,
            mkvmerge_path=mkvmerge_path,
            notification=notification,
            srt=srt,
            dont_rescale=dont_rescale,
            dont_convert=dont_convert,
            subtitle_lang=subtitle_lang.value,
            only_audio=only_audio,
            output_dir=output_dir,
        )
        self.chapter_processor = ChapterProcessor(
            mkvpropedit_path=mkvpropedit_path,
            ffmpeg_path=ffmpeg_path,
        )
        self.metadata_editor = MetadataEditor(
            mkvpropedit_path=mkvpropedit_path,
            mkvmerge_path=mkvmerge_path,
        )

    @staticmethod
    def ep_url(season_id: Union[int, str], episode_id: Union[int, str]) -> str:
        """Convert known IDs into proper, English episode URL"""
        return f"https://www.bilibili.tv/en/play/{season_id}/{episode_id}"

    def _get_video_info(self, episode_url: str):
        """Delegate to VideoDownloader"""
        return self.downloader.get_video_info(episode_url)

    def process_episode(self, episode_url: str, forced: bool = False) -> Optional[Path]:
        """Process episode from Bilibili"""
        clock = BenchClock()
        tries = 0
        history = History(self.history)

        # Normalize URL
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

                # Download video
                loc, data, language = self.downloader.download_episode(episode_url)

                # Process chapters
                chapters = self.downloader.get_episode_chapters(data)
                final = self.chapter_processor.embed_chapters(chapters, loc)

                # Prepare metadata arguments
                aud_args = self.metadata_editor.add_audio_language(final, language)

                font_args: List[str] = []
                if not self.srt or not self.dont_convert:
                    font_json = Path("fonts.json")
                    if font_json.exists():
                        font_json, font_args = loop_font_lookup(font_json, font_args)
                        font_json.unlink(True)

                sub_args = self.metadata_editor.set_default_subtitle(
                    data, final, self.subtitle_lang
                )  # type: ignore

                if not self.dont_thumbnail and not self.only_audio:
                    attachment_args = self.metadata_editor.insert_thumbnail(data)
                else:
                    attachment_args = []

                # Execute metadata editing
                final = self.metadata_editor.execute_mkvpropedit(
                    final, aud_args, sub_args, font_args, attachment_args
                )
                Path("thumbnail.png").unlink(True)

                # Update history
                if not forced:
                    series_id = ep_url.group(1) if ep_url else None
                    episode_id = ep_url.group(2) if ep_url else None
                    series_title = data.get(
                        "btitle", data.get("series", f"Series {series_id}")
                    )

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
            except Exception:
                prn_error("An exception has been thrown:")
                prn_error(traceback.format_exc())
                prn_info("Retrying...")
                tries += 1

    def process_playlist(self, playlist_url: str, forced: bool = False) -> List[Path]:
        """Process playlist from Bilibili"""
        clock = BenchClock()
        try:
            data = self._get_video_info(playlist_url)
        except Exception:
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
        """Process watchlist from Bilibili"""
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
