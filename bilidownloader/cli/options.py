from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from typing_extensions import Annotated

from bilidownloader.commons.constants import (
    DEFAULT_COOKIES,
    DEFAULT_HISTORY,
    VideoResolution,
)
from bilidownloader.commons.filesystem import find_command
from bilidownloader.commons.utils import SubtitleLanguage, check_package

bili_format = r"https:\/\/(?:www\.)?bilibili\.tv\/(?:[a-z]{2}\/)?(?:play|media)\/(?P<media_id>\d+)(?:\/(?P<episode_id>\d+))?"
ass_status = check_package("ass")


class HistorySortBy(str, Enum):
    """Sort options for history list and query commands"""

    DATE = "date"
    TITLE = "title"
    SERIES_ID = "series-id"
    EPISODE_ID = "episode-id"


URL_ARG = Annotated[
    str,
    typer.Argument(
        ...,
        help="Video or Playlist URL on Bilibili",
        show_default=False,
        rich_help_panel="Input",
    ),
]
"""URL Argument for the command to download"""
cookies_help = "Path to your cookie.txt file"
cookie_option = typer.Option(
    "--cookie",
    "--cookie-file",
    "-c",
    help=cookies_help,
    show_default=True,
    rich_help_panel="Data Management",
)
optcookie = deepcopy(cookie_option)
optcookie.help = f"{cookies_help}. Use this argument option if you also want to update your Bilibili information"
optcookie.show_default = True
optcookie.prompt = False
COOKIE_OPT = Annotated[Path, cookie_option]
"""Path to Cookie File for the command to download"""
OPTCOOKIE_OPT = Annotated[Optional[Path], optcookie]
"""Path to Cookie File for the command to download, optional"""
WATCHLIST_OPT = Annotated[
    Path,
    typer.Option(
        "--watchlist",
        "--watchlist-file",
        "-w",
        help="Path to your watchlist.txt file",
        rich_help_panel="Data Management",
        resolve_path=True,
    ),
]
"""Watchlist option for the command to manage watchlist"""
HISTORY_OPT = Annotated[
    Path,
    typer.Option(
        "--history",
        "--history-file",
        "-h",
        help="Path to your history.v2.tsv file",
        rich_help_panel="Data Management",
        resolve_path=True,
    ),
]
"""History option for the command to manage history"""
FORCED_OPT = Annotated[
    bool,
    typer.Option(
        "--force",
        "-F",
        help="Force download the video even if it was downloaded previously",
        rich_help_panel="Filtering & Selection",
    ),
]
"""Forced flag for the command to download"""
RESO_OPT = Annotated[
    VideoResolution,
    typer.Option(
        "--resolution",
        "--reso",
        "-r",
        help="Target video resolution",
        rich_help_panel="Filtering & Selection",
    ),
]
"""Resolution option for the command to download"""
AVC_OPT = Annotated[
    bool,
    typer.Option(
        "--is-avc",
        "--avc",
        "-a",
        help="Download the video with AVC as codec instead of HEVC.",
        rich_help_panel="Filtering & Selection",
    ),
]
"""Flag to change the codec to AVC"""
SRT_OPT = Annotated[
    bool,
    typer.Option(
        "--srt-only",
        "--plain",
        "-S",
        help=(
            "Download subtitles in SRT format only, instead of SSA/SRT. "
            "Enabled by default on a base installation."
        ),
        rich_help_panel="Filtering & Selection",
    ),
]
"""Flag to download SRT only"""
SKIP_NO_SUBTITLE_OPT = Annotated[
    bool,
    typer.Option(
        "--skip-no-subtitle",
        help="Skip downloading the episode if no subtitles are available.",
        rich_help_panel="Filtering & Selection",
    ),
]
"""Flag to skip episodes without subtitles"""
AUDIO_OPT = Annotated[
    bool,
    typer.Option(
        "--audio-only",
        "-A",
        help="Download audio only. Will override ALL other options: resolution, codec, etc.",
        rich_help_panel="Filtering & Selection",
    ),
]
DO_NOT_RESCALE_SSA_OPT = Annotated[
    bool,
    typer.Option(
        "--no-rescale",
        "-N",
        help=(
            "Prevent rescaling of SSA subtitles, which is typically done to adjust "
            "subtitle size when it appears too large by default. "
            "No action will be taken on a base installation."
        ),
        rich_help_panel="Post-Processing",
    ),
]
"""Flag to not rescale SSA subtitle"""
DO_NOT_ATTACH_THUMBNAIL_OPT = Annotated[
    bool,
    typer.Option(
        "--no-thumbnail",
        "-X",
        help="Do not download thumbnail from BiliBili then embed it",
        rich_help_panel="Post-Processing",
    ),
]
DO_NOT_CONVERT_SRT_OPT = Annotated[
    bool,
    typer.Option(
        "--no-convert",
        "-C",
        help="Do not convert SRT subtitles to ASS format",
        rich_help_panel="Post-Processing",
    ),
]
"""Flag to skip SRT to ASS conversion"""
SUBLANG_OPT = Annotated[
    Optional[SubtitleLanguage],
    typer.Option(
        "--sub-lang",
        "-l",
        help="Set the selected subtitle language to be default",
        case_sensitive=False,
        show_choices=True,
        rich_help_panel="Post-Processing",
    ),
]
"""Set the selected subtitle language to be default"""
PV_OPT = Annotated[
    bool,
    typer.Option(
        "--pv",
        help="Download promotional videos (PV) as well. Only applicable if the URL is a playlist.",
        rich_help_panel="Filtering & Selection",
    ),
]
"""Flag to download PV"""
FFMPEG_OPT = Annotated[
    Optional[Path],
    typer.Option(
        "--ffmpeg-path",
        "--ffmpeg",
        help="Specify the path to the ffmpeg binary or its containing directory",
        rich_help_panel="Binaries",
    ),
]
"""Path to ffmpeg binary"""
MKVPROPEX_OPT = Annotated[
    Optional[Path],
    typer.Option(
        "--mkvpropedit-path",
        "--mkvpropedit",
        help="Specify the path to the mkvpropedit binary or its containing directory",
        rich_help_panel="Binaries",
    ),
]
"""Path to mkvpropedit binary"""
MKVMERGE_OPT = Annotated[
    Optional[Path],
    typer.Option(
        "--mkvmerge-path",
        "--mkvmerge",
        help="Specify the path to the mkvmerge binary or its containing directory",
        rich_help_panel="Binaries",
    ),
]
"""Path to mkvmerge binary"""
SHOWURL_OPT = Annotated[
    bool,
    typer.Option(
        "--show-url",
        "-u",
        help="Generate URL to the show as well",
        rich_help_panel="Output",
    ),
]
"""Flag to show URL"""
NOTIFY_OPT = Annotated[
    bool,
    typer.Option(
        "--notify",
        "-n",
        help="Send a notification when an episode has been downloaded",
        rich_help_panel="Post-Processing",
    ),
]
"""Flag to send notification"""
ASSUMEYES_OPT = Annotated[
    bool,
    typer.Option(
        "--assumeyes",
        "-y",
        help="Automatically answer yes for all questions",
        rich_help_panel="Input",
    ),
]
"""Flag to force accept all prompts to True"""
SKIPREMOTE_OPT = Annotated[
    bool,
    typer.Option(
        "--skip-remote",
        "-R",
        help="Skip updating changes to Bilibili's server (add/delete from Favorites)",
        rich_help_panel="Data Management",
    ),
]
"""Flag to skip remote update on watchlist operations"""
ASPLAYLIST_OPT = Annotated[
    bool,
    typer.Option(
        "--as-playlist",
        help=(
            "Download monitored series as a playlist (play/) instead of the "
            "default behavior by relying on recently released episodes in the "
            "past 3 days. This option will download all episodes available, "
            "including the old ones, so use with caution."
        ),
        rich_help_panel="Filtering & Selection",
    ),
]
"""Flag to override default behaviour of downloading watchlist"""
VERBOSE_OPT = Annotated[
    bool,
    typer.Option(
        "--verbose",
        "-v",
        help="Enable verbose output from yt-dlp downloader",
        rich_help_panel="Output",
    ),
]
"""Flag to enable verbose output"""
PROXY_OPT = Annotated[
    Optional[str],
    typer.Option(
        "--proxy",
        "-p",
        help="Proxy URL for requests and yt-dlp (e.g., http://proxy.example.com:8080, socks5://127.0.0.1:1080)",
        rich_help_panel="Network",
    ),
]
"""Proxy URL option for network requests"""
SIMULATE_OPT = Annotated[
    bool,
    typer.Option(
        "--simulate",
        "-s",
        help="Simulate download without actually downloading files. Still records history.",
        rich_help_panel="Output",
    ),
]
"""Flag to simulate download without downloading"""

FFMPEG_PATH = find_command("ffmpeg")
MKVPROPEX_PATH = find_command("mkvpropedit")
MKVMERGE_PATH = find_command("mkvmerge")


@dataclass
class BinaryPaths:
    """Binary paths dependency"""

    ffmpeg_path: FFMPEG_OPT = FFMPEG_PATH
    mkvpropedit_path: MKVPROPEX_OPT = MKVPROPEX_PATH
    mkvmerge_path: MKVMERGE_OPT = MKVMERGE_PATH


@dataclass
class FileConfig:
    """File configuration dependency"""

    cookie: COOKIE_OPT = DEFAULT_COOKIES
    history_file: HISTORY_OPT = DEFAULT_HISTORY
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            "--output",
            "-o",
            help="Directory to save downloaded videos",
            rich_help_panel="Data Management",
            resolve_path=True,
        ),
    ] = Path.cwd()


@dataclass
class DownloadOptions:
    """Download options dependency"""

    resolution: RESO_OPT = VideoResolution.P1080
    srtonly: SRT_OPT = not ass_status
    is_avc: AVC_OPT = False
    forced: FORCED_OPT = False
    download_pv: PV_OPT = False
    verbose: VERBOSE_OPT = False
    skip_no_subtitle: SKIP_NO_SUBTITLE_OPT = False
    proxy: PROXY_OPT = None
    simulate: SIMULATE_OPT = False


@dataclass
class PostProcessingOptions:
    """Post-processing options dependency"""

    sub_lang: SUBLANG_OPT = SubtitleLanguage.en
    notification: NOTIFY_OPT = False
    no_rescale: DO_NOT_RESCALE_SSA_OPT = False
    no_thumbnail: DO_NOT_ATTACH_THUMBNAIL_OPT = False
    no_convert: DO_NOT_CONVERT_SRT_OPT = False
    audio_only: AUDIO_OPT = False
