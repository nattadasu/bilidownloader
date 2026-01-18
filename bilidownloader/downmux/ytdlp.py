"""
Video downloader - handles yt-dlp download operations
"""

import shlex
import sys
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
from bilidownloader.commons.ui import (
    prn_cmd,
    prn_dbg,
    prn_error,
    prn_info,
    push_notification,
)
from bilidownloader.commons.utils import (
    Chapter,
    RateLimitError,
    SubtitleLanguage,
    check_package,
    sanitize_filename,
)

ua = UserAgent()
uagent = ua.chrome


class YtDlpLogger:
    def debug(self, msg):
        if "412" in msg and "Precondition Failed" in msg:
            raise RateLimitError(
                "Bilibili rate limit reached (412 Precondition Failed)"
            )

        # Remove generic scopes from start of message
        # This handles [debug], [info], [download], [BiliIntl], etc.
        # But preserves [BiliIntl] if it appears later (e.g. in filename)
        msg = rsub(r"^\[[^]]+\]\s", "", msg)

        # Check if this is an ffmpeg command line and format it as CMD
        if msg.startswith("ffmpeg command line: "):
            cmd_line = msg.replace("ffmpeg command line: ", "")
            # Parse the command line into a list for prn_cmd
            try:
                cmd_parts = shlex.split(cmd_line)
                prn_cmd(cmd_parts)
            except ValueError:
                # Fallback if parsing fails
                prn_dbg(msg)
        else:
            prn_dbg(msg)

    def warning(self, msg):
        if "412" in msg and "Precondition Failed" in msg:
            raise RateLimitError(
                "Bilibili rate limit reached (412 Precondition Failed)"
            )
        prn_info(msg)

    def error(self, msg):
        if "412" in msg and "Precondition Failed" in msg:
            raise RateLimitError(
                "Bilibili rate limit reached (412 Precondition Failed)"
            )
        prn_error(msg)


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
        skip_no_subtitle: bool = False,
        proxy: Optional[str] = None,
        simulate: bool = False,
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
        self.skip_no_subtitle = skip_no_subtitle
        self.proxy = proxy
        self.simulate = simulate
        self._progress_bars = {}

    @staticmethod
    def _get_download_description(
        filename: str, info_dict: Optional[Dict[str, Any]] = None
    ) -> str:
        """Generate a descriptive title for the download based on filename and metadata"""
        import re

        from bilidownloader.commons.utils import langcode_to_str

        path = Path(filename)
        stem = path.stem
        ext = path.suffix.lower()

        # Check if it's a subtitle file
        if ext in [".ass", ".srt", ".vtt"]:
            # Extract language code from filename (e.g., "video.en.ass" -> "en")
            lang_match = re.search(
                r"\.([a-z]{2}(?:-[A-Z][a-z]+)?)\.(?:ass|srt|vtt)$", filename
            )
            if lang_match:
                lang_code = lang_match.group(1)
                lang_name = langcode_to_str(lang_code)
                format_name = ext[1:].upper()  # .ass -> ASS
                return f"{lang_name} {format_name} subtitle"
            else:
                return f"{ext[1:].upper()} subtitle"

        # Check if we have info_dict with format info
        if info_dict:
            # Check for video/audio based on vcodec and acodec
            vcodec = info_dict.get("vcodec", "none")
            acodec = info_dict.get("acodec", "none")

            if vcodec != "none" and acodec == "none":
                # Video only
                resolution = info_dict.get("resolution", "")
                format_note = info_dict.get("format_note", "")
                if format_note:
                    return f"Video track ({format_note})"
                elif resolution:
                    return f"Video track ({resolution})"
                else:
                    return "Video track"
            elif acodec != "none" and vcodec == "none":
                # Audio only
                return "Audio track"

        # Fallback: check filename pattern for .fN.mp4
        if ".f" in stem and ext in [".mp4", ".m4a", ".webm"]:
            # Extract format number (e.g., "video.f2.mp4" -> "2")
            fragment_match = re.search(r"\.f(\d+)$", stem)
            if fragment_match:
                format_id = fragment_match.group(1)
                # BiliBili typically uses lower IDs for audio, higher for video
                # Based on the format list: 0-2 are audio, 3+ are video
                try:
                    fid = int(format_id)
                    if fid <= 2:
                        return "Audio track"
                    else:
                        return "Video track"
                except ValueError:
                    pass

        # Fallback to truncated filename
        return stem[:35]

    def _progress_hook(self, d: Dict[str, Any]) -> None:
        """Progress hook for yt-dlp to display download status with alive-progress"""
        if d["status"] == "downloading":
            filename = d.get("filename", "")

            try:
                from alive_progress import alive_bar
            except ImportError:
                # Fallback without alive-progress
                return

            # Get or create progress bar for this file
            if filename not in self._progress_bars:
                total = d.get("total_bytes") or d.get("total_bytes_estimate")

                if total and total > 0:
                    # Pass info_dict if available in the download dict
                    info_dict = d.get("info_dict")
                    description = self._get_download_description(filename, info_dict)

                    # Detect if running in a terminal (like rich does)
                    is_terminal = sys.stdout.isatty()

                    # Only use ANSI color codes if in a terminal
                    if is_terminal:
                        title = (
                            f"\033[46m\033[30m INFO \033[0m Downloading {description}"
                        )
                    else:
                        title = f" INFO  Downloading {description}"

                    bar = alive_bar(
                        total,
                        title=title,
                        unit="B",
                        scale="IEC",
                        receipt=True,
                        ctrl_c=True,
                    )
                    bar_context = bar.__enter__()
                    self._progress_bars[filename] = {
                        "bar": bar,
                        "context": bar_context,
                        "last_downloaded": 0,
                    }

            # Update progress bar
            if filename in self._progress_bars:
                bar_info = self._progress_bars[filename]
                downloaded = d.get("downloaded_bytes", 0)

                if downloaded > bar_info["last_downloaded"]:
                    increment = downloaded - bar_info["last_downloaded"]
                    bar_info["context"](increment)
                    bar_info["last_downloaded"] = downloaded

        elif d["status"] == "finished":
            filename = d.get("filename", "")

            # Close progress bar for this file
            if filename in self._progress_bars:
                try:
                    self._progress_bars[filename]["bar"].__exit__(None, None, None)
                except Exception:
                    pass
                del self._progress_bars[filename]

        elif d["status"] == "error":
            filename = d.get("filename", "")

            # Close progress bar on error
            if filename in self._progress_bars:
                try:
                    self._progress_bars[filename]["bar"].__exit__(None, None, None)
                except Exception:
                    pass
                del self._progress_bars[filename]

            prn_error("Download error occurred")

    def get_video_info(
        self, episode_url: str, simulate: bool = True
    ) -> Union[Any, Dict[str, Any], None]:
        """Get video information from yt-dlp"""
        prn_dbg(f"Extracting video info from {episode_url} (simulate={simulate})")
        ydl_opts = {
            "cookiefile": str(self.cookie),
            "extract_flat": "in_playlist",
            "fragment_retries": 10,
            "ignoreerrors": "only_download",
            "noprogress": True,
            "postprocessors": [
                {"key": "FFmpegConcat", "only_multi_video": True, "when": "playlist"}
            ],
            "retries": 10,
            "simulate": simulate,
            "verbose": self.verbose,
            "quiet": not self.verbose,
            "referer": "https://www.bilibili.tv/",
            "writesubtitles": True,
            "allsubtitles": True,
            "logger": YtDlpLogger(),
        }
        if self.proxy:
            ydl_opts["proxy"] = self.proxy
        if self.ffmpeg_path:
            ydl_opts["ffmpeg_location"] = str(self.ffmpeg_path)
            prn_dbg(f"Using ffmpeg at: {self.ffmpeg_path}")
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
        html = BiliHtml(cookie_path=self.cookie, user_agent=uagent, proxy=self.proxy)
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

        # Map resolution to BiliBili's quality labels (format_note field)
        # This handles non-16:9 aspect ratios correctly
        quality_map = {
            144: "144P",
            240: "240P",
            360: "360P",
            480: "480P",
            720: "720P",
            1080: "1080P",
            2160: "Enhanced bitrate",  # 4K content
        }
        quality_label = quality_map.get(self.resolution, f"{self.resolution}P")

        # Build format selector with fallbacks:
        # 1. Try exact height match (for standard 16:9 content)
        # 2. For 1080P, prefer HD variant first, then standard
        # 3. Fall back to format_note label (handles non-16:9 aspect ratios)
        # Note: Using *= for substring matching instead of ~= to avoid regex issues
        if self.resolution == 1080:
            format_selector = (
                f"bv*[vcodec^={codec}][format_note*=HD]+ba/"
                f"bv*[vcodec^={codec}][height={self.resolution}]+ba/"
                f"bv*[vcodec^={codec}][format_note*={quality_label}]+ba"
            )
        else:
            format_selector = (
                f"bv*[vcodec^={codec}][height={self.resolution}]+ba/"
                f"bv*[vcodec^={codec}][format_note*={quality_label}]+ba"
            )

        ydl_opts = {
            "cookiefile": str(self.cookie),
            "extract_flat": "discard_in_playlist",
            "force_print": {"after_move": ["filepath"]},
            "format": format_selector,
            "fragment_retries": 10,
            "ignoreerrors": "only_download",
            "merge_output_format": "mkv",
            "final_ext": "mkv",
            "noprogress": True,
            "outtmpl": {
                "default": str(
                    self.output_dir
                    / "[%(extractor)s] {inp} - E%(episode_number)s [%(resolution)s, {codec}].%(ext)s".format(
                        inp=title, codec=hcodec
                    )
                )
            },
            "postprocessors": [],
            "progress_hooks": [self._progress_hook],
            "retries": 10,
            "subtitlesformat": "srt" if self.srt else "ass/srt",
            "subtitleslangs": ["all"],
            "updatetime": False,
            "writesubtitles": True,
            "referer": "https://www.bilibili.tv/",
            "logger": YtDlpLogger(),
        }
        if self.proxy:
            ydl_opts["proxy"] = self.proxy

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

        # Check for subtitles if skip_no_subtitle is True
        if self.skip_no_subtitle and not self.only_audio:
            # Use get_video_info to simulate and get metadata with subtitle info
            metadata_for_sub_check = self.get_video_info(episode_url, simulate=True)
            if not metadata_for_sub_check or not metadata_for_sub_check.get(
                "subtitles"
            ):
                prn_info(
                    f"Skipping {episode_url}: No subtitles found and --skip-no-subtitle is enabled."
                )
                return None, None, None  # Indicate skipped download

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

            # Show selected format information
            if metadata and "requested_formats" in metadata:
                formats = metadata["requested_formats"]
                for fmt in formats:
                    if fmt.get("vcodec") != "none":
                        # Video stream
                        vcodec = fmt.get("vcodec", "unknown")
                        resolution = f"{fmt.get('width', '?')}x{fmt.get('height', '?')}"
                        prn_info(
                            f"  Video: {vcodec} @ {resolution} ({fmt.get('format_note', 'unknown quality')})"
                        )
                    if fmt.get("acodec") != "none":
                        # Audio stream
                        acodec = fmt.get("acodec", "unknown")
                        prn_info(f"  Audio: {acodec}")

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

            prn_dbg(f"Starting download with yt-dlp (verbose={self.verbose})")
            if self.ffmpeg_path:
                prn_dbg(f"FFmpeg location: {self.ffmpeg_path}")
            if self.mkvmerge_path:
                prn_dbg(f"mkvmerge path: {self.mkvmerge_path}")

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

            if self.simulate:
                prn_info("Simulate mode: Skipping actual download")
                prn_dbg(f"Would download: {final_path}")
            else:
                ydl.download([episode_url])

        metadata["btitle"] = title  # type: ignore

        return (Path(".") / final_path, metadata, language)
