"""Thin wrapper around yt-dlp. No Qt in here, so it is easy to test and reuse."""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from yt_dlp import YoutubeDL
from yt_dlp.postprocessor import FFmpegPostProcessor, get_postprocessor
from yt_dlp.utils import DownloadCancelled

from .library import Library

# label -> (audio codec, yt-dlp format selector)
FORMATS = {
    "m4a (AAC) - widest compatibility": ("m4a", "bestaudio[ext=m4a]/bestaudio/best"),
    "opus - best quality for the size": ("opus", "bestaudio[ext=webm]/bestaudio/best"),
    "mp3 - works everywhere": ("mp3", "bestaudio/best"),
}
DEFAULT_FORMAT = next(iter(FORMATS))

# The id in the name guarantees two songs with the same title never overwrite each other.
FILENAME_TEMPLATE = "%(title)s [%(id)s].%(ext)s"

# Centre-crop to a square (players show cover art as a square).
SQUARE_CROP = ["-vf", "crop='min(iw,ih)':'min(iw,ih)'", "-frames:v", "1", "-q:v", "2"]


def ffmpeg_location() -> Optional[str]:
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
        bundled = sorted(root.glob("ffmpeg*.exe"))
        if bundled:
            return str(bundled[0])
    return shutil.which("ffmpeg")


class SquareCoverPP(FFmpegPostProcessor):
    """Centre-crop the downloaded cover image to a square.

    yt-dlp's own thumbnail converter skips images that already have the target format,
    so it cannot be relied on for cropping; this step always runs.
    """

    def run(self, info):
        for thumb in info.get("thumbnails") or []:
            path = thumb.get("filepath")
            if not path or not os.path.exists(path):
                continue
            tmp = path + ".square.jpg"
            self.run_ffmpeg(path, tmp, SQUARE_CROP)
            os.replace(tmp, path)
        return [], info


@dataclass
class Entry:
    key: str
    id: str
    title: str
    url: str
    uploader: str = ""


@dataclass
class Result:
    key: str
    title: str
    uploader: str
    path: str
    has_thumbnail: bool


def _entry(e: dict, fallback_ie: Optional[str]) -> Optional[Entry]:
    vid = e.get("id")
    if not vid:
        return None
    ie = e.get("ie_key") or e.get("extractor_key") or fallback_ie
    if ie and ie.endswith("Tab"):  # "YoutubeTab" -> "Youtube", the key used for single videos
        ie = ie[:-3]
    url = e.get("url") or e.get("webpage_url") or ""
    if not url.startswith("http"):
        url = f"https://www.youtube.com/watch?v={vid}"
    return Entry(
        key=Library.make_key(ie, vid),
        id=vid,
        title=e.get("title") or vid,
        url=url,
        uploader=e.get("uploader") or e.get("channel") or "",
    )


def parse_info(info: Optional[dict], source_url: str = "") -> tuple[list[Entry], Optional[str]]:
    """Turn yt-dlp's answer into (entries, playlist title). A single song gives one entry, title None."""
    if not info:
        raise ValueError("Nothing was found at that link.")
    if info.get("_type") == "playlist" or "entries" in info:
        entries = []
        for raw in info.get("entries") or []:
            if raw:
                ent = _entry(raw, info.get("extractor_key"))
                if ent:
                    entries.append(ent)
        if not entries:
            raise ValueError("That playlist has no downloadable tracks.")
        return entries, info.get("title") or "Playlist"
    ent = _entry({**info, "url": info.get("webpage_url") or source_url}, info.get("extractor_key"))
    if not ent:
        raise ValueError("Could not read that link.")
    return [ent], None


def fetch_info(url: str, song_only: bool = False) -> tuple[list[Entry], Optional[str]]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "noplaylist": song_only,
        "compat_opts": ["no-certifi"],
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return parse_info(info, url)


def build_opts(dest: Path, hook: Callable[[dict], None]) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,  # entries are already resolved one by one
        "compat_opts": ["no-certifi"],
        "outtmpl": {"default": str(Path(dest) / FILENAME_TEMPLATE), "pl_thumbnail": ""},
        "writethumbnail": True,  # cover art is always fetched ...
        "postprocessors": [  # ... converted to jpg before the download starts
            {"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"},
        ],
        "progress_hooks": [hook],
    }
    executable = ffmpeg_location()
    if executable:
        opts["ffmpeg_location"] = executable
    return opts


def attach_postprocessors(ydl: YoutubeDL, codec: str, crop_square: bool) -> None:
    """Add the steps that run after the download, in this exact order."""
    if crop_square:
        ydl.add_post_processor(SquareCoverPP(ydl))
    extract_audio = {"key": "FFmpegExtractAudio", "preferredcodec": codec}
    if codec == "mp3":
        extract_audio["preferredquality"] = "0"  # best VBR
    steps = [
        extract_audio,
        {"key": "FFmpegMetadata", "add_chapters": False, "add_metadata": True},
        {"key": "EmbedThumbnail", "already_have_thumbnail": False},  # always embed the cover
    ]
    for step in steps:
        args = dict(step)
        ydl.add_post_processor(get_postprocessor(args.pop("key"))(ydl, **args))


def download_entry(
    entry: Entry,
    dest: Path,
    fmt_label: str,
    crop_square: bool,
    on_progress: Callable[[float, str], None],
    should_cancel: Callable[[], bool],
) -> Result:
    Path(dest).mkdir(parents=True, exist_ok=True)

    def hook(d: dict) -> None:
        if should_cancel():
            raise DownloadCancelled()
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            pct = 100.0 * (d.get("downloaded_bytes") or 0) / total if total else 0.0
            on_progress(pct, "Downloading")
        elif d.get("status") == "finished":
            on_progress(100.0, "Converting and adding cover art")

    codec, selector = FORMATS[fmt_label]
    opts = build_opts(dest, hook)
    opts["format"] = selector
    with YoutubeDL(opts) as ydl:
        attach_postprocessors(ydl, codec, crop_square)
        info = ydl.extract_info(entry.url, download=True)

    done = (info.get("requested_downloads") or [{}])[0]
    path = done.get("filepath") or info.get("filepath") or ""
    if not path or not Path(path).exists():
        raise RuntimeError("yt-dlp finished but the audio file was not found.")
    return Result(
        key=entry.key,
        title=info.get("track") or info.get("title") or entry.title,
        uploader=info.get("artist") or info.get("uploader") or entry.uploader,
        path=path,
        has_thumbnail=bool(info.get("thumbnails") or info.get("thumbnail")),
    )
