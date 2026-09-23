"""
Metadata editor - handles MKV metadata operations
"""

import subprocess as sp
from io import BytesIO
from json import loads as jloads
from pathlib import Path
from typing import Any, ClassVar, cast

import requests as reqs
from PIL import Image

from bilidownloader.commons.filesystem import find_command
from bilidownloader.commons.ui import (
    _verbose,
    prn_cmd,
    prn_dbg,
    prn_done,
    prn_error,
    prn_info,
)
from bilidownloader.commons.utils import (
    AudioLanguage,
    SubtitleLanguage,
    langcode_to_str,
)
from bilidownloader.subtitles.post_processors import extract_lang_code


class MetadataEditor:
    """Handles MKV metadata editing operations"""

    # Bilibili subtitle code -> language tag written at mux time.
    # Tags are the canonical forms mkvmerge keeps in the file (it normalizes
    # e.g. zh-Hans/zh-Hant to chi and msa to may), so downstream matching is
    # exact. Hans/Hant share the chi tag and are told apart by mux order.
    SUBTITLE_MUX_LANGS: ClassVar[dict[str, str]] = {
        "en": "eng",
        "th": "tha",
        "vi": "vie",
        "id": "ind",
        "ms": "may",
        "zh-Hans": "chi",
        "zh-Hant": "chi",
        "ar": "ara",
    }

    def __init__(
        self,
        mkvpropedit_path: Path | None = None,
        mkvmerge_path: Path | None = None,
    ):
        self.mkvpropedit_path = mkvpropedit_path
        self.mkvmerge_path = mkvmerge_path

    @staticmethod
    def _empty_track_counts() -> dict[str, int]:
        return {"video": 0, "audio": 0, "text": 0}

    @classmethod
    def _parse_mediainfo_track_counts(cls, data: dict[str, Any]) -> dict[str, int]:
        """Extract comparable track counts from mediainfo JSON output."""
        counts = cls._empty_track_counts()
        media = cast(dict[str, Any], data.get("media", {}))
        tracks = cast(list[dict[str, Any]], media.get("track", []))
        for track in tracks:
            track_type = str(track.get("@type", "")).lower()
            if track_type == "video":
                counts["video"] += 1
            elif track_type == "audio":
                counts["audio"] += 1
            elif track_type == "text":
                counts["text"] += 1
        return counts

    @classmethod
    def _parse_mkvmerge_track_counts(cls, data: dict[str, Any]) -> dict[str, int]:
        """Extract comparable track counts from mkvmerge JSON output."""
        counts = cls._empty_track_counts()
        tracks = cast(list[dict[str, Any]], data.get("tracks", []))
        for track in tracks:
            track_type = str(track.get("type", "")).lower()
            if track_type == "video":
                counts["video"] += 1
            elif track_type == "audio":
                counts["audio"] += 1
            elif track_type == "subtitles":
                counts["text"] += 1
        return counts

    @staticmethod
    def _mediainfo_is_missing_tracks(
        mediainfo_counts: dict[str, int], mkvmerge_counts: dict[str, int]
    ) -> bool:
        """Return True when mediainfo reports fewer core tracks than mkvmerge."""
        return any(
            mediainfo_counts[track_type] < mkvmerge_counts[track_type]
            for track_type in ("video", "audio", "text")
        )

    def _read_mediainfo_track_counts(self, video_path: Path) -> dict[str, int] | None:
        """Read video/audio/text track counts from mediainfo."""
        mediainfo = find_command("mediainfo")
        if not mediainfo:
            prn_info("mediainfo is not found, skipping track sanity check")
            return None

        cmd = [str(mediainfo), "--Output=JSON", str(video_path)]
        prn_cmd(cmd)
        result = sp.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            prn_error(
                f"mediainfo failed to inspect {video_path.name}, attempting repair remux"
            )
            return self._empty_track_counts()

        try:
            data = jloads(result.stdout)
        except ValueError as err:
            prn_error(
                f"Failed to parse mediainfo output for {video_path.name}: {err}. "
                "Attempting repair remux."
            )
            return self._empty_track_counts()

        return self._parse_mediainfo_track_counts(cast(dict[str, Any], data))

    def _read_mkvmerge_track_counts(self, video_path: Path) -> dict[str, int]:
        """Read video/audio/text track counts from mkvmerge."""
        mkvmerge = self.mkvmerge_path or find_command("mkvmerge")
        if not mkvmerge:
            raise FileNotFoundError(
                "mkvmerge is not found in the system, try to install it first or check the path"
            )

        cmd = [str(mkvmerge), "-J", str(video_path)]
        prn_cmd(cmd)
        result = sp.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise ValueError(f"Failed to inspect track data for {video_path.name}")

        try:
            data = jloads(result.stdout)
        except ValueError as err:
            raise ValueError(
                f"Failed to parse mkvmerge output for {video_path.name}: {err}"
            ) from err

        return self._parse_mkvmerge_track_counts(cast(dict[str, Any], data))

    def _repair_tracks_with_mkvmerge(self, video_path: Path) -> Path:
        """Remux a file in place to repair track metadata issues."""
        mkvmerge = self.mkvmerge_path or find_command("mkvmerge")
        if not mkvmerge:
            raise FileNotFoundError(
                "mkvmerge is not found in the system, try to install it first or check the path"
            )

        temp_path = video_path.with_name(
            f"{video_path.stem}.sanity-remux{video_path.suffix}"
        )
        cmd = [str(mkvmerge), "--quiet", "-o", str(temp_path), str(video_path)]
        prn_info("Repairing MKV container so mediainfo can read all tracks")
        prn_cmd(cmd)
        try:
            sp.run(cmd, check=True)
            temp_path.replace(video_path)
        finally:
            if temp_path.exists():
                temp_path.unlink(True)

        return video_path

    def ensure_mediainfo_tracks(self, video_path: Path) -> Path:
        """Ensure mediainfo can see the same core tracks as mkvmerge."""
        if not video_path.exists():
            raise FileNotFoundError(
                f"Video file not found: {video_path}. Cannot verify track metadata."
            )

        mediainfo_counts = self._read_mediainfo_track_counts(video_path)
        if mediainfo_counts is None:
            return video_path

        mkvmerge_counts = self._read_mkvmerge_track_counts(video_path)
        if not self._mediainfo_is_missing_tracks(mediainfo_counts, mkvmerge_counts):
            prn_dbg(
                f"mediainfo track sanity passed for {video_path.name}: "
                f"{mediainfo_counts} vs {mkvmerge_counts}"
            )
            return video_path

        prn_error(
            f"mediainfo track mismatch for {video_path.name}: "
            f"{mediainfo_counts} vs {mkvmerge_counts}"
        )
        repaired_path = self._repair_tracks_with_mkvmerge(video_path)
        repaired_counts = self._read_mediainfo_track_counts(repaired_path)
        if repaired_counts is None:
            return repaired_path

        expected_counts = self._read_mkvmerge_track_counts(repaired_path)
        if self._mediainfo_is_missing_tracks(repaired_counts, expected_counts):
            raise ValueError(
                f"mediainfo still reports incomplete tracks for {video_path.name}: "
                f"{repaired_counts} vs {expected_counts}"
            )

        prn_done(f"Track sanity repair completed for {video_path.name}")
        return repaired_path

    def add_audio_language(
        self,
        video_path: Path,
        language: AudioLanguage,
    ) -> list[str]:
        """Add audio language to the video file"""
        prn_dbg(
            f"Preparing audio language metadata: '{language}' for {video_path.name}"
        )
        code = {
            "chi": "Chinese (中文)",
            "jpn": "Japanese (日本語)",
            "ind": "Indonesian (bahasa Indonesia)",
            "tha": "Thai (ไทย)",
            None: "Undetermined",
        }
        lang_title = code[language]
        language = language or "und"
        return [
            "--edit",
            "track:a1",
            "--set",
            f"language={language}",
            "--set",
            f"name={lang_title}",
        ]

    def set_default_subtitle(
        self,
        raw_data: dict[str, Any],
        video_path: Path,
        language: SubtitleLanguage | None = None,
    ) -> list[str]:
        """Flag the preferred subtitle track as default and name all tracks.

        Matches tracks by the language tags written at mux time
        (see SUBTITLE_MUX_LANGS), so no positional guessing is needed.
        """
        language = language or SubtitleLanguage.en
        want = self.SUBTITLE_MUX_LANGS.get(language.value, "eng")
        # zh-Hans and zh-Hant share the chi tag in the file. They mux in
        # sorted-filename order (Hans first), so disambiguate by occurrence
        # — but only when the full pair is verifiably present.
        want_chi_variant = (
            language.value if language.value in ("zh-Hans", "zh-Hant") else None
        )

        def fail(msg: str) -> list[str]:
            prn_dbg(msg)
            return []

        prn_dbg(f"Setting default subtitle to '{want}' for {video_path.name}")
        mkvmerge = self.mkvmerge_path or find_command("mkvmerge")
        if not mkvmerge:
            return fail(
                "mkvmerge is not found in the system, try to install it first or check the path"
            )

        mkvmerge_cmd = [str(mkvmerge), "-J", str(video_path)]
        prn_cmd(mkvmerge_cmd)
        result = sp.run(mkvmerge_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return fail("Failed to get subtitle track number")

        try:
            tracks = [
                track
                for track in jloads(result.stdout)["tracks"]
                if track["type"] == "subtitles"
            ]
        except Exception:
            return fail("Failed to parse subtitle track data")
        if not tracks:
            return fail("No subtitle tracks found in the video file")

        # Mux-time tag -> Bilibili code, to detect SRT-converted tracks.
        rev_langs = {tag: code for code, tag in self.SUBTITLE_MUX_LANGS.items()}
        available = (raw_data or {}).get("subtitles", {})
        pair_intact = (
            len(tracks) == len(available)
            and "zh-Hans" in available
            and "zh-Hant" in available
            and sum(1 for t in tracks if t["properties"].get("language") == "chi") == 2
        )

        default: tuple[str, str] | None = None
        others: list[tuple[str, str]] = []
        names: dict[str, str] = {}
        chi_seen = 0
        for track in tracks:
            num = str(track["id"] + 1)
            tag = track["properties"].get("language") or "und"
            if tag == "chi" and pair_intact:
                variant = "zh-Hans" if chi_seen == 0 else "zh-Hant"
                chi_seen += 1
            else:
                variant = rev_langs.get(tag, tag)
            sub_formats = available.get(variant, [])
            converted = (
                track["properties"].get("codec_id") == "S_TEXT/ASS"
                and sub_formats
                and not any(f.get("ext") == "ass" for f in sub_formats)
            )
            base = langcode_to_str(variant if pair_intact and tag == "chi" else tag)
            names[num] = f"{base} [Converted from SRT]" if converted else base
            is_wanted = tag == want and (
                tag != "chi" or not pair_intact or variant == want_chi_variant
            )
            if is_wanted and default is None:
                default = (num, tag)
            else:
                others.append((num, tag))

        if default is None:
            prn_error(
                f"Subtitle track for '{want}' not found, using the first subtitle track as default"
            )
            default = others.pop(0)

        args = [
            "--edit",
            f"track:{default[0]}",
            "--set",
            "flag-default=1",
            "--set",
            f"language={default[1]}",
            "--set",
            f"name={names[default[0]]}",
        ]
        for num, tag in others:
            args += [
                "--edit",
                f"track:{num}",
                "--set",
                "flag-default=0",
                "--set",
                f"language={tag}",
                "--set",
                f"name={names[num]}",
            ]
        args.append("--verbose" if _verbose else "--quiet")
        return args

    @staticmethod
    def resize_thumbnail_for_mkv(image_data: bytes) -> bytes:
        """Resize thumbnail to MKV maximum cover specifications (600x600)"""
        try:
            image = Image.open(BytesIO(image_data))

            if image.mode not in ("RGB", "RGBA"):
                if image.mode == "P":
                    image = image.convert("RGBA")
                else:
                    image = image.convert("RGB")

            original_width, original_height = image.size
            max_size = 600

            if original_height > max_size:
                new_height = max_size
                new_width = int((max_size * original_width) / original_height)
                image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

            output = BytesIO()

            if image.mode == "RGBA":
                image.save(output, format="PNG", optimize=True)
            else:
                if image.mode == "RGBA":
                    alpha = image.split()[3]
                    if alpha.getextrema()[0] == 255:
                        image = image.convert("RGB")

                image.save(output, format="PNG", optimize=True)

            return output.getvalue()

        except Exception as e:
            prn_error(f"Failed to resize thumbnail: {e}")
            return image_data

    def insert_thumbnail(self, raw_info: dict[str, Any]) -> list[str]:
        """Insert a thumbnail into the video file"""
        thumbnail = raw_info.get("thumbnail")
        if not thumbnail:
            return []

        prn_dbg("Downloading thumbnail and adding it to the video file")
        thumbnail_path = Path("thumbnail.png")

        with reqs.get(thumbnail) as resp:
            resized_thumbnail_data = self.resize_thumbnail_for_mkv(resp.content)
            thumbnail_path.write_bytes(resized_thumbnail_data)

        return [
            "--attachment-name",
            "cover_land.png",
            "--attachment-mime-type",
            "image/png",
            "--add-attachment",
            str(thumbnail_path),
        ]

    def delete_title_and_desc(self) -> list[str]:
        """Delete title and description from the video file"""
        return ["--delete", "title", "--tags", "global:"]

    def remux_tracks(
        self,
        video_track: Path,
        audio_track: Path | None,
        subtitle_tracks: list[Path],
        output_path: Path,
        default_sub_lang: str | None = None,
    ) -> Path:
        """Mux separate video/audio/subtitle tracks into one MKV with mkvmerge.

        This replaces the old ffmpeg-based merging (FFmpegMergerPP +
        FFmpegEmbedSubtitle). Tracks are passed through without re-encoding.
        Each subtitle file gets its `--language` from its filename so later
        metadata passes can match tracks exactly. Order in the output is
        video, audio, then subtitles sorted by filename.
        """
        mkvmerge = str(self.mkvmerge_path) if self.mkvmerge_path else "mkvmerge"
        if not video_track.exists():
            raise FileNotFoundError(f"Video track not found: {video_track}")
        if audio_track is not None and not audio_track.exists():
            raise FileNotFoundError(f"Audio track not found: {audio_track}")
        for sub in subtitle_tracks:
            if not sub.exists():
                raise FileNotFoundError(f"Subtitle track not found: {sub}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            output_path.unlink()

        cmd: list[str] = [mkvmerge, "-o", str(output_path)]
        cmd.append("--verbose" if _verbose else "--quiet")
        cmd.append(str(video_track))
        if audio_track is not None:
            cmd.append(str(audio_track))
        for sub in sorted(subtitle_tracks):
            if lang := self.SUBTITLE_MUX_LANGS.get(extract_lang_code(sub)):
                cmd += ["--language", f"0:{lang}"]
            cmd.append(str(sub))

        prn_info(f'Merging tracks into "{output_path.name}" with mkvmerge')
        prn_cmd(cmd)
        sp.run(cmd, check=True)
        if not output_path.exists():
            raise FileNotFoundError(f"mkvmerge failed to create {output_path}")
        if default_sub_lang:
            prn_dbg(f"Preferred default subtitle: {default_sub_lang}")
        return output_path

    def execute_mkvpropedit(
        self,
        video_path: Path,
        audio_args: list[str],
        sub_args: list[str],
        font_args: list[str],
        attachment_args: list[str],
        delete_metadata: bool = True,
    ) -> Path:
        """Execute mkvpropedit on the video file"""
        mkvpropedit = (
            str(self.mkvpropedit_path) if self.mkvpropedit_path else "mkvpropedit"
        )

        # Verify video file exists before processing
        if not video_path.exists():
            prn_error(f"Video file not found: {video_path}. Cannot edit metadata.")
            return video_path

        prn_info("Remuxing file with metadata and attachments")
        prn_dbg(f"Executing mkvpropedit on {video_path.name}")

        # Pass 1: Global metadata deletion
        if delete_metadata:
            delete_cmd = [
                mkvpropedit,
                str(video_path),
                *self.delete_title_and_desc(),
                "--verbose" if _verbose else "--quiet",
            ]
            prn_cmd(delete_cmd)
            sp.run(delete_cmd, check=True)

        # Pass 2: Track edits and attachments
        if audio_args or sub_args or font_args or attachment_args:
            edit_cmd = [
                mkvpropedit,
                str(video_path),
                *audio_args,
                *sub_args,
                *font_args,
                *attachment_args,
                "--verbose" if _verbose else "--quiet",
            ]
            prn_cmd(edit_cmd)
            sp.run(edit_cmd, check=True)

        # Pass 3: Add track statistics tags separately to avoid logic colliding
        stats_cmd = [
            mkvpropedit,
            str(video_path),
            "--add-track-statistics-tags",
            "--verbose" if _verbose else "--quiet",
        ]
        prn_cmd(stats_cmd)
        sp.run(
            stats_cmd,
            check=True,
        )
        prn_done("Remuxing completed")

        return self.ensure_mediainfo_tracks(video_path)
