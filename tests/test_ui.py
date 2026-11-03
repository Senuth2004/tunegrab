"""Offscreen smoke test of the window: statuses, archive pre-selection, delete flows."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

import tunegrab.main as main_mod
from tunegrab import updater
from tunegrab.downloader import Entry, Result
from tunegrab.library import BLOCKED, Library
from tunegrab.main import MainWindow


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
    assert win.update_btn.isEnabled() and win.tabs.tabText(2) == "Update (1)"

    win._checks_done(checks(outdated=False))
    assert not win.update_btn.isEnabled() and win.tabs.tabText(2) == "Update"


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
    assert win.tabs.tabText(2) == "Update"


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
