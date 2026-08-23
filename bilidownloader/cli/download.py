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
    from bilidownloader.downmux.orchestrator import download

    raise_ffmpeg(bins.ffmpeg_path)
    raise_mkvpropedit(bins.mkvpropedit_path)
    raise_mkvmerge(bins.mkvmerge_path)
    raise_cookie(files.cookie)

    download(
        url=url,
        output_dir=files.output_dir,
        resolution=str(dl_opts.resolution.value)
        if hasattr(dl_opts.resolution, "value")
        else str(dl_opts.resolution),
        is_avc=dl_opts.is_avc,
        forced=dl_opts.forced,
        verbose=dl_opts.verbose,
        skip_no_subtitle=dl_opts.skip_no_subtitle,
        ensure_sub=dl_opts.ensure_sub,
        proxy=dl_opts.proxy,
        no_thumbnail=pp_opts.no_thumbnail,
        no_mods=pp_opts.no_mods,
        notification=pp_opts.notification,
        cookie_path=files.cookie,
        history_path=files.history_file,
        ffmpeg_path=bins.ffmpeg_path,
        mkvpropedit_path=bins.mkvpropedit_path,
        mkvmerge_path=bins.mkvmerge_path,
    )
