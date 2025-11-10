import re
from html import unescape
from pathlib import Path
from sys import exit
from typing import Annotated, List, Optional, Tuple

import survey
from rich import box
from rich.console import Console
from rich.table import Column, Table
from typer_di import Depends, TyperDI

from bilidownloader.api import BiliApi, BiliHtml
from bilidownloader.cli.callbacks import raise_cookie
from bilidownloader.cli.download import download_url
from bilidownloader.cli.options import (
    ASPLAYLIST_OPT,
    ASSUMEYES_OPT,
    BinaryPaths,
    DownloadOptions,
    FileConfig,
    OPTCOOKIE_OPT,
    PostProcessingOptions,
    SHOWURL_OPT,
    WATCHLIST_OPT,
    bili_format,
)
from bilidownloader.constants import DEFAULT_WATCHLIST
from bilidownloader.extractor import BiliProcess
from bilidownloader.ui import prn_error, prn_info
from bilidownloader.watchlist import Watchlist

from bilidownloader.cli.application import wl_app
console = Console()


@wl_app.command("list", help="Read list of monitored series on Bilibili. Alias: ls, l")
@wl_app.command("ls", help="Read list of monitored series on Bilibili", hidden=True)
@wl_app.command("l", help="Read list of monitored series on Bilibili", hidden=True)
def watchlist_list(
    show_url: SHOWURL_OPT = False,
    file_path: WATCHLIST_OPT = DEFAULT_WATCHLIST,
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
    return (
        f"Provide the series URL or ID to be {action} in the watchlist."
        "Use this option if you have the media/play URL of the show and want "
        "to bypass interactive mode."
    )


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
            rich_help_panel="Input",
        ),
    ] = None,
    assume_yes: ASSUMEYES_OPT = False,
    file_path: WATCHLIST_OPT = DEFAULT_WATCHLIST,
    cookies: OPTCOOKIE_OPT = None,
):
    raise_cookie(cookies)
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
            rich_help_panel="Input",
        ),
    ] = None,
    assume_yes: ASSUMEYES_OPT = False,
    file_path: WATCHLIST_OPT = DEFAULT_WATCHLIST,
    cookies: OPTCOOKIE_OPT = None,
):
    raise_cookie(cookies)
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
                    prn_info(f"{title} is not found in the watchlist, skipping.")
            except Exception as e:
                prn_error(f"Error: {e}")
        if len(filt) == 0:
            prn_error("None of the specified series are found in the watchlist.")
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
    watchlist_file: WATCHLIST_OPT = DEFAULT_WATCHLIST,
    as_playlist: ASPLAYLIST_OPT = False,
    files: FileConfig = Depends(FileConfig),
    bins: BinaryPaths = Depends(BinaryPaths),
    dl_opts: DownloadOptions = Depends(DownloadOptions),
    pp_opts: PostProcessingOptions = Depends(PostProcessingOptions),
):
    raise_cookie(files.cookie)
    raise_ffmpeg(bins.ffmpeg_path)
    raise_mkvpropedit(bins.mkvpropedit_path)
    raise_mkvmerge(bins.mkvmerge_path)

    fix_reso = dl_opts.resolution  # type: ignore
    bili = BiliProcess(
        cookie=files.cookie,
        history=files.history_file,
        watchlist=watchlist_file,
        resolution=fix_reso,
        is_avc=dl_opts.is_avc,
        download_pv=False,
        ffmpeg_path=bins.ffmpeg_path,
        mkvpropedit_path=bins.mkvpropedit_path,
        mkvmerge_path=bins.mkvmerge_path,
        notification=pp_opts.notification,
        srt=dl_opts.srtonly,
        dont_rescale=pp_opts.no_rescale,
        dont_convert=pp_opts.no_convert,
        subtitle_lang=pp_opts.sub_lang,  # type: ignore
        dont_thumbnail=pp_opts.no_thumbnail,
        only_audio=pp_opts.audio_only,
        output_dir=files.output_dir,
    )
    if not as_playlist:
        bili.process_watchlist(forced=dl_opts.forced)
    else:
        wl = Watchlist(watchlist_file)
        for sid, title in wl.list:
            url = f"https://www.bilibili.tv/en/play/{sid}"
            prn_info(f"Downloading {title} ({url})")
            bili.process_playlist(url, dl_opts.forced)
