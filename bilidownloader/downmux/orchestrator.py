import traceback
from pathlib import Path
from re import search as rsearch
from typing import List, Optional, Union

from bilidownloader.apis.api import BiliApi
from bilidownloader.cli.options import (
    BinaryPaths,
    DownloadOptions,
    FileConfig,
    PostProcessingOptions,
)
from bilidownloader.commons.alias import SERIES_ALIASES
from bilidownloader.commons.constants import (
    DEFAULT_WATCHLIST,
    REINSTALL_ARGS,
)
from bilidownloader.commons.ui import prn_error, prn_info, push_notification
from bilidownloader.commons.utils import (
    BenchClock,
    DataExistError,
    SubtitleLanguage,
    check_package,
    pluralize,
)
from bilidownloader.downmux.chapter_processor import ChapterProcessor
from bilidownloader.downmux.fontmanager import initialize_fonts, loop_font_lookup
from bilidownloader.downmux.metadata_editor import MetadataEditor
from bilidownloader.downmux.ytdlp import VideoDownloader
from bilidownloader.history.history import History
from bilidownloader.watchlist.watchlist import Watchlist


class BiliProcess:
    """Orchestrates video download and processing workflow"""

    def __init__(
        self,
        file_config: FileConfig,
        download_options: DownloadOptions,
        post_processing_options: PostProcessingOptions,
        binary_paths: BinaryPaths,
        watchlist: Path = DEFAULT_WATCHLIST,
    ) -> None:
        """Initialize BiliProcess with component-based architecture"""
        self.watchlist = watchlist
        self.history = file_config.history_file
        self.cookie = file_config.cookie
        self.notification = post_processing_options.notification
        self.srt = download_options.srtonly
        self.dont_thumbnail = post_processing_options.no_thumbnail
        self.dont_convert = post_processing_options.no_convert
        self.subtitle_lang = post_processing_options.sub_lang
        self.only_audio = post_processing_options.audio_only

        if not self.srt and self.srt == check_package("ass"):
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
            cookie=file_config.cookie,
            resolution=download_options.resolution,
            is_avc=download_options.is_avc,
            download_pv=download_options.download_pv,
            ffmpeg_path=binary_paths.ffmpeg_path,
            mkvmerge_path=binary_paths.mkvmerge_path,
            notification=post_processing_options.notification,
            srt=download_options.srtonly,
            dont_rescale=post_processing_options.no_rescale,
            dont_convert=post_processing_options.no_convert,
            subtitle_lang=post_processing_options.sub_lang or SubtitleLanguage.en,
            only_audio=post_processing_options.audio_only,
            output_dir=file_config.output_dir,
            verbose=download_options.verbose,
        )
        if binary_paths.ffmpeg_path is None:
            raise ValueError("ffmpeg path is not set properly")
        if binary_paths.mkvpropedit_path is None:
            raise ValueError("mkvpropedit path is not set properly")
        if binary_paths.mkvmerge_path is None:
            raise ValueError("mkvmerge path is not set properly")
        self.chapter_processor = ChapterProcessor(
            mkvpropedit_path=binary_paths.mkvpropedit_path,
            ffmpeg_path=binary_paths.ffmpeg_path,
        )
        self.metadata_editor = MetadataEditor(
            mkvpropedit_path=binary_paths.mkvpropedit_path,
            mkvmerge_path=binary_paths.mkvmerge_path,
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
