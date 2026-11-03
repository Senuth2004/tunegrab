import pytest
from tunegrab.downloader import parse_info


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
