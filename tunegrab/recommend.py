"""Music suggestions from YouTube's own "Mix" playlists. No Qt in here, and no account or API key.

Seeds are the most recent YouTube downloads in the library. For each one, YouTube's Mix for that
video (the endless "radio" of related songs) is read. Songs that come early in a Mix, and songs that
show up in the Mixes of several seeds, rank higher. Anything already in the library (downloaded or
deleted) is left out.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from yt_dlp import YoutubeDL

MIX_URL = "https://www.youtube.com/watch?v={id}&list=RD{id}"
MIX_DEPTH = 25  # songs read from each Mix; the further down, the less related
MIN_SECONDS, MAX_SECONDS = 60, 12 * 60  # skip shorts and hour-long compilations
PER_CHANNEL = 3  # do not let one channel fill the list


class SuggestError(Exception):
    pass


@dataclass
class Seed:
    id: str
    title: str


@dataclass
class Suggestion:
    id: str
    title: str
    uploader: str = ""
    score: float = 0.0
    because: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.id}"

    @property
    def key(self) -> str:
        return f"youtube {self.id}"


def normalize(text: str) -> str:
    """Compare titles loosely: "Song (Official Video)" and "song" are the same song."""
    text = re.sub(r"[\(\[][^\)\]]*[\)\]]", "", text or "").lower()
    return re.sub(r"[^\w]+", " ", text).strip()


def youtube_id(key: str) -> Optional[str]:
    """ "youtube abc" or "youtube abc video" -> "abc"; other sites -> None."""
    parts = key.split()
    return parts[1] if len(parts) >= 2 and parts[0] == "youtube" else None


def library_seeds(tracks: Iterable, limit: int = 8) -> list[Seed]:
    """The most recent distinct YouTube downloads (the library lists newest first)."""
    seeds, seen = [], set()
    for t in tracks:
        vid = youtube_id(t.key)
        if t.status != "downloaded" or not vid or vid in seen:
            continue
        seen.add(vid)
        seeds.append(Seed(vid, t.title))
        if len(seeds) >= limit:
            break
    return seeds


def fetch_mix(video_id: str, depth: int = MIX_DEPTH) -> list[dict]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "playlistend": depth + 1,  # the first entry is the seed itself
        "compat_opts": ["no-certifi"],
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(MIX_URL.format(id=video_id), download=False)
    return [e for e in (info or {}).get("entries") or [] if e]


def suggest(
    tracks: list,
    count: int = 30,
    get_mix: Callable[[str], list[dict]] = fetch_mix,
    on_progress: Callable[[int, int], None] = lambda done, total: None,
    should_cancel: Callable[[], bool] = lambda: False,
) -> list[Suggestion]:
    seeds = library_seeds(tracks)
    if not seeds:
        raise SuggestError("Download a few songs from YouTube first: suggestions are based on them.")
    known_ids = {vid for vid in (youtube_id(t.key) for t in tracks) if vid}
    known_titles = {normalize(t.title) for t in tracks} - {""}
    found: dict[str, Suggestion] = {}
    failures = 0

    for n, seed in enumerate(seeds, start=1):
        if should_cancel():
            break
        try:
            mix = get_mix(seed.id)
        except Exception:  # some videos have no Mix: just use the other seeds
            failures += 1
            mix = []
        for pos, e in enumerate(mix):
            vid, title = e.get("id"), e.get("title") or ""
            duration = e.get("duration")
            if not vid or vid in known_ids or normalize(title) in known_titles:
                continue
            if duration and not MIN_SECONDS <= duration <= MAX_SECONDS:
                continue
            s = found.setdefault(vid, Suggestion(vid, title, e.get("uploader") or e.get("channel") or ""))
            s.score += 1.0 / (1 + pos / 5)  # early in the Mix = closely related
            if seed.title not in s.because:
                s.because.append(seed.title)
        on_progress(n, len(seeds))

    if failures == len(seeds):
        raise SuggestError("YouTube did not return any Mixes. Check your connection and try again.")
    ranked = sorted(found.values(), key=lambda s: (-len(s.because), -s.score, s.title.lower()))
    result, per_channel, titles = [], {}, set()
    for s in ranked:
        channel, name = normalize(s.uploader), normalize(s.title)
        if per_channel.get(channel, 0) >= PER_CHANNEL or name in titles:  # same song, other upload
            continue
        per_channel[channel] = per_channel.get(channel, 0) + 1
        titles.add(name)
        result.append(s)
        if len(result) >= count:
            break
    return result
