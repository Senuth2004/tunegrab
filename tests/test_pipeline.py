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
