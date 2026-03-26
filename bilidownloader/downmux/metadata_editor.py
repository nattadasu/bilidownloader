"""
Metadata editor - handles MKV metadata operations
"""

import subprocess as sp
from io import BytesIO
from json import loads as jloads
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, cast

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
from bilidownloader.commons.utils import SubtitleLanguage, langcode_to_str


class MetadataEditor:
    """Handles MKV metadata editing operations"""

    def __init__(
        self,
        mkvpropedit_path: Optional[Path] = None,
        mkvmerge_path: Optional[Path] = None,
    ):
        self.mkvpropedit_path = mkvpropedit_path
        self.mkvmerge_path = mkvmerge_path

    @staticmethod
    def _empty_track_counts() -> Dict[str, int]:
        return {"video": 0, "audio": 0, "text": 0}

    @classmethod
    def _parse_mediainfo_track_counts(cls, data: Dict[str, Any]) -> Dict[str, int]:
        """Extract comparable track counts from mediainfo JSON output."""
        counts = cls._empty_track_counts()
        media = cast(Dict[str, Any], data.get("media", {}))
        tracks = cast(List[Dict[str, Any]], media.get("track", []))
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
    def _parse_mkvmerge_track_counts(cls, data: Dict[str, Any]) -> Dict[str, int]:
        """Extract comparable track counts from mkvmerge JSON output."""
        counts = cls._empty_track_counts()
        tracks = cast(List[Dict[str, Any]], data.get("tracks", []))
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
        mediainfo_counts: Dict[str, int], mkvmerge_counts: Dict[str, int]
    ) -> bool:
        """Return True when mediainfo reports fewer core tracks than mkvmerge."""
        return any(
            mediainfo_counts[track_type] < mkvmerge_counts[track_type]
            for track_type in ("video", "audio", "text")
        )

    def _read_mediainfo_track_counts(
        self, video_path: Path
    ) -> Optional[Dict[str, int]]:
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

        return self._parse_mediainfo_track_counts(cast(Dict[str, Any], data))

    def _read_mkvmerge_track_counts(self, video_path: Path) -> Dict[str, int]:
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

        return self._parse_mkvmerge_track_counts(cast(Dict[str, Any], data))

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
        language: Optional[Literal["ind", "jpn", "chi", "tha", "und"]],
    ) -> List[str]:
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
        raw_data: Dict[str, Any],
        video_path: Path,
        language: Optional[SubtitleLanguage] = None,
    ) -> List[str]:
        """Set the default subtitle for the video file"""
        language = language or SubtitleLanguage.en
        lcodex = {
            "en": "eng",
            "id": "ind",
            "ms": "may",
            "th": "tha",
            "vi": "vie",
            "zh-Hans": "chi",
            "zh-Hant": "chi",
        }
        flang = lcodex.get(language.value, "eng")

        def fail(msg: str) -> List[str]:
            prn_dbg(msg)
            return []

        try:
            keys = list(raw_data.get("subtitles", {}).keys())
        except Exception:
            keys = []
        if not keys:
            return fail(
                "Failed to get subtitle index from yt-dlp. Does the video have subtitles?"
            )

        prn_dbg(f"Setting default subtitle to '{flang}' for {video_path.name}")
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

        set_track: Optional[tuple[str, str]] = None
        unset_track: List[tuple[str, str]] = []

        try:
            data = jloads(result.stdout)
            for track in data["tracks"]:
                if track["type"] == "subtitles":
                    track_lang = track["properties"]["language"]
                    if track_lang == "zh" or track_lang == "chi":
                        track_lang = keys[track["id"] - 2]
                    if track_lang == flang:
                        set_track = (str(track["id"] + 1), track_lang)
                    else:
                        unset_track.append((str(track["id"] + 1), track_lang))
        except Exception:
            return fail("Failed to get subtitle track number")

        if not set_track and len(unset_track) > 0:
            prn_error(
                f"Subtitle track for '{flang}' not found, using the first subtitle track as default"
            )
            set_track = unset_track.pop(0)

        if set_track:
            unset_: List[str] = []
            for track in unset_track:
                unset_ += [
                    "--edit",
                    f"track:{track[0]}",
                    "--set",
                    "flag-default=0",
                    "--set",
                    f"language={track[1]}",
                    "--set",
                    f"name={langcode_to_str(track[1])}",
                ]
            return [
                "--edit",
                f"track:{set_track[0]}",
                "--set",
                "flag-default=1",
                "--set",
                f"language={set_track[1]}",
                "--set",
                f"name={langcode_to_str(set_track[1])}",
                *unset_,
                *["--verbose" if _verbose else "--quiet"],
            ]
        else:
            return fail("Failed to set subtitle track as default")

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

    def insert_thumbnail(self, raw_info: Dict[str, Any]) -> List[str]:
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

    def delete_title_and_desc(self) -> List[str]:
        """Delete title and description from the video file"""
        return ["--delete", "title", "--tags", "global:"]

    def execute_mkvpropedit(
        self,
        video_path: Path,
        audio_args: List[str],
        sub_args: List[str],
        font_args: List[str],
        attachment_args: List[str],
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
