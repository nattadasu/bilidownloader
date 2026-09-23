"""
Video downloader - handles yt-dlp download operations.

Tracks are downloaded separately (video with subtitles, then audio) and
remuxed into a final MKV with mkvmerge. Progress via rich, binary units.
"""

import shlex
from html import unescape
from pathlib import Path
from re import IGNORECASE
from re import search as rsearch
from re import sub as rsub
from typing import Any

from fake_useragent import UserAgent
from langcodes import Language
from yt_dlp import YoutubeDL as YDL

from bilidownloader.apis.api import BiliHtml
from bilidownloader.commons.alias import SERIES_ALIASES
from bilidownloader.commons.progress import YtDlpProgress
from bilidownloader.commons.ui import (
    prn_cmd,
    prn_dbg,
    prn_error,
    prn_info,
    push_notification,
)
from bilidownloader.commons.utils import (
    Chapter,
    DubLanguage,
    RateLimitError,
    SubtitleLanguage,
    sanitize_filename,
)

ua = UserAgent()
uagent = ua.chrome

_SUBTITLE_EXTS = frozenset({".ass", ".srt", ".vtt"})
"""Subtitle extensions; their progress tasks are transient (see progress.py)."""


def _normalize_tag(code: str) -> str:
    """Normalize language code via langcodes to a comparable tag (lowercase)."""
    try:
        return Language.get(code.strip()).to_tag().lower()
    except Exception:
        return code.strip().lower()


def _parse_ensure_subs(raw: list[str] | None) -> list[str] | None:
    """Flatten ensure-sub input (support repeat and comma-separated)."""
    if not raw:
        return None
    flat: list[str] = []
    for entry in raw:
        if entry is None:
            continue
        # entry might be comma-separated
        for part in str(entry).split(","):
            part = part.strip()
            if part:
                flat.append(part)
    # deduplicate preserving order (case-insensitive)
    seen: set[str] = set()
    deduped: list[str] = []
    for code in flat:
        lower = code.lower()
        if lower not in seen:
            seen.add(lower)
            deduped.append(code)
    return deduped if deduped else None


def _has_required_subtitle(
    subtitles: dict[str, list[Any]], ensure_subs: list[str]
) -> bool:
    """
    Return True if at least one of ensure_subs matches a key in subtitles.

    Matching is done with ISO 639-1/3 awareness via langcodes:
    - Exact normalized tag match wins (e.g., eng -> en, zh-Hans -> zh-hans).
    - If requested code has no script/region (no '-' or '_'), fall back to
      base language comparison (so 'en' matches 'en', 'eng' matches 'en',
      'zh' matches 'zh-Hans', etc.).
    """
    if not subtitles or not ensure_subs:
        return False

    avail_tags = {k: _normalize_tag(k) for k in subtitles}
    avail_langs: dict[str, str | None] = {}
    for k in subtitles:
        try:
            avail_langs[k] = Language.get(k).language
        except Exception:
            avail_langs[k] = None

    for req in ensure_subs:
        req_tag = _normalize_tag(req)
        if req_tag in avail_tags.values():
            return True
        # Fall back to base-language comparison when no script/region given
        # (so 'en' matches 'en', 'eng' matches 'en', 'zh' matches 'zh-Hans').
        if "-" in req or "_" in req:
            continue
        try:
            req_base = (Language.get(req).language or "").lower()
        except Exception:
            req_base = ""
        req_base = req_base or req_tag.split("-")[0].split("_")[0]
        for avail_tag, avail_lang in zip(
            avail_tags.values(), avail_langs.values(), strict=True
        ):
            if req_base and req_base in (
                (avail_lang or "").lower(),
                avail_tag.split("-")[0].split("_")[0],
            ):
                return True
    return False


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

        # yt-dlp surfaces external command lines; show them as CMD.
        for prefix in ("ffmpeg command line: ", "mkvmerge command line: "):
            if msg.startswith(prefix):
                cmd_line = msg.replace(prefix, "")
                try:
                    cmd_parts = shlex.split(cmd_line)
                    prn_cmd(cmd_parts)
                except ValueError:
                    prn_dbg(msg)
                return
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
    """Downloads video/audio/subtitle tracks separately and remuxes with mkvmerge."""

    def __init__(
        self,
        cookie: Path,
        resolution: int = 1080,
        is_avc: bool = False,
        download_pv: bool = False,
        ffmpeg_path: Path | None = None,
        mkvmerge_path: Path | None = None,
        notification: bool = False,
        srt: bool = False,
        dont_rescale: bool = False,
        dont_convert: bool = False,
        no_mods: bool = False,
        subtitle_lang: SubtitleLanguage = SubtitleLanguage.en,
        only_audio: bool = False,
        output_dir: Path | None = None,
        verbose: bool = False,
        skip_no_subtitle: bool = False,
        ensure_sub: list[str] | None = None,
        proxy: str | None = None,
        mark_downloaded: bool = False,
    ):
        self.cookie = cookie
        self.resolution = resolution
        self.is_avc = is_avc
        self.download_pv = download_pv
        # Deprecated compat param; never passed to yt-dlp.
        self.ffmpeg_path = ffmpeg_path
        if ffmpeg_path is not None:
            prn_dbg("ffmpeg_path is deprecated and ignored; remuxing uses mkvmerge")
        self.mkvmerge_path = mkvmerge_path
        self.notification = notification
        self.srt = srt
        self.dont_rescale = dont_rescale
        self.dont_convert = dont_convert
        self.no_mods = no_mods
        self.subtitle_lang = subtitle_lang
        self.only_audio = only_audio
        self.output_dir = output_dir or Path.cwd()
        self.verbose = verbose
        self.skip_no_subtitle = skip_no_subtitle
        self.ensure_sub = _parse_ensure_subs(ensure_sub)
        self.proxy = proxy
        self.mark_downloaded = mark_downloaded
        self._progress = YtDlpProgress(
            describe=self._get_download_description, transient_exts=_SUBTITLE_EXTS
        )

    @staticmethod
    def _get_download_description(
        filename: str, info_dict: dict[str, Any] | None = None
    ) -> str:
        """Short label for a track, e.g. 'Video (144P)'."""
        import re

        from bilidownloader.commons.utils import langcode_to_str

        ext = Path(filename).suffix.lower()
        if ext in _SUBTITLE_EXTS:
            lang_match = re.search(
                r"\.([a-z]{2}(?:-[A-Z][a-z]+)?)\.(?:ass|srt|vtt)$", filename
            )
            if lang_match:
                return f"{langcode_to_str(lang_match.group(1))} sub"
            return "Sub"

        if Path(filename).stem.endswith(".audio"):
            return "Audio"

        info = info_dict or {}
        if note := info.get("format_note") or info.get("resolution", ""):
            return f"Video ({note})"
        return "Video"

    def _progress_hook(self, d: dict[str, Any]) -> None:
        """Progress hook for yt-dlp, backed by rich with binary byte units."""
        self._progress.hook(d)
        if d["status"] == "error":
            prn_error("Download error occurred")

    def _build_format_selectors(self) -> tuple[str, str, str]:
        """Build (combined, video-only, audio-only) format selectors."""
        codec = "avc1" if self.is_avc else "hev1"

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

        # Note: Using *= for substring matching instead of ~= to avoid regex issues
        if self.resolution == 1080:
            video_selector = (
                f"bv*[vcodec^={codec}][format_note*=HD]/"
                f"bv*[vcodec^={codec}][height={self.resolution}]/"
                f"bv*[vcodec^={codec}][format_note*={quality_label}]"
            )
        else:
            video_selector = (
                f"bv*[vcodec^={codec}][height={self.resolution}]/"
                f"bv*[vcodec^={codec}][format_note*={quality_label}]"
            )
        audio_selector = "ba"
        combined_selector = f"{video_selector}+{audio_selector}"
        return combined_selector, video_selector, audio_selector

    def _base_ydl_opts(self) -> dict[str, Any]:
        """Common yt-dlp options shared by all track downloads."""
        opts: dict[str, Any] = {
            "cookiefile": str(self.cookie),
            "extract_flat": "discard_in_playlist",
            "fragment_retries": 10,
            "ignoreerrors": "only_download",
            "noprogress": True,
            "progress_hooks": [self._progress_hook],
            "retries": 10,
            "updatetime": False,
            "referer": "https://www.bilibili.tv/",
            "logger": YtDlpLogger(),
            # No merging here; remuxing happens in download_episode.
            "keepvideo": True,
        }
        if self.proxy:
            opts["proxy"] = self.proxy
        return opts

    def _track_opts(self, outtmpl: str | None = None, **extra: Any) -> dict[str, Any]:
        """Options for one track download pass (video or audio)."""
        opts = self._base_ydl_opts()
        if outtmpl is not None:
            opts["outtmpl"] = {"default": outtmpl}
        opts.update(
            {
                "quiet": not self.verbose,
                "verbose": self.verbose,
                **extra,
            }
        )
        return opts

    def _attach_subtitle_processors(self, ydl: YDL, is_chinese: bool) -> None:
        """Attach subtitle reporter + processing PPs to a yt-dlp instance."""
        if self.only_audio:
            return
        from bilidownloader.subtitles import post_processors as pp
        from bilidownloader.subtitles.subtitle_reporter import SubtitleReporter

        def add(proc: Any) -> None:
            ydl.add_post_processor(proc, when="before_dl")

        add(SubtitleReporter())
        if self.srt:
            add(pp.SRTModifier(no_mods=self.no_mods))
            add(pp.SRTGapFiller(is_chinese=is_chinese))
            return
        if not self.dont_convert:
            add(pp.SRTToASSConverter(is_chinese=is_chinese, no_mods=self.no_mods))
        add(pp.ASSModifier(no_mods=self.no_mods))
        add(pp.ASSGapFiller(is_chinese=is_chinese))
        if not self.dont_rescale:
            add(pp.SSARescaler())
        add(pp.FontCollector())

    def get_video_info(
        self, episode_url: str, simulate: bool = True
    ) -> Any | dict[str, Any] | None:
        """Get video information from yt-dlp"""
        prn_dbg(f"Extracting video info from {episode_url} (simulate={simulate})")
        ydl_opts = {
            "cookiefile": str(self.cookie),
            "extract_flat": "in_playlist",
            "fragment_retries": 10,
            "ignoreerrors": "only_download",
            "noprogress": True,
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
        with YDL(ydl_opts) as ydl:  # type: ignore
            return ydl.extract_info(episode_url, download=False)

    @staticmethod
    def get_episode_chapters(raw_info: dict[str, Any]) -> list[Chapter]:
        """Get chapters from video metadata"""
        try:
            return [Chapter(**chs) for chs in raw_info["chapters"]]
        except Exception:
            return []

    def _files_with_prefix(self, prefix: str) -> list[Path]:
        """Files in output_dir whose name starts with prefix (literal match).

        Literal matching is required because base names contain brackets
        (e.g. "[BiliIntl] ...") that glob would read as character classes.
        """
        return sorted(
            p
            for p in self.output_dir.iterdir()
            if p.is_file() and p.name.startswith(prefix)
        )

    def _find_track(self, prefix: str) -> Path | None:
        """Find a downloaded video/audio track by filename prefix."""
        matches = self._files_with_prefix(prefix)
        for match in matches:
            if match.suffix not in (".part", ".tmp", ".ytdl"):
                return match
        return matches[0] if matches else None

    def _find_subtitle_tracks(self, base_stem: str) -> list[Path]:
        """Find downloaded subtitle files for a base name."""
        return [
            p
            for p in self._files_with_prefix(base_stem + ".")
            if p.suffix.lower() in (".ass", ".srt")
        ]

    def _consolidate_video_pass_subtitles(self, base_stem: str) -> None:
        """Rename `<base>.video.<lang>.ass/srt` to `<base>.<lang>.ass/srt`.

        Subtitles ride on the video pass, so yt-dlp names them after the
        video track. Strip the `.video` infix so the remux lookup finds them.
        """
        infix = f"{base_stem}.video."
        for sub in self._files_with_prefix(infix):
            if sub.suffix.lower() not in (".ass", ".srt"):
                continue
            target = self.output_dir / f"{base_stem}.{sub.name[len(infix) :]}"
            try:
                sub.replace(target)
            except OSError as err:
                prn_dbg(f"Failed to rename {sub.name}: {err}")

    def download_episode(
        self,
        episode_url: str,
    ) -> tuple[Path, Any, DubLanguage | None]:
        """Download episode tracks separately, then remux with mkvmerge.

        Returns (final_path, metadata, audio_language). Intermediate
        video/audio/subtitle files are removed after a successful remux.
        """
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
        language: DubLanguage | None = None
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

        hcodec = "AVC" if self.is_avc else "HEVC"
        combined_selector, video_selector, audio_selector = (
            self._build_format_selectors()
        )

        # Check for subtitles if skip_no_subtitle or ensure_sub is set
        if (self.skip_no_subtitle or self.ensure_sub) and not self.only_audio:
            metadata_for_sub_check = self.get_video_info(episode_url, simulate=True)
            subtitles_dict = (
                metadata_for_sub_check.get("subtitles")
                if metadata_for_sub_check
                else None
            )
            if self.skip_no_subtitle and not subtitles_dict:
                prn_info(
                    f"Skipping {episode_url}: No subtitles found and --skip-no-subtitle is enabled."
                )
                return None, None, None  # Indicate skipped download
            if self.ensure_sub and (
                not subtitles_dict
                or not _has_required_subtitle(subtitles_dict, self.ensure_sub)
            ):
                available = (
                    ", ".join(sorted(subtitles_dict.keys()))
                    if subtitles_dict
                    else "none"
                )
                prn_info(
                    f"Skipping {episode_url}: None of the required subtitles "
                    f"({', '.join(self.ensure_sub)}) found. Available: {available} "
                    f"and --ensure-sub is enabled."
                )
                return None, None, None

        # Probe metadata without downloading or merging.
        probe_opts = self._track_opts(
            format=combined_selector,
            simulate=True,
            # Needed so the extractor populates `subtitles`: yt-dlp skips
            # subtitle extraction entirely without writesubtitles/listsubtitles.
            writesubtitles=True,
            subtitleslangs=["all"],
        )
        with YDL(probe_opts) as ydl:  # type: ignore
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
        except TypeError, NameError:
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

        # Deterministic base name, so split tracks are findable after download.
        extractor_name = (
            metadata.get("extractor_key") or metadata.get("extractor") or "BiliIntl"
        )
        video_fmt = next(
            (
                fmt
                for fmt in metadata.get("requested_formats", [])
                if fmt.get("vcodec") != "none" and fmt.get("width")
            ),
            {},
        )
        if video_fmt:
            res_str = f"{video_fmt.get('width')}x{video_fmt.get('height', '?')}"
        else:
            res_str = str(metadata.get("resolution", f"{self.resolution}p"))
        base_stem = f"[{extractor_name}] {title} - {ep_num} [{res_str}, {hcodec}]"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        final_path = self.output_dir / f"{base_stem}.mkv"
        video_outtmpl = str(self.output_dir / f"{base_stem}.video.%(ext)s")
        audio_outtmpl = str(self.output_dir / f"{base_stem}.audio.%(ext)s")

        prn_dbg(f"Starting track downloads with yt-dlp (verbose={self.verbose})")
        if self.mkvmerge_path:
            prn_dbg(f"mkvmerge path: {self.mkvmerge_path}")

        if self.mark_downloaded:
            prn_info("Mark-downloaded mode: Skipping actual download")
            prn_dbg(f"Would download: {final_path}")
            metadata["btitle"] = title  # type: ignore
            return (final_path, metadata, language)

        is_chinese = language == "chi"

        try:
            if self.only_audio:
                with YDL(self._track_opts(audio_outtmpl, format=audio_selector)) as ydl:  # type: ignore
                    ydl.download([episode_url])
                audio_track = self._find_track(f"{base_stem}.audio.")
                if audio_track is None:
                    raise FileNotFoundError(
                        f"Audio track not found for {base_stem} after download"
                    )
                # Audio-only: the downloaded track is the final file
                metadata["btitle"] = title  # type: ignore
                return (audio_track, metadata, language)

            # Subtitles ride the video pass; before_dl PPs run after they land.
            video_opts = self._track_opts(
                video_outtmpl,
                format=video_selector,
                writesubtitles=True,
                subtitleslangs=["all"],
                subtitlesformat="srt" if self.srt else "ass/srt",
            )
            with YDL(video_opts) as ydl:  # type: ignore
                self._attach_subtitle_processors(ydl, is_chinese=is_chinese)
                ydl.download([episode_url])
            self._consolidate_video_pass_subtitles(base_stem)

            with YDL(self._track_opts(audio_outtmpl, format=audio_selector)) as ydl:  # type: ignore
                ydl.download([episode_url])

            video_track = self._find_track(f"{base_stem}.video.")
            audio_track = self._find_track(f"{base_stem}.audio.")
            if video_track is None:
                raise FileNotFoundError(
                    f"Video track not found for {base_stem} after download"
                )
            if audio_track is None:
                raise FileNotFoundError(
                    f"Audio track not found for {base_stem} after download"
                )
            subtitle_tracks = [
                sub
                for sub in self._find_subtitle_tracks(base_stem)
                if sub not in (video_track, audio_track)
            ]

            # Remux video + audio + subtitles with mkvmerge.
            from bilidownloader.downmux.metadata_editor import MetadataEditor

            MetadataEditor(mkvmerge_path=self.mkvmerge_path).remux_tracks(
                video_track=video_track,
                audio_track=audio_track,
                subtitle_tracks=subtitle_tracks,
                output_path=final_path,
            )

            for intermediate in (video_track, audio_track, *subtitle_tracks):
                try:
                    intermediate.unlink(missing_ok=True)
                except OSError as err:
                    prn_dbg(f"Failed to remove intermediate {intermediate.name}: {err}")
        finally:
            self._progress.close()

        metadata["btitle"] = title  # type: ignore
        return (final_path, metadata, language)
