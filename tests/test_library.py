import os
from tunegrab.library import BLOCKED, DOWNLOADED, Library


def test_archive_lifecycle(tmp_path):
    lib = Library(tmp_path / "lib.db")
    key = Library.make_key("Youtube", "abc123")
    assert key == "youtube abc123"
    assert lib.get(key) is None

    lib.add_downloaded(key, "Song", "Artist", "/music/Song.m4a", "My list")
    assert lib.get(key).status == DOWNLOADED

    lib.block(key)  # user deleted the file on purpose
    t = lib.get(key)
    assert t.status == BLOCKED and t.path == "" and t.title == "Song"

    out = tmp_path / "archive.txt"
    assert lib.export_archive(out) == 1  # blocked tracks stay in the yt-dlp archive too
    assert out.read_text() == "youtube abc123\n"

    lib.forget(key)  # allow re-download
    assert lib.get(key) is None
    assert lib.export_archive(out) == 0


def test_redownload_overwrites_blocked(tmp_path):
    lib = Library(tmp_path / "lib.db")
    key = "youtube x"
    lib.add_downloaded(key, "A", "", "/a", "")
    lib.block(key)
    lib.add_downloaded(key, "A", "", "/a2", "")  # user forced a re-download
    assert lib.get(key).status == DOWNLOADED and lib.get(key).path == "/a2"
