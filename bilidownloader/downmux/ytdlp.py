"""
Video downloader - handles yt-dlp download operations
"""

from html import unescape
from pathlib import Path
from re import IGNORECASE
from re import search as rsearch
from re import sub as rsub
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from fake_useragent import UserAgent
from yt_dlp import YoutubeDL as YDL

from bilidownloader.apis.api import BiliHtml
from bilidownloader.commons.alias import SERIES_ALIASES
from bilidownloader.commons.constants import REINSTALL_ARGS
from bilidownloader.commons.ui import prn_error, prn_info, push_notification
from bilidownloader.commons.utils import (
    Chapter,
    SubtitleLanguage,
    check_package,
    sanitize_filename,
)

ua = UserAgent()
uagent = ua.chrome


class VideoDownloader:
    """Handles video download operations using yt-dlp"""

    def __init__(
        self,
        cookie: Path,
        resolution: int = 1080,
        is_avc: bool = False,
        download_pv: bool = False,
        ffmpeg_path: Optional[Path] = None,
        mkvmerge_path: Optional[Path] = None,
        notification: bool = False,
        srt: bool = False,
        dont_rescale: bool = False,
        dont_convert: bool = False,
        subtitle_lang: SubtitleLanguage = SubtitleLanguage.en,
        only_audio: bool = False,
        output_dir: Optional[Path] = None,
        verbose: bool = False,
    ):
        self.cookie = cookie
        self.resolution = resolution
        self.is_avc = is_avc
        self.download_pv = download_pv
        self.ffmpeg_path = ffmpeg_path
        self.mkvmerge_path = mkvmerge_path
        self.notification = notification
        self.srt = srt
        self.dont_rescale = dont_rescale
        self.dont_convert = dont_convert
        self.subtitle_lang = subtitle_lang
        self.only_audio = only_audio
        self.output_dir = output_dir or Path.cwd()
        self.verbose = verbose

    def get_video_info(self, episode_url: str) -> Union[Any, Dict[str, Any], None]:
        """Get video information from yt-dlp"""
        ydl_opts = {
            "cookiefile": str(self.cookie),
            "extract_flat": "discard_in_playlist",
            "forcejson": True,
            "fragment_retries": 10,
            "ignoreerrors": "only_download",
            "noprogress": True,
            "postprocessors": [
                {"key": "FFmpegConcat", "only_multi_video": True, "when": "playlist"}
            ],
            "retries": 10,
            "simulate": True,
            "verbose": False,
            "quiet": True,
            "referer": "https://www.bilibili.tv/",
        }
        if self.ffmpeg_path:
            ydl_opts["ffmpeg_location"] = str(self.ffmpeg_path)
        with YDL(ydl_opts) as ydl:  # type: ignore
            return ydl.extract_info(episode_url, download=False)

    @staticmethod
    def get_episode_chapters(raw_info: Dict[str, Any]) -> List[Chapter]:
        """Get chapters from video metadata"""
        try:
            return [Chapter(**chs) for chs in raw_info["chapters"]]
        except Exception:
            return []

    def download_episode(
        self,
        episode_url: str,
    ) -> Tuple[Path, Any, Optional[Literal["ind", "jpn", "chi", "tha"]]]:
        """Download episode from Bilibili with yt-dlp"""
        prn_info("Resolving some metadata information of the link, may take a while")
        html = BiliHtml(cookie_path=self.cookie, user_agent=uagent)
        resp = html.get(episode_url)

        ep_url = rsearch(r"play/(\d+)/(\d+)", episode_url)
        series_id = ep_url.group(1) if ep_url else None
        ftitle = rsearch(
            r"<title>(.*)</title>", resp.content.decode("utf-8"), IGNORECASE
        )
        if ftitle:
            title = rsub(
                r"\s+(?:E\d+|PV\d*|SP\d*|OVA\d*).*$",
                "",
                ftitle.group(1),
            )
            title = sanitize_filename(unescape(title))
        else:
            title = ftitle

        if series_id and series_id in SERIES_ALIASES:
            title = sanitize_filename(SERIES_ALIASES[series_id])

        # Determine audio language
        language: Optional[Literal["ind", "jpn", "chi", "tha"]] = None
        language = "chi" if "Chinese Mainland" in resp.text else language
        if language is None:
            language = "jpn" if "Japan" in resp.text else language
        jp_dub = ["JP Ver", "JPN Dub"]
        ch_dub = ["Dub CN", "พากย์จีน"]
        id_dub = ["Dub Indo", "ID dub"]
        th_dub = ["Thai Dub", "TH dub"]
        if any(x.lower() in str(title).lower() for x in jp_dub):
            language = "jpn"
        elif any(x.lower() in str(title).lower() for x in ch_dub):
            language = "chi"
        elif any(x.lower() in str(title).lower() for x in id_dub):
            language = "ind"
        elif any(x.lower() in str(title).lower() for x in th_dub):
            language = "tha"

        codec = "avc1" if self.is_avc else "hev1"
        hcodec = "AVC" if self.is_avc else "HEVC"

        ydl_opts = {
            "cookiefile": str(self.cookie),
            "extract_flat": "discard_in_playlist",
            "force_print": {"after_move": ["filepath"]},
            "format": f"bv*[vcodec^={codec}][height={self.resolution}]+ba",
            "fragment_retries": 10,
            "ignoreerrors": "only_download",
            "merge_output_format": "mkv",
            "final_ext": "mkv",
            "outtmpl": {
                "default": str(
                    self.output_dir
                    / "[%(extractor)s] {inp} - E%(episode_number)s [%(resolution)s, {codec}].%(ext)s".format(
                        inp=title, codec=hcodec
                    )
                )
            },
            "postprocessors": [],
            "retries": 10,
            "subtitlesformat": "srt" if self.srt else "ass/srt",
            "subtitleslangs": ["all"],
            "updatetime": False,
            "writesubtitles": True,
            "referer": "https://www.bilibili.tv/",
        }

        # Build postprocessors list in the correct order
        postprocessors = []
        postprocessors.append(
            {"already_have_subtitle": False, "key": "FFmpegEmbedSubtitle"}
        )
        postprocessors.append(
            {
                "add_chapters": False,
                "add_infojson": None,
                "add_metadata": False,
                "key": "FFmpegMetadata",
            }
        )
        postprocessors.append(
            {"key": "FFmpegConcat", "only_multi_video": True, "when": "playlist"}
        )

        ep_num = "0"

        ydl_opts["postprocessors"] = postprocessors
        if self.only_audio:
            ydl_opts["format"] = "ba"
            del ydl_opts["subtitlesformat"]
            del ydl_opts["subtitleslangs"]
            del ydl_opts["writesubtitles"]
        if self.ffmpeg_path:
            ydl_opts["ffmpeg_location"] = str(self.ffmpeg_path)
        if self.mkvmerge_path:
            ydl_opts["mkvmerge_path"] = str(self.mkvmerge_path)

        with YDL(ydl_opts) as ydl:  # type: ignore
            ydl.params["quiet"] = True
            ydl.params["verbose"] = False
            metadata = ydl.extract_info(episode_url, download=False)
            try:
                if metadata is None:
                    raise NameError()
                is_pv = metadata["title"].startswith("PV")  # type: ignore
                if is_pv and not self.download_pv:
                    raise NameError()
            except AttributeError:
                raise ReferenceError(
                    f"{episode_url} does not have preferred resolution of {self.resolution}"
                )
            except (TypeError, NameError):
                raise NameError(
                    f"{episode_url} is a PV. Explicitly enable the switch if you want to download it."
                )
            if "entries" in metadata:
                raise ReferenceError(
                    f"{episode_url} is a Playlist URL, not episode. To avoid unwanted err, please use other command"
                )
            ep_num = f"E{metadata.get('episode_number', 0):02d}" if metadata else ""
            if not metadata["title"].startswith("E"):  # type: ignore
                ep_num = metadata["title"].split(" - ")[0] if metadata else ep_num  # type: ignore
            if self.notification:
                push_notification(
                    title=str(title),
                    index=ep_num,
                )
            prn_info(
                f'Downloading "{title}" {ep_num} ({self.resolution}p, {"AVC" if self.is_avc else "HEVC"})'
            )
            ydl.params["outtmpl"]["default"] = (  # type: ignore
                "[%(extractor)s] {inp} - {ep} [%(resolution)s, {codec}].%(ext)s".format(  # type: ignore
                    inp=title,
                    ep=ep_num,
                    codec=hcodec,
                )
            )
            final_path = ydl.prepare_filename(metadata)
            ydl.params["quiet"] = not self.verbose
            ydl.params["verbose"] = self.verbose

            # Add subtitle reporter to display found subtitles
            if not self.only_audio:
                from bilidownloader.subtitles.subtitle_reporter import SubtitleReporter

                ydl.add_post_processor(SubtitleReporter(), when="before_dl")

            # Add ASS rescaler if conditions are met
            if not self.srt and not self.only_audio and not self.dont_rescale:
                if check_package("ass"):
                    from bilidownloader.subtitles.assresample import SSARescaler

                    ydl.add_post_processor(SSARescaler(), when="before_dl")

            # Add SRT to ASS converter if needed
            if not self.srt and not self.only_audio and not self.dont_convert:
                if check_package("ass"):
                    from bilidownloader.subtitles.srttoass import SRTToASSConverter

                    ydl.add_post_processor(SRTToASSConverter(), when="before_dl")
                else:
                    prn_error(
                        (
                            "`ass` package is not found inside the environment, "
                            "please reinstall `bilidownloader` by executing this "
                            "command to install the required package:"
                        )
                    )
                    prn_error(REINSTALL_ARGS)
                    prn_info("Reverting to use SRT")
                    self.srt = True
                    self.dont_rescale = False

            # Add SRT gap filler for direct SRT subtitles
            if self.srt and not self.only_audio:
                from bilidownloader.subtitles.srtgapfill import SRTGapFiller

                ydl.add_post_processor(SRTGapFiller(), when="before_dl")

            ydl.download([episode_url])

        metadata["btitle"] = title  # type: ignore

        return (Path(".") / final_path, metadata, language)
