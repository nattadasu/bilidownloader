import re
from copy import deepcopy
from enum import Enum
from html import unescape
from pathlib import Path
from sys import exit
from typing import List, Optional

import survey
import typer
from rich import box
from rich import print as rprint
from rich.console import Console
from rich.table import Column, Table
from typing_extensions import Annotated

try:
    from api import BiliApi, BiliHtml
    from api_model import CardItem
    from common import (
        DEFAULT_HISTORY,
        DEFAULT_WATCHLIST,
        available_res,
        find_ffmpeg,
        find_mkvpropedit,
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
        available_res,
        find_ffmpeg,
        find_mkvpropedit,
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
hi_app = typer.Typer(no_args_is_help=True)
wl_app = typer.Typer(no_args_is_help=True)
app.add_typer(hi_app, name="history", help="View and manage history")

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
        "/--no-rescale",
        "/-N",
        help="Do not rescale SSA subtitle to fix subtitle size when by default it's too big",
    ),
]
"""Flag to not rescale SSA subtitle"""
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

#####################################
# END OF ARGS AND FLAGS DEFINITIONS #
#####################################

down_shelp = "Download via direct URL"


@app.command(
    name="download",
    short_help=f"{down_shelp}. Alias: down",
    no_args_is_help=True,
)
@app.command(name="down", short_help=down_shelp, hidden=True, no_args_is_help=True)
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
        dont_rescale=no_rescale,
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
    no_rescale: DO_NOT_RESCALE_SSA_OPT = False,
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
    )

    wl = Watchlist(watchlist_file)
    if not wl.search_watchlist(season_id=anime.season_id):
        if survey.routines.inquire(
            f"Do you want to save {anime.title} to watchlist? You can easily download latest episodes with dedicated commands. ",
            default=False,
        ):
            wl.add_watchlist(anime.season_id, anime.title)
    else:
        prn_info(f"{anime.title} is exist on watchlist, skipping prompt")


@app.command(
    "today", help="Get and download anime released today", no_args_is_help=True
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
        )
    except survey.widgets.Escape:
        exit(1)


@app.command(
    "released",
    help="Select and downloads released anime from 3 days prior",
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
        )
    except survey.widgets.Escape:
        exit(1)


@wl_app.command("list", help="Read list of monitored series on Bilibili")
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


@wl_app.command("add", help="Add a series to watchlist")
def watchlist_add(
    series_url: Annotated[
        Optional[str],
        typer.Argument(
            ...,
            help="If you obtained media/play URL of the show, and skip interactive mode",
            show_default=False,
        ),
    ] = None,
    file_path: WATCHLIST_OPT = DEFAULT_WATCHLIST,
    cookies: OPTCOOKIE_OPT = None,
    assume_yes: ASSUMEYES_OPT = False,
):
    wl = Watchlist(file_path, cookies)
    wids = {item[0] for item in wl.list}

    if series_url:
        search = re.search(bili_format, series_url)
        if search:
            media_id = search.group("media_id")
            url = f"https://www.bilibili.tv/en/media/{media_id}"
            resp = BiliHtml().get(url)
            ftitle = re.search(
                r'<h1.*class="detail-header__title".*>(.*)</h1>',
                resp.content.decode("utf-8"),
                re.IGNORECASE,
            )
            if ftitle:
                title = unescape(ftitle.group(1))
                index = {0}
                filt = [(media_id, title)]
            else:
                raise NameError("Title of the show can't be located")
        else:
            raise ValueError(f"{series_url} is not valid Bilibili series URL")
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
        confirm = assume_yes
        if cookies and not assume_yes:
            confirm = survey.routines.inquire(
                f"Do you want to add {title} ({sid}) to watchlist? ", default=False
            )
        wl.add_watchlist(filt[i][0], filt[i][1], confirm or not cookies)
    exit(0)


wl_del_help = "Delete series from watchlist"


@wl_app.command("delete", help=wl_del_help, short_help=f"{wl_del_help}. Alias: del")
@wl_app.command("del", help=wl_del_help, hidden=True)
def watchlist_delete(
    file_path: WATCHLIST_OPT = DEFAULT_WATCHLIST,
    cookies: OPTCOOKIE_OPT = None,
    assume_yes: ASSUMEYES_OPT = False,
):
    wl = Watchlist(file_path, cookies)
    index: Optional[List[int]] = None

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
        confirm = assume_yes
        if cookies and not assume_yes:
            confirm = survey.routines.inquire(
                f"Do you want to delete {sid} from watchlist? ", default=False
            )
        wl.delete_from_watchlist(sid, confirm or not cookies)
    exit(0)


wl_down_help = "Download all released episodes on watchlist, max 3 days old"
wl_down_shelp = "Download all episodes from watchlist"


@wl_app.command(
    "download", help=f"{wl_down_help}. Alias: down", short_help=wl_down_shelp
)
@wl_app.command(
    "down",
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
    )
    bili.process_watchlist(forced=forced)


@hi_app.command(
    "list", help="Show history of downloaded URLs, might be unreadable by normal mean"
)
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


@hi_app.command("clear", help="Clear history")
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


@app.command("schedule", help="Get release schedule")
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


@app.command("version", help="Show version")
@app.command("ver", help="Show version", hidden=True)
def version(
    plain: Annotated[
        bool,
        typer.Option(
            "--plain",
            "-p",
            help="Show version number only",
        ),
    ] = False,
):
    if plain:
        print(__VERSION__)
    else:
        rprint(f"[bold]BiliDownloader[/] version: [blue]{__VERSION__}[/]")
    typer.Exit()


if __name__ == "__main__":
    app()
