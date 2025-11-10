import re
from pathlib import Path

import survey
from typer_di import Depends

from bilidownloader.cli.callbacks import (
    raise_cookie,
    raise_ffmpeg,
    raise_mkvmerge,
    raise_mkvpropedit,
)
from bilidownloader.cli.options import (
    ASPLAYLIST_OPT,
    ASSUMEYES_OPT,
    BinaryPaths,
    DownloadOptions,
    FileConfig,
    OPTCOOKIE_OPT,
    PostProcessingOptions,
    URL_ARG,
    WATCHLIST_OPT,
    bili_format,
)
from bilidownloader.constants import DEFAULT_WATCHLIST, available_res
from bilidownloader.orchestrator import BiliProcess
from bilidownloader.history import History
from bilidownloader.ui import prn_done, prn_info
from bilidownloader.watchlist import Watchlist

from bilidownloader.cli.application import app


@app.command(
    name="download",
    short_help="Download via direct URL. Alias: down, dl, d",
    no_args_is_help=True,
)
@app.command(name="down", short_help="Download via direct URL", hidden=True, no_args_is_help=True)
@app.command(name="dl", short_help="Download via direct URL", hidden=True, no_args_is_help=True)
@app.command(name="d", short_help="Download via direct URL", hidden=True, no_args_is_help=True)
def download_url(
    url: URL_ARG,
    files: FileConfig = Depends(FileConfig),
    bins: BinaryPaths = Depends(BinaryPaths),
    dl_opts: DownloadOptions = Depends(DownloadOptions),
    pp_opts: PostProcessingOptions = Depends(PostProcessingOptions),
):
    """Download via direct URL, let the app decide what type of the URL"""

    raise_ffmpeg(bins.ffmpeg_path)
    raise_mkvpropedit(bins.mkvpropedit_path)
    raise_mkvmerge(bins.mkvmerge_path)
    raise_cookie(files.cookie)

    matches = re.search(bili_format, url)
    fix_reso: available_res = dl_opts.resolution  # type: ignore
    bili = BiliProcess(
        file_config=files,
        download_options=dl_opts,
        post_processing_options=pp_opts,
        binary_paths=bins,
    )
    if matches:
        if not dl_opts.forced:
            History(files.history_file).check_history(url)
        if matches.group("episode_id"):
            prn_info("URL is an episode")
            bili.process_episode(url, dl_opts.forced)
        else:
            prn_info("URL is a playlist")
            bili.process_playlist(url, dl_opts.forced)
    else:
        raise ValueError("Link is not a valid Bilibili.tv URL")
