import re
from copy import deepcopy
from enum import Enum
from html import unescape
from pathlib import Path
from sys import exit
from typing import List, Optional, Tuple

import requests as req
import survey
import typer
from rich import box
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Column, Table
from tomllib import loads as tloads
from typing_extensions import Annotated

try:
    from api import BiliApi, BiliHtml
    from api_model import CardItem
    from common import (
        DEFAULT_HISTORY,
        DEFAULT_WATCHLIST,
        SubtitleLanguage,
        available_res,
        find_ffmpeg,
        find_mkvpropedit,
        prn_done,
        prn_error,
        prn_info,
    )
    from extractor import BiliProcess
    from history import History
    from metadata import __DESCRIPTION__, __VERSION__
    from watchlist import Watchlist
except ImportError:
    from bilidownloader.api import BiliApi, BiliHtml
    from bilidownloader.api_model import CardItem
    from bilidownloader.common import (
        DEFAULT_HISTORY,
        DEFAULT_WATCHLIST,
        SubtitleLanguage,
        available_res,
        find_ffmpeg,
        find_mkvpropedit,
        prn_done,
        prn_error,
        prn_info,
    )
    from bilidownloader.extractor import BiliProcess
    from bilidownloader.history import History
    from bilidownloader.metadata import __DESCRIPTION__, __VERSION__
    from bilidownloader.watchlist import Watchlist

console = Console()

app = typer.Typer(
    pretty_exceptions_show_locals=False,
    no_args_is_help=True,
    help=f"{__DESCRIPTION__} (Version: {__VERSION__})",
)
hi_app = typer.Typer(pretty_exceptions_show_locals=False, no_args_is_help=True)
wl_app = typer.Typer(pretty_exceptions_show_locals=False, no_args_is_help=True)
app.add_typer(hi_app, name="history", help="View and manage history. Alias: his, h")
app.add_typer(hi_app, name="his", help="View and manage history", hidden=True)
app.add_typer(hi_app, name="h", help="View and manage history", hidden=True)

wl_help = (
    "View and manage watchlist, or download recently released episodes from watchlist"
)
wl_shelp = "View and manage watchlist. Alias: wl"
app.add_typer(wl_app, name="watchlist", help=f"{wl_help}", short_help=wl_shelp)
app.add_typer(wl_app, name="wl", help=wl_help, hidden=True)


bili_format = r"https:\/\/(?:www\.)?bilibili\.tv\/(?:[a-z]{2}\/)?(?:play|media)\/(?P<media_id>\d+)(?:\/(?P<episode_id>\d+))?"
resos = [144, 240, 360, 480, 720, 1080, 2160]


def resolution_callback(user_input: int) -> int:
    if user_input in resos:
        return user_input
    raise typer.BadParameter(f"Only following values were accepted: {resos}")


def resolution_autocomplete():
    return resos


FFMPEG_PATH = find_ffmpeg()
MKVPROPEX_PATH = find_mkvpropedit()


def raise_ffmpeg(path: Optional[Path]):
    if path is None:
        raise FileNotFoundError("ffmpeg binary couldn't be found!")


def raise_mkvpropedit(path: Optional[Path]):
    if path is None:
        raise FileNotFoundError("mkvpropedit binary couldn't be found!")


##############################
# ARGS AND FLAGS DEFINITIONS #
##############################

URL_ARG = Annotated[
    str,
    typer.Argument(
        ...,
        help="Video or Playlist URL on Bilibili",
        show_default=False,
    ),
]
"""URL Argument for the command to download"""
cookies_help = "Path to your cookie.txt file"
cookie_option = typer.Option(
    "--cookie",
    "--cookie-file",
    "-c",
    help=cookies_help,
    prompt=True,
    show_default=False,
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
    ),
]
"""Watchlist option for the command to manage watchlist"""
HISTORY_OPT = Annotated[
    Path,
    typer.Option(
        "--history",
        "--history-file",
        "-h",
        help="Path to your history.txt file",
    ),
]
"""History option for the command to manage history"""
FORCED_OPT = Annotated[
    bool,
    typer.Option(
        "--force",
        "-F",
        help="Force download the video even if it was downloaded previously",
    ),
]
"""Forced flag for the command to download"""
RESO_OPT = Annotated[
    int,
    typer.Option(
        "--resolution",
        "--reso",
        "-r",
        help="Target video resolution, accepted value: 144 | 240 | 360 | 480 | 720 | 1080 | 2160",
        min=144,
        max=2160,
        callback=resolution_callback,
        autocompletion=resolution_autocomplete,
    ),
]
"""Resolution option for the command to download"""
AVC_OPT = Annotated[
    bool,
    typer.Option(
        "--is-avc",
        "--avc",
        "-a",
        help="Download the video with AVC as codec instead of HEVC. Enable this option if you had compability issue",
    ),
]
"""Flag to change the codec to AVC"""
SRT_OPT = Annotated[
    bool,
    typer.Option(
        "--srt-only",
        "--plain",
        "-S",
        help="Download the embedded subtitle as SRT only rather to prioritize SSA/SRT. Best for compatibility and readability",
    ),
]
"""Flag to download SRT only"""
DO_NOT_RESCALE_SSA_OPT = Annotated[
    bool,
    typer.Option(
        "--no-rescale",
        "-N",
        help="Do not rescale SSA subtitle to fix subtitle size when by default it's too big",
    ),
]
"""Flag to not rescale SSA subtitle"""
DO_NOT_ATTACH_THUMBNAIL_OPT = Annotated[
    bool,
    typer.Option(
        "--no-thumbnail",
        "-X",
        help="Do not download thumbnail from BiliBili then embed it",
    ),
]
SUBLANG_OPT = Annotated[
    Optional[SubtitleLanguage],
    typer.Option(
        "--sub-lang",
        "-l",
        help="Set the selected subtitle language to be default",
        case_sensitive=False,
        show_choices=True,
    ),
]
"""Set the selected subtitle language to be default"""
PV_OPT = Annotated[
    bool,
    typer.Option(
        "--pv",
        help="Also download PV, only affects if the url is a Playlist",
    ),
]
"""Flag to download PV"""
FFMPEG_OPT = Annotated[
    Optional[Path],
    typer.Option(
        "--ffmpeg-path",
        "--ffmpeg",
        help="Location of the ffmpeg binary; either the path to the binary or its containing directory",
    ),
]
"""Path to ffmpeg binary"""
MKVPROPEX_OPT = Annotated[
    Optional[Path],
    typer.Option(
        "--mkvpropedit-path",
        "--mkvpropedit",
        help="Location of the mkvpropedit binary; either the path to the binary or its containing directory",
    ),
]
"""Path to mkvpropedit binary"""
SHOWURL_OPT = Annotated[
    bool, typer.Option("--show-url", "-u", help="Generate URL to the show as well")
]
"""Flag to show URL"""
NOTIFY_OPT = Annotated[
    bool,
    typer.Option(
        "--notify",
        "-n",
        help="Send a notification when an episode has been downloaded",
    ),
]
"""Flag to send notification"""
ASSUMEYES_OPT = Annotated[
    bool,
    typer.Option(
        "--assumeyes", "-y", help="Automatically answer yes for all questions"
    ),
]
"""Flag to force accept all prompts to True"""
ASPLAYLIST_OPT = Annotated[
    bool,
    typer.Option(
        "--as-playlist",
        help=(
            "Download monitored series as a playlist (play/) instead of "
            "default behaviour by relying on recently released episodes in "
            "past 3 days. This option will download all episodes available "
            "including the old ones, so use with caution."
        ),
    ),
]
"""Flag to override default behaviour of downloading watchlist"""

#####################################
# END OF ARGS AND FLAGS DEFINITIONS #
#####################################

down_shelp = "Download via direct URL"


@app.command(
    name="download",
    short_help=f"{down_shelp}. Alias: down, dl, d",
    no_args_is_help=True,
)
@app.command(name="down", short_help=down_shelp, hidden=True, no_args_is_help=True)
@app.command(name="dl", short_help=down_shelp, hidden=True, no_args_is_help=True)
@app.command(name="d", short_help=down_shelp, hidden=True, no_args_is_help=True)
def download_url(
    url: URL_ARG,
    cookie: COOKIE_OPT,
    history_file: HISTORY_OPT = DEFAULT_HISTORY,
    forced: FORCED_OPT = False,
    resolution: RESO_OPT = 1080,
    is_avc: AVC_OPT = False,
    download_pv: PV_OPT = False,
    ffmpeg_path: FFMPEG_OPT = FFMPEG_PATH,
    mkvpropedit_path: MKVPROPEX_OPT = MKVPROPEX_PATH,
    notification: NOTIFY_OPT = False,
    srtonly: SRT_OPT = False,
    no_rescale: DO_NOT_RESCALE_SSA_OPT = False,
    sub_lang: SUBLANG_OPT = SubtitleLanguage.en,
    no_thumbnail: DO_NOT_ATTACH_THUMBNAIL_OPT = False,
):
    """Download via direct URL, let the app decide what type of the URL"""

    raise_ffmpeg(ffmpeg_path)
    raise_mkvpropedit(mkvpropedit_path)

    matches = re.search(bili_format, url)
    fix_reso: available_res = resolution  # type: ignore
    bili = BiliProcess(
        cookie,
        history_file,
        resolution=fix_reso,
        is_avc=is_avc,
        download_pv=download_pv,
        ffmpeg_path=ffmpeg_path,
        mkvpropedit_path=mkvpropedit_path,
        notification=notification,
        srt=srtonly,
        dont_thumbnail=no_thumbnail,
        dont_rescale=no_rescale,
        subtitle_lang=sub_lang,  # type: ignore
    )
    if matches:
        if not forced:
            History(history_file).check_history(url)
        if matches.group("episode_id"):
            prn_info("URL is an episode")
            bili.process_episode(url, forced)
        else:
            prn_info("URL is a playlist")
            bili.process_playlist(url, forced)
    else:
        raise ValueError("Link is not a valid Bilibili.tv URL")


def _cards_selector(
    cards: List[CardItem],
    cookie: Path,
    watchlist_file: Path = DEFAULT_WATCHLIST,
    history_file: Path = DEFAULT_HISTORY,
    forced: bool = False,
    resolution: int = 1080,
    is_avc: bool = False,
    download_pv: bool = False,
    ffmpeg_path: Optional[Path] = FFMPEG_PATH,
    mkvpropedit_path: Optional[Path] = MKVPROPEX_PATH,
    notification: bool = False,
    srtonly: bool = False,
    no_rescale: bool = False,
    sub_lang: Optional[str] = None,
    no_thumbnail: DO_NOT_ATTACH_THUMBNAIL_OPT = False,
):
    raise_ffmpeg(ffmpeg_path)
    raise_mkvpropedit(mkvpropedit_path)

    choices = [
        f"{anime.title} ({anime.index_show.removesuffix(' updated')})"
        for anime in cards
    ]
    if len(choices) == 0:
        raise LookupError("There is no releases aired yet.")
    query = survey.routines.select("Select a title to download: ", options=choices)
    if query is None:
        raise ValueError("Query is empty")
    anime = cards[query]
    as_playlist = survey.routines.inquire("Download as playlist? ", default=False)
    url = f"https://www.bilibili.tv/en/play/{anime.season_id}"
    url = url + f"/{anime.episode_id}" if not as_playlist else url
    prn_info(
        f"Downloading {anime.title} {anime.index_show.removesuffix(' updated')} ({url})"
    )
    download_url(
        url=url,
        cookie=cookie,
        history_file=history_file,
        forced=forced,
        resolution=resolution,
        is_avc=is_avc,
        download_pv=download_pv,
        ffmpeg_path=ffmpeg_path,
        mkvpropedit_path=mkvpropedit_path,
        notification=notification,
        srtonly=srtonly,
        no_rescale=no_rescale,
        sub_lang=sub_lang,  # type: ignore
        no_thumbnail=no_thumbnail,
    )

    wl = Watchlist(watchlist_file)
    if not wl.search_watchlist(season_id=anime.season_id):
        if survey.routines.inquire(
            f"Do you want to save {anime.title} to watchlist? You can easily download latest episodes with dedicated commands. ",
            default=False,
        ):
            wl.add_watchlist(anime.season_id, anime.title)
    else:
        prn_done(f"{anime.title} is exist on watchlist, skipping prompt")


@app.command(
    "today",
    help="Get and download anime released today. Alias: now",
    no_args_is_help=True,
)
@app.command(
    "now",
    help="Get and download anime released today",
    hidden=True,
    no_args_is_help=True,
)
def download_today_releases(
    cookie: COOKIE_OPT,
    watchlist_file: WATCHLIST_OPT = DEFAULT_WATCHLIST,
    history_file: HISTORY_OPT = DEFAULT_HISTORY,
    forced: FORCED_OPT = False,
    resolution: RESO_OPT = 1080,
    is_avc: AVC_OPT = False,
    download_pv: PV_OPT = False,
    ffmpeg_path: FFMPEG_OPT = FFMPEG_PATH,
    mkvpropedit_path: MKVPROPEX_OPT = MKVPROPEX_PATH,
    notification: NOTIFY_OPT = False,
    srtonly: SRT_OPT = False,
    no_rescale: DO_NOT_RESCALE_SSA_OPT = False,
    sub_lang: SUBLANG_OPT = SubtitleLanguage.en,
    no_thumbnail: DO_NOT_ATTACH_THUMBNAIL_OPT = False,
):
    raise_ffmpeg(ffmpeg_path)

    api = BiliApi().get_today_schedule()
    released = [anime for anime in api if anime.is_available]
    try:
        _cards_selector(
            released,
            cookie=cookie,
            watchlist_file=watchlist_file,
            history_file=history_file,
            forced=forced,
            resolution=resolution,
            is_avc=is_avc,
            download_pv=download_pv,
            ffmpeg_path=ffmpeg_path,
            mkvpropedit_path=mkvpropedit_path,
            notification=notification,
            srtonly=srtonly,
            no_rescale=no_rescale,
            sub_lang=sub_lang,
            no_thumbnail=no_thumbnail,
        )
    except survey.widgets.Escape:
        exit(1)


@app.command(
    "released",
    help="Select and downloads released anime from 3 days prior. Alias: rel",
    no_args_is_help=True,
)
@app.command(
    "rel",
    help="Select and downloads released anime from 3 days prior",
    hidden=True,
    no_args_is_help=True,
)
def download_all_releases(
    cookie: COOKIE_OPT,
    watchlist_file: WATCHLIST_OPT = DEFAULT_WATCHLIST,
    history_file: HISTORY_OPT = DEFAULT_HISTORY,
    forced: FORCED_OPT = False,
    resolution: RESO_OPT = 1080,
    is_avc: AVC_OPT = False,
    download_pv: PV_OPT = False,
    ffmpeg_path: FFMPEG_OPT = FFMPEG_PATH,
    mkvpropedit_path: MKVPROPEX_OPT = MKVPROPEX_PATH,
    notification: NOTIFY_OPT = False,
    srtonly: SRT_OPT = False,
    no_rescale: DO_NOT_RESCALE_SSA_OPT = False,
    sub_lang: SUBLANG_OPT = SubtitleLanguage.en,
    no_thumbnail: DO_NOT_ATTACH_THUMBNAIL_OPT = False,
):
    raise_ffmpeg(ffmpeg_path)
    raise_mkvpropedit(mkvpropedit_path)

    api = BiliApi().get_all_available_shows()
    released = [anime for anime in api if anime.is_available]
    released = sorted(released, key=lambda k: k.title)
    try:
        _cards_selector(
            released,
            cookie=cookie,
            watchlist_file=watchlist_file,
            history_file=history_file,
            forced=forced,
            resolution=resolution,
            is_avc=is_avc,
            download_pv=download_pv,
            ffmpeg_path=ffmpeg_path,
            mkvpropedit_path=mkvpropedit_path,
            notification=notification,
            srtonly=srtonly,
            no_rescale=no_rescale,
            sub_lang=sub_lang,
            no_thumbnail=no_thumbnail,
        )
    except survey.widgets.Escape:
        exit(1)


@wl_app.command("list", help="Read list of monitored series on Bilibili. Alias: ls, l")
@wl_app.command("ls", help="Read list of monitored series on Bilibili", hidden=True)
@wl_app.command("l", help="Read list of monitored series on Bilibili", hidden=True)
def watchlist_list(
    file_path: WATCHLIST_OPT = DEFAULT_WATCHLIST,
    show_url: SHOWURL_OPT = False,
):
    wl = Watchlist(file_path)

    if len(wl.list) == 0:
        prn_error("There are no series currently monitored")
        exit(2)

    prn_info("Below are currently monitored series:")

    items = sorted(wl.list, key=lambda k: k[1])
    head = [Column("No.", justify="right"), Column("ID", justify="center"), "Title"]
    if show_url:
        head.append("URL")
    table = Table(*head, box=box.ROUNDED)
    for index, item in enumerate(items):
        it = [str(index + 1), str(item[0]), item[1]]
        if show_url:
            it.append(f"https://www.bilibili.tv/media/{item[0]}")
        table.add_row(*it)
    console.print(table)


def _wl_do_proc(serial_url: str) -> Tuple[str, str]:
    search = re.search(bili_format, serial_url)
    if search:
        media_id = search.group("media_id")
    else:
        media_id = serial_url
    url = f"https://www.bilibili.tv/en/media/{media_id}"
    try:
        resp = BiliHtml().get(url)
    except Exception as e:
        raise ValueError(f"Failed to fetch {url}: {e}")
    ftitle = re.search(
        r'<h1.*class="detail-header__title".*>(.*)</h1>',
        resp.content.decode("utf-8"),
        re.IGNORECASE,
    )
    if ftitle:
        title = unescape(ftitle.group(1))
        return media_id, title
    else:
        raise NameError("Title of the show can't be located")


def wl_action_msg(action: str) -> str:
    return f"Series URL or ID to be {action} to watchlist. Use this if you obtained media/play URL of the show, and want to skip interactive mode"


@wl_app.command("add", help="Add a series to watchlist. Alias: insert, ins")
@wl_app.command("insert", help="Add a series to watchlist", hidden=True)
@wl_app.command("ins", help="Add a series to watchlist", hidden=True)
def watchlist_add(
    series: Annotated[
        Optional[List[str]],
        typer.Argument(
            ...,
            help=wl_action_msg("added"),
            show_default=False,
        ),
    ] = None,
    file_path: WATCHLIST_OPT = DEFAULT_WATCHLIST,
    cookies: OPTCOOKIE_OPT = None,
    assume_yes: ASSUMEYES_OPT = False,
):
    wl = Watchlist(file_path, cookies)
    wids = {item[0] for item in wl.list}

    if series:
        filt: List[Tuple[str, str]] = []
        for url in series:
            try:
                media_id, title = _wl_do_proc(url)
                if media_id not in wids:
                    filt.append((media_id, title))
                else:
                    prn_info(f"{title} is already exist on watchlist, skipping prompt")
            except Exception as e:
                prn_error(f"Error: {e}")
        if len(filt) == 0:
            prn_error("All series are already exist on watchlist")
            exit(2)
        index = [i for i in range(len(filt))]
    else:
        api = BiliApi().get_all_shows_simple()

        filt = [item for item in api if item[0] not in wids]
        while True:
            try:
                index = survey.routines.basket(
                    "Select any shows to be added: ",
                    options=[title for _, title in filt],
                )
                if index is not None:
                    break
                prn_error("Selection is empty. Press Esc or Ctrl+C to exit")
            except (survey.widgets.Escape, KeyboardInterrupt):
                exit(1)
    for i in index:
        sid = filt[i][0]
        title = filt[i][1]
        if cookies and not assume_yes:
            confirm = survey.routines.inquire(  # type: ignore
                f"Do you want to add {title} ({sid}) to watchlist? ", default=False
            )
        elif cookies and assume_yes:
            confirm = True
        else:
            confirm = False
        wl.add_watchlist(filt[i][0], filt[i][1], confirm)
    exit(0)


wl_del_help = "Delete series from watchlist"


@wl_app.command(
    "delete", help=wl_del_help, short_help=f"{wl_del_help}. Alias: del, remove, rm"
)
@wl_app.command("remove", help=wl_del_help, hidden=True)
@wl_app.command("rm", help=wl_del_help, hidden=True)
@wl_app.command("del", help=wl_del_help, hidden=True)
def watchlist_delete(
    series: Annotated[
        Optional[List[str]],
        typer.Argument(
            ...,
            help=wl_action_msg("deleted"),
            show_default=False,
        ),
    ] = None,
    file_path: WATCHLIST_OPT = DEFAULT_WATCHLIST,
    cookies: OPTCOOKIE_OPT = None,
    assume_yes: ASSUMEYES_OPT = False,
):
    wl = Watchlist(file_path, cookies)
    index: Optional[List[int]] = None

    if series:
        filt: List[Tuple[str, str]] = []
        for url in series:
            try:
                media_id, title = _wl_do_proc(url)
                if wl.search_watchlist(season_id=media_id):
                    filt.append((media_id, title))
                else:
                    prn_info(f"{title} is not exist on watchlist, skipping prompt")
            except Exception as e:
                prn_error(f"Error: {e}")
        if len(filt) == 0:
            prn_error("All series are not exist on watchlist")
            exit(2)
        # properly set index to avoid error by comparing from wl.list
        find = [media_id for media_id, _ in filt]
        index = [i for i, (sid, _) in enumerate(wl.list) if sid in find]
    else:
        while True:
            try:
                index = survey.routines.basket(
                    "Select any shows to be deleted: ",
                    options=[title for _, title in wl.list],
                )
                if index is not None:
                    break
                prn_error("Selection is empty. Press Esc or Ctrl+C to exit")
            except (survey.widgets.Escape, KeyboardInterrupt):
                exit(1)
    ids = []
    for i in index:
        ids.append(wl.list[i][0])

    for sid in ids:
        if cookies and not assume_yes:
            confirm = survey.routines.inquire(  # type: ignore
                f"Do you want to delete {sid} from watchlist? ", default=False
            )
        elif cookies and assume_yes:
            confirm = True
        else:
            confirm = False
        wl.delete_from_watchlist(sid, confirm)
    exit(0)


wl_down_help = "Download all released episodes on watchlist, max 3 days old"
wl_down_shelp = "Download all episodes from watchlist"


@wl_app.command(
    "download", help=f"{wl_down_help}. Alias: down, dl, d", short_help=wl_down_shelp
)
@wl_app.command(
    "down",
    help=wl_down_help,
    short_help=wl_down_shelp,
    hidden=True,
)
@wl_app.command(
    "dl",
    help=wl_down_help,
    short_help=wl_down_shelp,
    hidden=True,
)
@wl_app.command(
    "d",
    help=wl_down_help,
    short_help=wl_down_shelp,
    hidden=True,
)
def watchlist_download(
    cookie: COOKIE_OPT,
    watchlist_file: WATCHLIST_OPT = DEFAULT_WATCHLIST,
    history_file: HISTORY_OPT = DEFAULT_HISTORY,
    forced: FORCED_OPT = False,
    resolution: RESO_OPT = 1080,
    is_avc: AVC_OPT = False,
    ffmpeg_path: FFMPEG_OPT = FFMPEG_PATH,
    mkvpropedit_path: MKVPROPEX_OPT = MKVPROPEX_PATH,
    notification: NOTIFY_OPT = False,
    srtonly: SRT_OPT = False,
    no_rescale: DO_NOT_RESCALE_SSA_OPT = False,
    sub_lang: SUBLANG_OPT = SubtitleLanguage.en,
    as_playlist: ASPLAYLIST_OPT = False,
    no_thumbnail: DO_NOT_ATTACH_THUMBNAIL_OPT = False,
):
    raise_ffmpeg(ffmpeg_path)
    raise_mkvpropedit(mkvpropedit_path)

    fix_reso: available_res = resolution  # type: ignore
    bili = BiliProcess(
        cookie=cookie,
        history=history_file,
        watchlist=watchlist_file,
        resolution=fix_reso,
        is_avc=is_avc,
        download_pv=False,
        ffmpeg_path=ffmpeg_path,
        mkvpropedit_path=mkvpropedit_path,
        notification=notification,
        srt=srtonly,
        dont_rescale=no_rescale,
        subtitle_lang=sub_lang,  # type: ignore
        dont_thumbnail=no_thumbnail,
    )
    if not as_playlist:
        bili.process_watchlist(forced=forced)
    else:
        wl = Watchlist(watchlist_file)
        for sid, title in wl.list:
            url = f"https://www.bilibili.tv/en/play/{sid}"
            prn_info(f"Downloading {title} ({url})")
            bili.process_playlist(url, forced)


@hi_app.command(
    "list",
    help="Show history of downloaded URLs, might be unreadable by normal mean. Alias: ls, l",
)
@hi_app.command("ls", help="Show history of downloaded URLs", hidden=True)
@hi_app.command("l", help="Show history of downloaded URLs", hidden=True)
def history_list(
    file_path: HISTORY_OPT = DEFAULT_HISTORY,
):
    hi = History(file_path)

    if len(hi.list) == 0 or hi.list[0] == "":
        prn_error("Your history is clean!")
        exit(2)

    prn_info("Below is list of downloaded URLs:\n")

    items = sorted(hi.list)
    table = Table(Column("No.", justify="right"), "URL", box=box.ROUNDED)
    for index, item in enumerate(items):
        table.add_row(str(index + 1), item)
    console.print(table)


@hi_app.command("clear", help="Clear history. Alias: clean, purge, cls")
@hi_app.command("clean", help="Clear history", hidden=True)
@hi_app.command("purge", help="Clear history", hidden=True)
@hi_app.command("cls", help="Clear history", hidden=True)
def history_clear(
    file_path: HISTORY_OPT = DEFAULT_HISTORY,
    yes: ASSUMEYES_OPT = False,
):
    hi = History(file_path)
    prompt = False
    if not yes:
        prompt = survey.routines.inquire(
            "Do you want to clear the history? ", default=False
        )

    if prompt:
        yes = survey.routines.inquire("Are you sure? ", default=False)  # type: ignore

    if yes or not prompt:
        hi._write([])
        prn_info("History successfully cleared!")


class DayOfWeek(str, Enum):
    TODAY = "today"
    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


@app.command(
    "schedule", help="Get release schedule. Alias: calendar, cal, sch, timetable, tt"
)
@app.command("calendar", help="Get release schedule", hidden=True)
@app.command("cal", help="Get release schedule", hidden=True)
@app.command("sch", help="Get release schedule", hidden=True)
@app.command("timetable", help="Get release schedule", hidden=True)
@app.command("tt", help="Get release schedule", hidden=True)
def schedule(
    show_url: SHOWURL_OPT = False,
    day: Annotated[
        Optional[DayOfWeek], typer.Option("--day", "-d", help="Only show selected day")
    ] = None,
):
    api = BiliApi()
    data = api.get_anime_timeline()
    tpat = re.compile(r"(\d{2}:\d{2})")
    epat = re.compile(r"E(\d+(-\d+)?)")
    rprint(
        "[reverse green] Note [/] [green]Episodes that already aired have no airtime on the table"
    )
    for dow in data.data.items:
        if dow.is_today and day == DayOfWeek.TODAY:
            day = DayOfWeek(dow.full_day_of_week.lower())
        if day is not None and str(day.name.lower()) != dow.full_day_of_week.lower():
            continue
        is_today = " [blue] >> TODAY << [/]" if dow.is_today else ""
        rprint(
            f"[reverse blue bold] {dow.full_day_of_week} [/][reverse white] {dow.full_date_text} [/]{is_today}"
        )
        tab = Table(
            Column("Time", justify="center"),
            "Series ID",
            "Title",
            "Ep.",
            box=box.ROUNDED,
        )
        if show_url:
            tab.add_column("URL")
        released = []
        upcoming = []
        if not dow.cards:
            console.print(tab)
            continue
        for item in dow.cards:
            tmat = tpat.search(item.index_show)
            time = tmat.group(0) if tmat else ""
            emat = epat.search(item.index_show)
            eps = emat.group(0) if emat else ""
            ent = [time, item.season_id, item.title, eps]
            if show_url:
                ent.append(
                    f"https://www.bilibili.tv/play/{item.season_id}/{item.episode_id}"
                )
            released.append(ent) if time == "" else upcoming.append(ent)
        released = sorted(released, key=lambda e: e[2])
        upcoming = sorted(upcoming, key=lambda e: e[0])
        released.extend(upcoming)
        for anime in released:
            tab.add_row(*anime)
        console.print(tab)


# check for an update
def app_update() -> bool:
    """Check for an update from upstream's pyproject.toml"""
    latest_version = __VERSION__
    update_url = (
        "https://raw.githubusercontent.com/nattadasu/bilidownloader/main/pyproject.toml"
    )
    try:
        resp = req.get(update_url)
        resp.raise_for_status()
        data = tloads(resp.text)
        latest_version = data["project"]["version"]
        if latest_version != __VERSION__:
            warn = (
                f"[bold]BiliDownloader[/] has a new version: [blue]{latest_version}[/] "
                f"(Current: [red]{__VERSION__}[/]).\n"
                "Updating is recommended to get the latest features and bug fixes.\n\n"
                "To update, execute [black]`[/][bold]pipx upgrade bilidownloader[black]`[/]"
            )
            panel = Panel(
                warn,
                title="Update Available",
                box=box.ROUNDED,
                title_align="left",
                border_style="yellow",
                expand=False,
            )
            console.print(panel)
            print()
    except Exception as err:
        panel = Panel(
            f"Failed to check for an app update, reason: {err}",
            title="Update Check Failed",
            box=box.ROUNDED,
            title_align="left",
            border_style="red",
            expand=False,
        )
        console.print(panel)
        print()
    rprint(f"[reverse white] BiliDownloader [/][reverse blue bold] {__VERSION__} [/]")
    return latest_version != __VERSION__


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    app_update()


if __name__ == "__main__":
    app()
