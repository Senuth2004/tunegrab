import pytest
from tunegrab.downloader import fetch_info, parse_info


def test_single_song():
    info = {"id": "abc", "title": "Song", "uploader": "Artist",
            "extractor_key": "Youtube", "webpage_url": "https://www.youtube.com/watch?v=abc"}
    entries, title = parse_info(info)
    assert title is None and len(entries) == 1
    assert entries[0].key == "youtube abc" and entries[0].url.endswith("v=abc")


def test_playlist_flat_entries():
    info = {"_type": "playlist", "title": "Road trip", "extractor_key": "YoutubeTab", "entries": [
        {"id": "a1", "title": "One", "ie_key": "Youtube", "url": "https://www.youtube.com/watch?v=a1"},
        None,                                  # unavailable entry
        {"title": "no id"},                    # unusable entry
        {"id": "b2", "title": "Two", "url": "b2"},   # bare id, no ie_key -> fall back, build url
    ]}
    entries, title = parse_info(info)
    assert title == "Road trip" and [e.id for e in entries] == ["a1", "b2"]
    assert entries[0].key == "youtube a1"
    assert entries[1].key == "youtube b2"      # playlist extractor "YoutubeTab" -> "youtube"
    assert entries[1].url == "https://www.youtube.com/watch?v=b2"


def test_empty_results_raise():
    with pytest.raises(ValueError):
        parse_info(None)
    with pytest.raises(ValueError):
        parse_info({"_type": "playlist", "title": "x", "entries": []})


def test_fetch_info_uses_system_certificate_store(monkeypatch):
    seen = []

    class FakeYDL:
        def __init__(self, options):
            seen.append(options)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download):
            return {
                "id": "abc",
                "title": "Song",
                "extractor_key": "Youtube",
                "webpage_url": url,
            }

    monkeypatch.setattr("tunegrab.downloader.YoutubeDL", FakeYDL)
    entries, _ = fetch_info("https://www.youtube.com/watch?v=abc")

    assert entries[0].id == "abc"
    assert seen[0]["compat_opts"] == ["no-certifi"]


def test_frozen_windows_uses_bundled_ffmpeg(monkeypatch, tmp_path):
    import tunegrab.downloader as downloader

    bundled = tmp_path / "ffmpeg-win-x86_64.exe"
    bundled.write_bytes(b"test executable")
    monkeypatch.setattr(downloader.sys, "platform", "win32")
    monkeypatch.setattr(downloader.sys, "frozen", True, raising=False)
    monkeypatch.setattr(downloader.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(downloader.shutil, "which", lambda name: None)

    assert downloader.ffmpeg_location() == str(bundled)
    options = downloader.build_opts(tmp_path / "music", lambda _: None)
    assert options["ffmpeg_location"] == str(bundled)
