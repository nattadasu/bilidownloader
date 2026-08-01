from typer_di import Depends

from bilidownloader.cli.application import app
from bilidownloader.cli.callbacks import (
    raise_cookie,
    raise_ffmpeg,
    raise_mkvmerge,
    raise_mkvpropedit,
)
from bilidownloader.cli.options import (
    URL_ARG,
    BinaryPaths,
    DownloadOptions,
    FileConfig,
    PostProcessingOptions,
)
from bilidownloader.downmux.orchestrator import BiliProcess


@app.command(
    name="download",
    short_help="Download via direct URL. Alias: down, dl, d",
    no_args_is_help=True,
)
@app.command(
    name="down", short_help="Download via direct URL", hidden=True, no_args_is_help=True
)
@app.command(
    name="dl", short_help="Download via direct URL", hidden=True, no_args_is_help=True
)
@app.command(
    name="d", short_help="Download via direct URL", hidden=True, no_args_is_help=True
)
def download_url(
    url: URL_ARG,
    files: FileConfig = Depends(FileConfig),
    bins: BinaryPaths = Depends(BinaryPaths),
    dl_opts: DownloadOptions = Depends(DownloadOptions),
    pp_opts: PostProcessingOptions = Depends(PostProcessingOptions),
) -> None:
    """Download via direct URL, let the app decide what type of the URL"""

    raise_ffmpeg(bins.ffmpeg_path)
    raise_mkvpropedit(bins.mkvpropedit_path)
    raise_mkvmerge(bins.mkvmerge_path)
    raise_cookie(files.cookie)

    bili = BiliProcess(
        file_config=files,
        download_options=dl_opts,
        post_processing_options=pp_opts,
        binary_paths=bins,
    )
    bili.download(url, dl_opts.forced)
