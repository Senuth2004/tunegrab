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


def test_facebook_and_instagram_single_videos():
    for ie, vid, url in (("Facebook", "1234567890", "https://www.facebook.com/watch/?v=1234567890"),
                         ("Instagram", "C0dE123", "https://www.instagram.com/reel/C0dE123/")):
        entries, title = parse_info({"id": vid, "title": "Clip", "extractor_key": ie, "webpage_url": url})
        assert title is None
        assert entries[0].key == f"{ie.lower()} {vid}"
        assert entries[0].url == url and entries[0].index == 0


def test_carousel_items_without_own_link_use_playlist_index():
    post = "https://www.instagram.com/p/AbC123/"
    info = {"_type": "playlist", "title": "Post by someone", "extractor_key": "Instagram",
            "webpage_url": post, "entries": [
                {"id": "v1", "title": "Video 1"},                     # no link of its own
                None,                                                 # an image, not a video
                {"id": "v3", "title": "Video 3", "webpage_url": post},  # same link as the post
            ]}
    entries, _ = parse_info(info, post)
    assert [(e.url, e.index) for e in entries] == [(post, 1), (post, 3)]
    assert entries[0].key == "instagram v1"


def test_non_youtube_bare_ids_do_not_become_youtube_links():
    info = {"_type": "playlist", "title": "Page", "extractor_key": "FacebookPlaylist",
            "webpage_url": "https://www.facebook.com/somepage/videos", "entries": [
                {"id": "42", "title": "A", "ie_key": "Facebook", "url": "42"}]}
    entries, _ = parse_info(info)
    assert "youtube" not in entries[0].url
    assert entries[0].url == "https://www.facebook.com/somepage/videos" and entries[0].index == 1


def test_cookies_from_browser_are_passed_to_yt_dlp(monkeypatch, tmp_path):
    import tunegrab.downloader as downloader
    seen = []

    class FakeYDL:
        def __init__(self, options):
            seen.append(options)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download):
            return {"id": "x", "title": "t", "extractor_key": "Instagram", "webpage_url": url}

    monkeypatch.setattr(downloader, "YoutubeDL", FakeYDL)
    fetch_info("https://www.instagram.com/reel/x/", cookies_browser="firefox")
    fetch_info("https://www.instagram.com/reel/x/")
    assert seen[0]["cookiesfrombrowser"] == ("firefox",)
    assert "cookiesfrombrowser" not in seen[1]
    assert downloader.build_opts(tmp_path, lambda _: None, "chrome")["cookiesfrombrowser"] == ("chrome",)


def test_video_formats_and_keys():
    import tunegrab.downloader as downloader
    assert downloader.format_kind("mp4 video - best quality") == "video"
    assert downloader.format_kind(downloader.DEFAULT_FORMAT) == "audio"
    assert downloader.library_key("youtube abc", "video") == "youtube abc video"
    assert downloader.library_key("youtube abc", "audio") == "youtube abc"
