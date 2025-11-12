"""
Metadata editor - handles MKV metadata operations
"""

import subprocess as sp
from io import BytesIO
from json import loads as jloads
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import requests as reqs
from PIL import Image

from bilidownloader.commons.filesystem import find_command
from bilidownloader.commons.ui import prn_dbg, prn_done, prn_error, prn_info
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

    def add_audio_language(
        self,
        video_path: Path,
        language: Optional[Literal["ind", "jpn", "chi", "tha", "und"]],
    ) -> List[str]:
        """Add audio language to the video file"""
        prn_dbg(
            f"Adding audio language '{language}' to {video_path.name} using mkvpropedit"
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
            prn_error(msg)
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

        result = sp.run(
            [mkvmerge, "-J", str(video_path)], capture_output=True, text=True
        )

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

    def execute_mkvpropedit(
        self,
        video_path: Path,
        audio_args: List[str],
        sub_args: List[str],
        font_args: List[str],
        attachment_args: List[str],
    ) -> Path:
        """Execute mkvpropedit on the video file"""
        mkvpropedit = (
            str(self.mkvpropedit_path) if self.mkvpropedit_path else "mkvpropedit"
        )
        if not audio_args and not sub_args:
            return video_path

        prn_info("Adding metadata")
        prn_dbg(f"Executing mkvpropedit on {video_path.name}")
        sp.run(
            [
                mkvpropedit,
                str(video_path),
                *audio_args,
                *sub_args,
                *font_args,
                *attachment_args,
                "--quiet",
                "--add-track-statistics-tags",
            ],
            check=True,
        )
        prn_done("Metadata added")

        return video_path
