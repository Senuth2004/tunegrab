"""Offscreen smoke test of the window: statuses, archive pre-selection, delete flows."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

import tunegrab.main as main_mod
from tunegrab import updater
from tunegrab.downloader import Entry, Result
from tunegrab.library import BLOCKED, Library
from tunegrab.main import MainWindow, app_icon
from tunegrab.theme import LIGHT_STYLESHEET, STYLESHEET, apply_theme


@pytest.fixture()
def win(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    QApplication.instance() or QApplication([])
    scheduled = []
    monkeypatch.setattr(main_mod, "QTimer", type("T", (), {
        "singleShot": staticmethod(lambda ms, fn: scheduled.append((ms, fn)))}))
    w = MainWindow(Library(tmp_path / "lib.db"))
    w.scheduled = scheduled
    yield w
    w.lib.close()


def entries():
    return [Entry(key=f"youtube id{i}", id=f"id{i}", title=f"Song {i}", url=f"https://x/{i}") for i in range(3)]


def test_dark_theme_uses_fusion_and_dark_surfaces():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    assert app.palette().color(QPalette.ColorRole.Window).name() == "#15181e"
    assert "#111318" in STYLESHEET and "#8b7cff" in STYLESHEET


def test_light_mode_action_applies_and_persists(win):
    win.light_mode_action.setChecked(True)
    assert win.settings.value("theme") == "light"
    assert QApplication.instance().palette().color(QPalette.ColorRole.Window).name() == "#f4f5f8"
    assert QApplication.instance().styleSheet() == LIGHT_STYLESHEET

    win.light_mode_action.setChecked(False)
    assert win.settings.value("theme") == "dark"
    assert QApplication.instance().palette().color(QPalette.ColorRole.Window).name() == "#15181e"


def test_application_icon_is_available():
    assert not app_icon().isNull()


def test_managed_build_keeps_update_controls_available(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    QApplication.instance() or QApplication([])
    win = MainWindow(Library(tmp_path / "lib.db"))
    assert win.repo_edit.isEnabled()
    assert win.repo_edit.text() == "Senuth2004/tunegrab"
    assert win.check_btn.isEnabled()
    assert not win.update_btn.isEnabled()
    assert win.auto_check.isEnabled()
    win.repo_edit.setText("me/my-app")
    assert win.settings.value("update_repo") == "me/my-app"
    win.lib.close()


def test_managed_check_button_starts_version_check(win, monkeypatch):
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    calls = []

    class FakeSignal:
        def connect(self, callback):
            pass

    class FakeChecker:
        def __init__(self, repo):
            calls.append(("created", repo))
            self.done = FakeSignal()
            self.finished = FakeSignal()

        def start(self):
            calls.append(("started",))

        def isRunning(self):
            return False

    monkeypatch.setattr(main_mod, "CheckWorker", FakeChecker)
    win.repo_edit.setText("example/tunegrab")

    win.check_btn.click()

    assert calls == [("created", "example/tunegrab"), ("started",)]
    assert not win.check_btn.isEnabled()


def checked(w):
    return [w.table.item(r, 0).checkState() == Qt.CheckState.Checked for r in range(w.table.rowCount())]


def test_archive_preselection(win, tmp_path):
    f = tmp_path / "Song 1.m4a"
    f.write_bytes(b"x")
    win.lib.add_downloaded("youtube id1", "Song 1", "", str(f), "L")
    win.lib.add_downloaded("youtube id2", "Song 2", "", "/gone.m4a", "L")
    win.lib.block("youtube id2")

    win.use_archive.setChecked(True)
    win._fetched(entries(), "My list")
    assert checked(win) == [True, False, False]       # only the new song is ticked
    assert [win.table.item(r, 2).text() for r in range(3)] == [
        "New", "Already downloaded", "Deleted earlier - blocked"]

    win.use_archive.setChecked(False)
    win._fetched(entries(), "My list")
    assert checked(win) == [True, True, True]          # archive off: everything is ticked
    win._set_checks(lambda s: s is None)               # "Select new only"
    assert checked(win) == [True, False, False]


def test_single_song_summary(win):
    win._fetched(entries()[:1], None)
    assert "Single song" in win.summary.text()
    assert win.download_btn.isEnabled()


def test_track_selection_buttons_update_download_button(win):
    win.lib.add_downloaded("youtube id1", "Song 1", "", "/gone.m4a", "My list")
    win._fetched(entries(), "My list")
    buttons = {button.text(): button for button in win.findChildren(main_mod.QPushButton)}

    buttons["Select none"].click()
    assert checked(win) == [False, False, False]
    assert not win.download_btn.isEnabled()

    buttons["Select all"].click()
    assert checked(win) == [True, True, True]
    assert win.download_btn.isEnabled()

    buttons["Select new only"].click()
    assert checked(win) == [True, False, True]
    assert win.download_btn.isEnabled()


def test_browse_button_updates_folder(win, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: "/tmp/Music")
    browse = next(button for button in win.findChildren(main_mod.QPushButton)
                  if button.text() == "Browse...")

    browse.click()

    assert win.folder.text() == "/tmp/Music"


def test_failed_fetch_clears_stale_tracks_and_disables_download(win, monkeypatch):
    win._fetched(entries(), "Old playlist")
    assert win.download_btn.isEnabled()

    class FakeWorker:
        def __init__(self, url, song_only, cookies_browser=""):
            self.url = url
            self.song_only = song_only
            self.done = FakeSignal()
            self.failed = FakeSignal()
            self.finished = FakeSignal()

        def isRunning(self):
            return False

        def start(self):
            pass

    class FakeSignal:
        def connect(self, callback):
            pass

    monkeypatch.setattr(main_mod, "FetchWorker", FakeWorker)
    monkeypatch.setattr(QMessageBox, "exec", lambda *args: QMessageBox.StandardButton.Ok)
    win.url.setText("https://example.invalid/video")
    win.fetch()
    assert win.table.rowCount() == 0
    assert not win.download_btn.isEnabled()
    win._fetch_failed("network error")
    assert "Could not load tracks" in win.summary.text()


def test_track_done_records_in_library(win, tmp_path):
    win._fetched(entries()[:1], "Mix")
    win._jobs_total, win._jobs_done = 1, 0
    win._track_done(0, Result("youtube id0", "Song 0", "Artist", str(tmp_path / "a.m4a"), True))
    assert win.lib.get("youtube id0").playlist == "Mix"
    assert win.table.item(0, 2).text() == "Done"


def _select_all(w):
    w.refresh_library()
    w.lib_table.selectAll()


def test_delete_and_block(win, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    f = tmp_path / "keep_me_not.m4a"
    f.write_bytes(b"x")
    win.lib.add_downloaded("youtube a", "A", "", str(f), "")
    _select_all(win)
    win.delete_selected(block=True)
    assert not f.exists()                                  # moved to the Trash
    assert win.lib.get("youtube a").status == BLOCKED     # and remembered, never re-downloaded
    assert win.lib_table.item(0, 3).text() == "Deleted (blocked)"

    _select_all(win)
    win.unblock_selected()
    assert win.lib.get("youtube a") is None               # can be downloaded again


def test_delete_and_allow_redownload(win, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    f = tmp_path / "b.m4a"
    f.write_bytes(b"x")
    win.lib.add_downloaded("youtube b", "B", "", str(f), "")
    _select_all(win)
    win.delete_selected(block=False)
    assert not f.exists() and win.lib.get("youtube b") is None


def test_missing_file_is_flagged_and_removable(win, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    win.lib.add_downloaded("youtube c", "C", "", "/does/not/exist.m4a", "")
    win.refresh_library()
    assert win.lib_table.item(0, 3).text() == "File missing"
    _select_all(win)
    win.delete_selected(block=True)                        # nothing to trash, still recorded
    assert win.lib.get("youtube c").status == BLOCKED


def test_library_filter(win):
    win.lib.add_downloaded("youtube d", "Alpha", "", "", "")
    win.lib.add_downloaded("youtube e", "Beta", "", "", "")
    win.refresh_library()
    win.search.setText("alp")
    hidden = [win.lib_table.isRowHidden(r) for r in range(2)]
    assert sorted(hidden) == [False, True]


# ---------------------------------------------------------------- update tab
def checks(outdated=True):
    return updater.Checks([
        updater.Status("tunegrab", "0.2.0", None),
        updater.Status("yt-dlp", "2026.1.1", "2026.10.26" if outdated else "2026.1.1"),
        updater.Status("mutagen", "1.47.0", "1.47.0"),
    ])


def test_startup_check_is_scheduled_when_enabled(win):
    assert win.auto_check.isChecked()
    assert [fn for _, fn in win.scheduled] == [win.check_updates]


def test_update_tab_shows_status(win):
    win.repo_edit.setText("")
    win._checks_done(checks())
    rows = [[win.upd_table.item(r, c).text() for c in range(4)] for r in range(3)]
    assert rows[0][3] == "No update source set"
    assert rows[1] == ["yt-dlp", "2026.1.1", "2026.10.26", "Update available"]
    assert rows[2][3] == "Up to date"
    assert win.update_btn.isEnabled() and win.tabs.tabText(win.tabs.indexOf(win.update_tab)) == "Update (1)"

    win._checks_done(checks(outdated=False))
    assert not win.update_btn.isEnabled() and win.tabs.tabText(win.tabs.indexOf(win.update_tab)) == "Update"


def test_managed_update_downloads_and_restarts(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    calls = []
    monkeypatch.setattr(updater, "run_update", lambda c, log: calls.append(c) or log("staging build") or True)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Library(tmp_path / "lib.db"))
    window._checks_done(updater.Checks(
        [updater.Status("tunegrab", "0.3.1", "0.3.2"),
         updater.Status("yt-dlp", "2026.1", "2026.2")],
        updater.AppRelease("0.3.2", "", "https://example.com/release.zip")))

    assert window.update_btn.isEnabled()
    assert window.update_btn.text() == "Install update"
    window.run_update()
    window.updater_thread.wait()
    QApplication.processEvents()

    assert len(calls) == 1
    assert "staging build" in window.upd_log.toPlainText()
    assert "Closing to install" in window.upd_log.toPlainText()
    window.lib.close()


def test_update_blocked_while_downloading(win, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[1]))
    win._checks_done(checks())
    win.worker = type("Busy", (), {"isRunning": lambda self: True})()
    win.run_update()
    assert shown == ["Downloads running"] and win.updater_thread is None


def test_update_runs_and_offers_restart(win, monkeypatch):
    restarted = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(main_mod, "restart_app", lambda: restarted.append(True))
    monkeypatch.setattr(updater, "run_update", lambda c, log: log("updating...") or True)
    win._checks_done(checks())
    win.run_update()
    win.updater_thread.wait()
    QApplication.processEvents()
    assert "updating..." in win.upd_log.toPlainText() and restarted == [True]
    assert win.tabs.tabText(win.tabs.indexOf(win.update_tab)) == "Update"


def test_update_error_is_shown_not_raised(win, monkeypatch):
    warned = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    monkeypatch.setattr(updater, "run_update",
                        lambda c, log: (_ for _ in ()).throw(updater.UpdateError("pip exploded")))
    win._checks_done(checks())
    win.run_update()
    win.updater_thread.wait()
    QApplication.processEvents()
    assert warned == ["pip exploded"] and win.update_btn.isEnabled()
    assert "Update failed: pip exploded" in win.upd_log.toPlainText()


def test_declining_the_update_does_nothing(win, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    win._checks_done(checks())
    win.run_update()
    assert win.updater_thread is None


def test_video_format_uses_separate_folder_status_and_disables_crop(win, tmp_path):
    win.folder.setText("/music/here")
    win.lib.add_downloaded("youtube id0", "Song 0", "", str(tmp_path / "x.m4a"), "")
    win._fetched(entries()[:1], None)
    assert win.crop.isEnabled()

    win.format.setCurrentText("mp4 video - up to 1080p")
    assert not win.crop.isEnabled()
    assert win.folder.text() != "/music/here"              # video has its own folder
    assert win.table.item(0, 2).text() == "New"            # audio download does not count for video
    assert "Single video" in win.summary.text()

    win._jobs_total, win._jobs_done = 1, 0
    win._track_done(0, Result("youtube id0 video", "Song 0", "", str(tmp_path / "x.mp4"), True))
    win.refresh_library()
    types = sorted(win.lib_table.item(r, 4).text() for r in range(win.lib_table.rowCount()))
    assert types == ["Audio", "Video"]

    win.format.setCurrentText(main_mod.DEFAULT_FORMAT)
    assert win.folder.text() == "/music/here" and win.crop.isEnabled()


def test_cookie_browser_choice_is_remembered(win):
    win.cookies.setCurrentIndex(win.cookies.findData("firefox"))
    assert win.cookies_browser() == "firefox"
    assert win.settings.value("cookies_browser") == "firefox"


def test_login_errors_explain_cookies(win, monkeypatch):
    texts = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: texts.append(self.text()))
    win._fetch_failed("[Instagram] abc: Requested content is not available, rate-limit reached or login required")
    assert "Sign-in cookies from" in texts[0]


def test_discover_tab_sends_picked_suggestions_to_download_tab(win, monkeypatch):
    from tunegrab.recommend import Suggestion
    assert win.tabs.tabText(win.tabs.indexOf(win.discover_tab)) == "Discover"
    win.lib.add_downloaded("youtube z", "Only A", "", "/gone.m4a", "")

    win._suggested([Suggestion("y", "Shared", "Chan", 1.0, ["A", "B", "C"]),
                    Suggestion("z", "Only A", "Chan2", 0.5, ["A"])])
    assert win.sugg_table.rowCount() == 2 and win.sugg_table.item(0, 2).text() == "A, B +1 more"
    assert win.sugg_table.item(0, 1).text() == "Chan"
    assert not win.send_btn.isEnabled()

    win.sugg_table.item(1, 0).setCheckState(Qt.CheckState.Checked)
    assert win.send_btn.isEnabled()
    win.send_btn.click()
    assert win.tabs.currentWidget() is win.download_tab
    assert [(e.key, e.url) for e in win.entries] == [("youtube z", "https://www.youtube.com/watch?v=z")]
    assert win.table.item(0, 2).text() == "In archive (file missing)"   # real keys: archive status works


def test_suggest_with_empty_library_explains_why(win, monkeypatch):
    class InlineWorker(main_mod.SuggestWorker):
        def start(self):
            self.run()

    monkeypatch.setattr(main_mod, "SuggestWorker", InlineWorker)
    win.suggest_music()
    assert "Download a few songs" in win.sugg_status.text()
