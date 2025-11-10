from pathlib import Path
from sys import exit
from typing import List

import survey
from typer_di import Depends

from bilidownloader.api import BiliApi
from bilidownloader.api_model import CardItem
from bilidownloader.cli.callbacks import (
    raise_cookie,
    raise_ffmpeg,
    raise_mkvmerge,
    raise_mkvpropedit,
)
from bilidownloader.cli.download import download_url
from bilidownloader.cli.options import (
    BinaryPaths,
    DownloadOptions,
    FileConfig,
    PostProcessingOptions,
    WATCHLIST_OPT,
)
from bilidownloader.constants import DEFAULT_WATCHLIST
from bilidownloader.ui import prn_done, prn_info
from bilidownloader.watchlist import Watchlist

from bilidownloader.cli.application import app


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
        files=files,
        bins=bins,
        dl_opts=dl_opts,
        pp_opts=pp_opts,
    )

    wl = Watchlist(watchlist_file)
    if not wl.search_watchlist(season_id=anime.season_id):
        if survey.routines.inquire(
            f"Would you like to add {anime.title} to your watchlist? This allows you to quickly download the latest episodes using dedicated commands.",
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
    watchlist_file: WATCHLIST_OPT = DEFAULT_WATCHLIST,
    files: FileConfig = Depends(FileConfig),
    bins: BinaryPaths = Depends(BinaryPaths),
    dl_opts: DownloadOptions = Depends(DownloadOptions),
    pp_opts: PostProcessingOptions = Depends(PostProcessingOptions),
):
    raise_ffmpeg(bins.ffmpeg_path)
    raise_mkvmerge(bins.mkvmerge_path)
    raise_cookie(files.cookie)

    api = BiliApi().get_today_schedule()
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
):
    raise_ffmpeg(bins.ffmpeg_path)
    raise_mkvpropedit(bins.mkvpropedit_path)
    raise_mkvmerge(bins.mkvmerge_path)
    raise_cookie(files.cookie)

    api = BiliApi().get_all_available_shows()
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
