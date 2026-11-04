import pytest

from tunegrab import recommend
from tunegrab.library import Track


def track(vid, title, status="downloaded", site="youtube", video=False):
    key = f"{site} {vid}" + (" video" if video else "")
    return Track(key=key, title=title, uploader="", path="", playlist="", status=status)


def mix_entry(vid, title, uploader="Chan", duration=200):
    return {"id": vid, "title": title, "uploader": uploader, "duration": duration}


def test_seeds_are_recent_youtube_downloads_only():
    tracks = [track("a", "A"), track("a", "A (video)", video=True), track("b", "B", status="blocked"),
              track("c", "C", site="instagram"), track("d", "D")]
    assert [s.id for s in recommend.library_seeds(tracks)] == ["a", "d"]
    assert recommend.youtube_id("youtube abc video") == "abc"
    assert recommend.youtube_id("facebook 123") is None


def test_suggest_ranks_by_agreement_and_leaves_out_known_songs():
    lib = [track("s1", "Seed One"), track("s2", "Seed Two"), track("old", "Deleted Song", status="blocked")]
    mixes = {
        "s1": [mix_entry("s1", "Seed One"), mix_entry("old", "Deleted Song"), mix_entry("x", "Only One"),
               mix_entry("y", "Both", uploader="Other")],
        "s2": [mix_entry("s2", "Seed Two"), mix_entry("y", "Both", uploader="Other"),
               mix_entry("z", "Seed One (Official Video)")],  # another upload of a song we have
    }
    found = recommend.suggest(lib, get_mix=mixes.__getitem__)
    assert [s.id for s in found] == ["y", "x"]
    assert found[0].because == ["Seed One", "Seed Two"]
    assert found[0].url == "https://www.youtube.com/watch?v=y" and found[0].key == "youtube y"


def test_skips_shorts_compilations_and_duplicate_uploads():
    mix = [mix_entry("s", "Seed"), mix_entry("short", "Clip", duration=20),
           mix_entry("long", "10 Hours Mix", duration=36000), mix_entry("a", "Tune"),
           mix_entry("b", "Tune [Lyrics]", uploader="Lyrics Chan"), mix_entry("n", "No Duration", duration=None)]
    found = recommend.suggest([track("s", "Seed")], get_mix=lambda vid: mix)
    assert [s.id for s in found] == ["a", "n"]


def test_one_channel_cannot_fill_the_list():
    mix = [mix_entry(f"v{i}", f"Song {i}", uploader="Same") for i in range(6)]
    assert len(recommend.suggest([track("s", "Seed")], get_mix=lambda vid: mix)) == recommend.PER_CHANNEL


def test_a_seed_without_mix_is_skipped_but_all_failing_is_an_error():
    def get_mix(vid):
        if vid == "bad":
            raise RuntimeError("This playlist type is unviewable")
        return [mix_entry("x", "X")]

    assert [s.id for s in recommend.suggest([track("bad", "B"), track("ok", "O")], get_mix=get_mix)] == ["x"]
    with pytest.raises(recommend.SuggestError, match="did not return"):
        recommend.suggest([track("bad", "B")], get_mix=get_mix)
    with pytest.raises(recommend.SuggestError, match="Download a few songs"):
        recommend.suggest([track("c", "C", site="instagram")])


def test_fetch_mix_reads_a_limited_flat_playlist(monkeypatch):
    seen = {}

    class FakeYDL:
        def __init__(self, opts):
            seen["opts"] = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def extract_info(self, url, download):
            seen["url"] = url
            return {"_type": "playlist", "entries": [mix_entry("a", "A"), None]}

    monkeypatch.setattr(recommend, "YoutubeDL", FakeYDL)
    assert [e["id"] for e in recommend.fetch_mix("abc")] == ["a"]
    assert seen["url"] == "https://www.youtube.com/watch?v=abc&list=RDabc"
    assert seen["opts"]["extract_flat"] == "in_playlist" and seen["opts"]["playlistend"] == recommend.MIX_DEPTH + 1
