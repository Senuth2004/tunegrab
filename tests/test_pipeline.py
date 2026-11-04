"""End-to-end check of the real yt-dlp + ffmpeg chain, with no internet.

A local HTTP server plays the part of the site: it serves an opus audio file and a
16:9 cover image. We run tunegrab's own download_entry() against it and then inspect
the finished file with ffprobe: audio present, cover art embedded and square, tags set.
"""
import functools
import http.server
import json
import shutil
import subprocess
import threading

import pytest
import yt_dlp
from yt_dlp.extractor.common import InfoExtractor

import tunegrab.downloader as dl

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg/ffprobe test tools not installed")


def ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


@pytest.fixture()
def site(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    ff("-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "libopus", str(root / "song.webm"))
    ff("-f", "lavfi", "-i", "testsrc=size=640x360:rate=1", "-frames:v", "1", str(root / "cover.jpg"))
    ff("-f", "lavfi", "-i", "testsrc=size=640x360:rate=1", "-frames:v", "1", str(root / "cover.webp"))
    ff("-f", "lavfi", "-i", "testsrc=size=640x360:rate=1", "-frames:v", "1", str(root / "cover.png"))
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


class FakeIE(InfoExtractor):
    IE_NAME = "fake"
    _VALID_URL = r"fake://(?P<id>\w+)"
    base = ""
    cover = "cover.jpg"

    def _real_extract(self, url):
        vid = self._match_id(url)
        return {
            "id": vid, "title": "Test Song", "uploader": "Test Artist", "ext": "webm",
            "formats": [{"format_id": "a", "url": f"{self.base}/song.webm", "ext": "webm",
                         "acodec": "opus", "vcodec": "none"}],
            "thumbnails": [{"id": "0", "url": f"{self.base}/{self.cover}"}],
        }


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True, capture_output=True, text=True).stdout
    return json.loads(out)


@pytest.mark.parametrize("fmt_label,suffix", [
    ("m4a (AAC) - widest compatibility", ".m4a"),
    ("opus - best quality for the size", ".opus"),
    ("mp3 - works everywhere", ".mp3"),
])
@pytest.mark.parametrize("crop", [True, False])
@pytest.mark.parametrize("cover", ["cover.jpg", "cover.webp", "cover.png"])
def test_download_embeds_cover_art(site, tmp_path, monkeypatch, fmt_label, suffix, crop, cover):
    FakeIE.base, FakeIE.cover = site, cover

    class TestYDL(yt_dlp.YoutubeDL):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            ie = FakeIE(self)
            self._ies = {"Fake": ie.__class__, **self._ies}
            self._ies_instances["Fake"] = ie

    monkeypatch.setattr(dl, "YoutubeDL", TestYDL)
    entry = dl.Entry(key="fake abc", id="abc", title="Test Song", url="fake://abc")
    seen = []
    res = dl.download_entry(entry, tmp_path / "out", fmt_label, crop,
                            lambda pct, txt: seen.append(txt), lambda: False)

    assert res.path.endswith(suffix) and res.has_thumbnail
    info = probe(res.path)
    kinds = [s["codec_type"] for s in info["streams"]]
    assert "audio" in kinds and "video" in kinds, f"no embedded cover art: {kinds}"
    pic = next(s for s in info["streams"] if s["codec_type"] == "video")
    if crop:
        assert pic["width"] == pic["height"] == 360, (pic["width"], pic["height"])
    else:
        assert (pic["width"], pic["height"]) == (640, 360)
    tags = {k.lower(): v for k, v in {**info["format"].get("tags", {}),
            **next(s for s in info["streams"] if s["codec_type"] == "audio").get("tags", {})}.items()}
    assert tags.get("title") == "Test Song", tags
    assert not list((tmp_path / "out").glob("*.jpg")), "temporary cover file was left behind"


def test_cancel_stops_download(site, tmp_path, monkeypatch):
    FakeIE.base = site

    class TestYDL(yt_dlp.YoutubeDL):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            ie = FakeIE(self)
            self._ies = {"Fake": ie.__class__, **self._ies}
            self._ies_instances["Fake"] = ie

    monkeypatch.setattr(dl, "YoutubeDL", TestYDL)
    entry = dl.Entry(key="fake abc", id="abc", title="t", url="fake://abc")
    with pytest.raises(yt_dlp.utils.DownloadCancelled):
        dl.download_entry(entry, tmp_path / "o", dl.DEFAULT_FORMAT, True, lambda *a: None, lambda: True)


@pytest.fixture()
def video_site(tmp_path):
    """Separate video-only and audio-only streams, the way YouTube, Facebook and Instagram serve them."""
    root = tmp_path / "vsite"
    root.mkdir()
    ff("-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=2", "-c:v", "mpeg4", "-an",
       str(root / "video.mp4"))
    ff("-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "aac", "-vn", str(root / "audio.m4a"))
    ff("-f", "lavfi", "-i", "testsrc=size=640x360:rate=1", "-frames:v", "1", str(root / "cover.jpg"))
    ff("-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=2", "-f", "lavfi",
       "-i", "sine=frequency=440:duration=2", "-c:v", "libvpx-vp9", "-c:a", "libopus", "-shortest",
       str(root / "both.webm"))
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


class FakeVideoIE(InfoExtractor):
    IE_NAME = "fakevideo"
    _VALID_URL = r"fakevideo://(?P<id>\w+)"
    base = ""
    single_file = False

    def _real_extract(self, url):
        vid = self._match_id(url)
        if self.single_file:  # one muxed webm, needs remuxing to mp4
            formats = [{"format_id": "both", "url": f"{self.base}/both.webm", "ext": "webm",
                        "vcodec": "vp9", "acodec": "opus", "height": 240, "width": 320}]
        else:
            formats = [
                {"format_id": "v", "url": f"{self.base}/video.mp4", "ext": "mp4", "vcodec": "mp4v",
                 "acodec": "none", "height": 240, "width": 320},
                {"format_id": "a", "url": f"{self.base}/audio.m4a", "ext": "m4a", "acodec": "aac",
                 "vcodec": "none"},
            ]
        return {"id": vid, "title": "Test Clip", "uploader": "Test Channel", "formats": formats,
                "thumbnails": [{"id": "0", "url": f"{self.base}/cover.jpg"}]}


def _video_ydl(monkeypatch):
    class TestYDL(yt_dlp.YoutubeDL):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            ie = FakeVideoIE(self)
            self._ies = {"FakeVideo": ie.__class__, **self._ies}
            self._ies_instances["FakeVideo"] = ie

    monkeypatch.setattr(dl, "YoutubeDL", TestYDL)


@pytest.mark.parametrize("single_file", [False, True])
@pytest.mark.parametrize("fmt_label,suffix", [
    ("mp4 video - best quality", ".mp4"),
    ("mp4 video - up to 720p", ".mp4"),
    ("mkv video - best quality, any codec", ".mkv"),
])
def test_video_download_merges_streams(video_site, tmp_path, monkeypatch, fmt_label, suffix, single_file):
    FakeVideoIE.base, FakeVideoIE.single_file = video_site, single_file
    _video_ydl(monkeypatch)
    entry = dl.Entry(key="fakevideo abc", id="abc", title="Test Clip", url="fakevideo://abc")
    seen = []
    res = dl.download_entry(entry, tmp_path / "out", fmt_label, True,
                            lambda pct, txt: seen.append(txt), lambda: False)

    assert res.path.endswith(suffix), res.path
    assert res.key == "fakevideo abc video"
    info = probe(res.path)
    real_video = [s for s in info["streams"] if s["codec_type"] == "video"
                  and not s.get("disposition", {}).get("attached_pic")]
    assert real_video and real_video[0]["height"] == 240
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    tags = {k.lower(): v for k, v in info["format"].get("tags", {}).items()}
    assert tags.get("title") == "Test Clip", tags
    assert sorted(p.suffix for p in (tmp_path / "out").iterdir()) == [suffix], "temporary files left behind"
