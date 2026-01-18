from pathlib import Path
from sys import exit
from typing import List

import survey
from typer_di import Depends

from bilidownloader.apis.api import BiliApi
from bilidownloader.apis.models import CardItem
from bilidownloader.cli.application import app
from bilidownloader.cli.callbacks import (
    raise_cookie,
    raise_ffmpeg,
    raise_mkvmerge,
    raise_mkvpropedit,
)
from bilidownloader.cli.download import download_url
from bilidownloader.cli.options import (
    WATCHLIST_OPT,
    BinaryPaths,
    DownloadOptions,
    FileConfig,
    PostProcessingOptions,
)
from bilidownloader.commons.alias import SERIES_ALIASES
from bilidownloader.commons.constants import DEFAULT_WATCHLIST
from bilidownloader.commons.ui import prn_done, prn_info
from bilidownloader.commons.utils import sanitize_filename
from bilidownloader.watchlist.watchlist import Watchlist


def _cards_selector(
    cards: List[CardItem],
    watchlist_file: Path,
    files: FileConfig,
    bins: BinaryPaths,
    dl_opts: DownloadOptions,
    pp_opts: PostProcessingOptions,
):
    raise_ffmpeg(bins.ffmpeg_path)
    raise_mkvpropedit(bins.mkvpropedit_path)
    raise_mkvmerge(bins.mkvmerge_path)
    raise_cookie(files.cookie)

    choices = [
        f"{SERIES_ALIASES.get(anime.season_id, anime.title)} ({anime.index_show.removesuffix(' updated')})"
        for anime in cards
    ]
    if len(choices) == 0:
        raise LookupError("There is no releases aired yet.")
    query = survey.routines.select("Select a title to download: ", options=choices)
    if query is None:
        raise ValueError("Query is empty")
    anime = cards[query]
    display_title = sanitize_filename(SERIES_ALIASES.get(anime.season_id, anime.title))
    as_playlist = survey.routines.inquire("Download as playlist? ", default=False)
    url = f"https://www.bilibili.tv/en/play/{anime.season_id}"
    url = url + f"/{anime.episode_id}" if not as_playlist else url
    prn_info(
        f"Downloading {display_title} {anime.index_show.removesuffix(' updated')} ({url})"
    )
    download_url(
        url=url,
        files=files,
        bins=bins,
        dl_opts=dl_opts,
        pp_opts=pp_opts,
    )

    wl = Watchlist(watchlist_file)
    if not wl.search_watchlist(season_id=anime.season_id):
        if survey.routines.inquire(
            f"Would you like to add {display_title} to your watchlist? This allows you to quickly download the latest episodes using dedicated commands.",
            default=False,
        ):
            wl.add_watchlist(anime.season_id, display_title)
    else:
        prn_done(f"{display_title} is exist on watchlist, skipping prompt")


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
    watchlist_file: WATCHLIST_OPT = DEFAULT_WATCHLIST,
    files: FileConfig = Depends(FileConfig),
    bins: BinaryPaths = Depends(BinaryPaths),
    dl_opts: DownloadOptions = Depends(DownloadOptions),
    pp_opts: PostProcessingOptions = Depends(PostProcessingOptions),
) -> None:
    raise_ffmpeg(bins.ffmpeg_path)
    raise_mkvmerge(bins.mkvmerge_path)
    raise_cookie(files.cookie)

    api = BiliApi(proxy=dl_opts.proxy).get_today_schedule()
    released = [anime for anime in api if anime.is_available]
    try:
        _cards_selector(
            released,
            watchlist_file=watchlist_file,
            files=files,
            bins=bins,
            dl_opts=dl_opts,
            pp_opts=pp_opts,
        )
    except survey.widgets.Escape:
        exit(1)


@app.command(
    "released",
    help="Select and download anime released in the past 3 days. Alias: rel",
    no_args_is_help=True,
)
@app.command(
    "rel",
    help="Select and download anime released in the past 3 days",
    hidden=True,
    no_args_is_help=True,
)
def download_all_releases(
    watchlist_file: WATCHLIST_OPT = DEFAULT_WATCHLIST,
    files: FileConfig = Depends(FileConfig),
    bins: BinaryPaths = Depends(BinaryPaths),
    dl_opts: DownloadOptions = Depends(DownloadOptions),
    pp_opts: PostProcessingOptions = Depends(PostProcessingOptions),
) -> None:
    raise_ffmpeg(bins.ffmpeg_path)
    raise_mkvpropedit(bins.mkvpropedit_path)
    raise_mkvmerge(bins.mkvmerge_path)
    raise_cookie(files.cookie)

    api = BiliApi(proxy=dl_opts.proxy).get_all_available_shows()
    released = [anime for anime in api if anime.is_available]
    released = sorted(released, key=lambda k: k.title)
    try:
        _cards_selector(
            released,
            watchlist_file=watchlist_file,
            files=files,
            bins=bins,
            dl_opts=dl_opts,
            pp_opts=pp_opts,
        )
    except survey.widgets.Escape:
        exit(1)
