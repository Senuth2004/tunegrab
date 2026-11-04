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

AUDIO = "audio"
VIDEO = "video"


def _video_selector(max_height: Optional[int] = None) -> str:
    """Prefer streams that fit an mp4 without re-encoding, fall back to anything."""
    cap = f"[height<={max_height}]" if max_height else ""
    return "/".join((
        f"bv*{cap}[ext=mp4]+ba[ext=m4a]",
        f"b{cap}[ext=mp4]",
        f"bv*{cap}+ba",
        f"b{cap}",
        "bv*+ba/b",  # nothing small enough: take what the site has
    ))


# label -> (audio codec, yt-dlp format selector)
AUDIO_FORMATS = {
    "m4a (AAC) - widest compatibility": ("m4a", "bestaudio[ext=m4a]/bestaudio/best"),
    "opus - best quality for the size": ("opus", "bestaudio[ext=webm]/bestaudio/best"),
    "mp3 - works everywhere": ("mp3", "bestaudio/best"),
}
# label -> (container, yt-dlp format selector)
VIDEO_FORMATS = {
    "mp4 video - best quality": ("mp4", _video_selector()),
    "mp4 video - up to 1080p": ("mp4", _video_selector(1080)),
    "mp4 video - up to 720p": ("mp4", _video_selector(720)),
    "mp4 video - up to 480p (small files)": ("mp4", _video_selector(480)),
    "mkv video - best quality, any codec": ("mkv", "bv*+ba/b"),
}
FORMATS = {**AUDIO_FORMATS, **VIDEO_FORMATS}
DEFAULT_FORMAT = next(iter(AUDIO_FORMATS))

# Browsers yt-dlp can read sign-in cookies from. Instagram and Facebook often need them.
COOKIE_BROWSERS = ["firefox", "chrome", "chromium", "brave", "edge", "opera", "vivaldi"]


def format_kind(fmt_label: str) -> str:
    return VIDEO if fmt_label in VIDEO_FORMATS else AUDIO


def library_key(key: str, kind: str) -> str:
    """Audio and video of the same item are tracked separately in the library."""
    return f"{key} {VIDEO}" if kind == VIDEO else key

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
    # Set when the item has no link of its own (for example one video of an Instagram
    # carousel): download it as item `index` (1-based) of the playlist at `url`.
    index: int = 0


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
        # YouTube playlists list bare ids; other sites get no usable link here.
        url = f"https://www.youtube.com/watch?v={vid}" if (ie or "").lower().startswith("youtube") else ""
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
        page = info.get("webpage_url") or source_url
        for pos, raw in enumerate(info.get("entries") or [], start=1):
            if raw:
                ent = _entry(raw, info.get("extractor_key"))
                if ent:
                    if not ent.url or ent.url in (page, source_url):
                        ent.url, ent.index = page, raw.get("playlist_index") or pos
                    entries.append(ent)
        if not entries:
            raise ValueError("That playlist has no downloadable tracks.")
        return entries, info.get("title") or "Playlist"
    ent = _entry({**info, "url": info.get("webpage_url") or source_url}, info.get("extractor_key"))
    if not ent:
        raise ValueError("Could not read that link.")
    return [ent], None


def _add_cookies(opts: dict, cookies_browser: str) -> dict:
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)
    return opts


def fetch_info(url: str, song_only: bool = False,
               cookies_browser: str = "") -> tuple[list[Entry], Optional[str]]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "noplaylist": song_only,
        "compat_opts": ["no-certifi"],
    }
    with YoutubeDL(_add_cookies(opts, cookies_browser)) as ydl:
        info = ydl.extract_info(url, download=False)
    return parse_info(info, url)


def build_opts(dest: Path, hook: Callable[[dict], None], cookies_browser: str = "") -> dict:
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
    return _add_cookies(opts, cookies_browser)


def attach_postprocessors(ydl: YoutubeDL, codec: str, crop_square: bool, kind: str = AUDIO) -> None:
    """Add the steps that run after the download, in this exact order."""
    if kind == VIDEO:
        # A single-file download in another container is remuxed (no re-encoding).
        first = {"key": "FFmpegVideoRemuxer", "preferedformat": codec}
    else:
        if crop_square:
            ydl.add_post_processor(SquareCoverPP(ydl))
        first = {"key": "FFmpegExtractAudio", "preferredcodec": codec}
        if codec == "mp3":
            first["preferredquality"] = "0"  # best VBR
    steps = [
        first,
        {"key": "FFmpegMetadata", "add_chapters": kind == VIDEO, "add_metadata": True},
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
    cookies_browser: str = "",
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
            on_progress(100.0, "Merging video and adding thumbnail" if kind == VIDEO
                        else "Converting and adding cover art")

    kind = format_kind(fmt_label)
    codec, selector = FORMATS[fmt_label]
    opts = build_opts(dest, hook, cookies_browser)
    opts["format"] = selector
    if kind == VIDEO:
        opts["merge_output_format"] = codec
    if entry.index:  # one item of a multi-video post: pick it out of the playlist
        opts["noplaylist"] = False
        opts["playlist_items"] = str(entry.index)
    with YoutubeDL(opts) as ydl:
        attach_postprocessors(ydl, codec, crop_square, kind)
        info = ydl.extract_info(entry.url, download=True)

    if info and (info.get("_type") == "playlist" or "entries" in info):
        info = next((e for e in info.get("entries") or [] if e), None)
    if not info:
        raise RuntimeError("yt-dlp did not return the requested item.")
    done = (info.get("requested_downloads") or [{}])[0]
    path = done.get("filepath") or info.get("filepath") or ""
    if not path or not Path(path).exists():
        raise RuntimeError(f"yt-dlp finished but the {kind} file was not found.")
    return Result(
        key=library_key(entry.key, kind),
        title=info.get("track") or info.get("title") or entry.title,
        uploader=info.get("artist") or info.get("uploader") or entry.uploader,
        path=path,
        has_thumbnail=bool(info.get("thumbnails") or info.get("thumbnail")),
    )
