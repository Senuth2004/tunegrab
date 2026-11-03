"""Tunegrab - a small Qt/KDE front end for yt-dlp: songs and playlists, cover art, archive."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QFile, QSettings, QStandardPaths, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)
from yt_dlp.utils import DownloadCancelled, sanitize_filename

from . import __version__, updater
from .downloader import DEFAULT_FORMAT, FORMATS, Entry, Result, download_entry, fetch_info
from .library import BLOCKED, DOWNLOADED, Library
from .theme import apply_theme

KEY_ROLE = Qt.ItemDataRole.UserRole


def app_icon() -> QIcon:
    if getattr(sys, "frozen", False):
        icon_path = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "tunegrab.svg"
    else:
        icon_path = Path(__file__).parent / "assets" / "tunegrab.svg"
    return QIcon(str(icon_path)) if icon_path.is_file() else QIcon.fromTheme("audio-x-generic")


def move_to_trash(path: str) -> bool:
    """Send a file to the Trash (freedesktop spec, so Dolphin can restore it).

    Qt does it natively; if that fails (for example on another mount) fall back to
    `gio trash`. Returns False when the file could not be trashed.
    """
    if QFile(path).moveToTrash():
        return True
    gio = shutil.which("gio")
    if gio:
        return subprocess.run([gio, "trash", path], capture_output=True).returncode == 0
    return False


def notify(title: str, body: str) -> None:
    if shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "-i", "audio-x-generic", title, body])


class FetchWorker(QThread):
    done = Signal(list, object)  # entries, playlist title or None
    failed = Signal(str)

    def __init__(self, url: str, song_only: bool):
        super().__init__()
        self.url, self.song_only = url, song_only

    def run(self) -> None:
        try:
            entries, title = fetch_info(self.url, self.song_only)
        except Exception as exc:  # network, unsupported link, ...
            self.failed.emit(str(exc).replace("ERROR: ", ""))
            return
        self.done.emit(entries, title)


class DownloadWorker(QThread):
    progress = Signal(int, float, str)  # row, percent, text
    track_done = Signal(int, object)  # row, Result
    track_failed = Signal(int, str)  # row, message
    finished_all = Signal(int, int, bool)  # ok, failed, cancelled

    def __init__(self, jobs: list[tuple[int, Entry]], dest: Path, fmt: str, crop: bool):
        super().__init__()
        self.jobs, self.dest, self.fmt, self.crop = jobs, dest, fmt, crop
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        ok = failed = 0
        for row, entry in self.jobs:
            if self._cancel:
                break
            try:
                res = download_entry(
                    entry, self.dest, self.fmt, self.crop,
                    lambda pct, txt, r=row: self.progress.emit(r, pct, txt),
                    lambda: self._cancel,
                )
            except DownloadCancelled:
                break
            except Exception as exc:
                failed += 1
                self.track_failed.emit(row, str(exc).replace("ERROR: ", "")[:300])
                continue
            ok += 1
            self.track_done.emit(row, res)
        self.finished_all.emit(ok, failed, self._cancel)


class CheckWorker(QThread):
    done = Signal(object)  # updater.Checks

    def __init__(self, repo: str):
        super().__init__()
        self.repo = repo

    def run(self) -> None:
        self.done.emit(updater.check_all(self.repo))


class UpdateWorker(QThread):
    line = Signal(str)
    done = Signal(bool, str)  # restart needed, error message ("" when fine)

    def __init__(self, checks):
        super().__init__()
        self.checks = checks

    def run(self) -> None:
        try:
            restart = updater.run_update(self.checks, self.line.emit)
        except Exception as exc:  # UpdateError or anything unexpected: show it, never crash
            self.done.emit(False, str(exc))
            return
        self.done.emit(restart, "")


def restart_app() -> None:
    options = {"cwd": str(updater.PROJECT_ROOT)}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    subprocess.Popen([sys.executable, "-m", "tunegrab"], **options)
    QApplication.quit()


class MainWindow(QMainWindow):
    def __init__(self, lib: Library):
        super().__init__()
        self.lib = lib
        self.settings = QSettings("tunegrab", "tunegrab")
        self.entries: list[Entry] = []
        self.playlist_title: Optional[str] = None
        self.fetcher: Optional[FetchWorker] = None
        self.worker: Optional[DownloadWorker] = None
        self._download_active = False

        self.setWindowTitle(f"Tunegrab {__version__}")
        self.setWindowIcon(app_icon())
        self.resize(940, 680)
        self.checks: Optional[updater.Checks] = None
        self.checker: Optional[CheckWorker] = None
        self.updater_thread: Optional[UpdateWorker] = None
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_download_tab(), "Download")
        self.tabs.addTab(self._build_library_tab(), "Library")
        self.tabs.addTab(self._build_update_tab(), "Update")
        self.tabs.currentChanged.connect(lambda i: self.refresh_library() if i == 1 else None)
        self.setCentralWidget(self.tabs)
        self.refresh_library()
        if self.auto_check.isChecked() and not updater.is_managed_install():
            QTimer.singleShot(1500, self.check_updates)

    # ------------------------------------------------------------------ download tab
    def _build_download_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        top = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText("Paste a song or playlist link, then press Enter")
        self.url.setClearButtonEnabled(True)
        self.url.returnPressed.connect(self.fetch)
        self.fetch_btn = QPushButton("Fetch")
        self.fetch_btn.clicked.connect(self.fetch)
        top.addWidget(self.url, 1)
        top.addWidget(self.fetch_btn)
        v.addLayout(top)

        self.song_only = QCheckBox("Song only (ignore the playlist part of the link)")
        v.addWidget(self.song_only)

        self.summary = QLabel("")
        v.addWidget(self.summary)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Track", "Uploader", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        v.addWidget(self.table, 1)

        sel = QHBoxLayout()
        for text, fn in (("Select all", lambda: self._set_checks(lambda s: True)),
                         ("Select none", lambda: self._set_checks(lambda s: False)),
                         ("Select new only", lambda: self._set_checks(lambda s: s is None))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            sel.addWidget(b)
        sel.addStretch(1)
        v.addLayout(sel)

        opts = QHBoxLayout()
        opts.addWidget(QLabel("Format:"))
        self.format = QComboBox()
        self.format.addItems(list(FORMATS))
        saved = self.settings.value("format", DEFAULT_FORMAT)
        self.format.setCurrentText(saved if saved in FORMATS else DEFAULT_FORMAT)
        opts.addWidget(self.format)
        opts.addSpacing(12)
        opts.addWidget(QLabel("Save to:"))
        music = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MusicLocation)
        self.folder = QLineEdit(self.settings.value("folder", str(Path(music) / "Tunegrab")))
        opts.addWidget(self.folder, 1)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self.browse)
        opts.addWidget(browse)
        v.addLayout(opts)

        checks = QHBoxLayout()
        self.use_archive = QCheckBox("Skip tracks already in the archive")
        self.use_archive.setChecked(self.settings.value("archive", True, type=bool))
        self.own_folder = QCheckBox("Put playlists in their own folder")
        self.own_folder.setChecked(self.settings.value("own_folder", True, type=bool))
        self.crop = QCheckBox("Square cover art")
        self.crop.setChecked(self.settings.value("crop", True, type=bool))
        for c in (self.use_archive, self.own_folder, self.crop):
            checks.addWidget(c)
        checks.addStretch(1)
        v.addLayout(checks)

        run = QHBoxLayout()
        self.download_btn = QPushButton("Download selected")
        self.download_btn.clicked.connect(self.start_download)
        self.download_btn.setEnabled(False)
        self.table.itemChanged.connect(self._download_selection_changed)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_download)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.status = QLabel("")
        run.addWidget(self.download_btn)
        run.addWidget(self.cancel_btn)
        run.addWidget(self.bar, 1)
        v.addLayout(run)
        v.addWidget(self.status)
        return w

    def browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose music folder", self.folder.text())
        if d:
            self.folder.setText(d)

    def _set_checks(self, want) -> None:
        for row, entry in enumerate(self.entries):
            t = self.lib.get(entry.key)
            state = t.status if t else None
            self.table.item(row, 0).setCheckState(
                Qt.CheckState.Checked if want(state) else Qt.CheckState.Unchecked)

    def _status_text(self, entry: Entry) -> tuple[str, Optional[str]]:
        t = self.lib.get(entry.key)
        if t is None:
            return "New", None
        if t.status == BLOCKED:
            return "Deleted earlier - blocked", BLOCKED
        if t.path and not os.path.exists(t.path):
            return "In archive (file missing)", DOWNLOADED
        return "Already downloaded", DOWNLOADED

    def fetch(self) -> None:
        url = self.url.text().strip()
        if self._download_active:
            self.status.setText("Wait for the current downloads to finish before fetching another link.")
            return
        if not url or (self.fetcher is not None and self.fetcher.isRunning()):
            return
        self.entries = []
        self.playlist_title = None
        self.table.setRowCount(0)
        self._update_download_button()
        self.fetch_btn.setEnabled(False)
        self.summary.setText("Looking up the link...")
        self.fetcher = FetchWorker(url, self.song_only.isChecked())
        self.fetcher.done.connect(self._fetched)
        self.fetcher.failed.connect(self._fetch_failed)
        self.fetcher.finished.connect(self._fetch_finished)
        self.fetcher.start()

    def _fetch_finished(self) -> None:
        self.fetch_btn.setEnabled(True)  # keep the QThread object alive until the next fetch

    def _fetch_failed(self, msg: str) -> None:
        self.summary.setText("Could not load tracks. Check the link and your network connection.")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Could not read that link")
        if "CERTIFICATE_VERIFY_FAILED" in msg:
            box.setText(
                "Tunegrab could not verify the site's security certificate. Check your system "
                "date and make sure your system CA certificates are up to date."
            )
        else:
            box.setText("Tunegrab could not load this link. Check the link and your network connection.")
        box.setDetailedText(msg)
        box.exec()

    def _fetched(self, entries: list, title: Optional[str]) -> None:
        self.entries, self.playlist_title = entries, title
        self.table.setRowCount(len(entries))
        skip = self.use_archive.isChecked()
        known = 0
        for row, e in enumerate(entries):
            text, state = self._status_text(e)
            known += state is not None
            item = QTableWidgetItem(e.title)
            item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                          | Qt.ItemFlag.ItemIsSelectable)
            item.setCheckState(Qt.CheckState.Unchecked if (skip and state) else Qt.CheckState.Checked)
            self.table.setItem(row, 0, item)
            self.table.setItem(row, 1, QTableWidgetItem(e.uploader))
            self.table.setItem(row, 2, QTableWidgetItem(text))
        kind = f"Playlist: {title}" if title else "Single song"
        self.summary.setText(f"{kind} - {len(entries)} track(s), {known} already known.")
        self.bar.setValue(0)
        self.status.setText("")
        self._update_download_button()

    def _download_selection_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == 0:
            self._update_download_button()

    def _update_download_button(self) -> None:
        has_selected = False
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                has_selected = True
                break
        self.download_btn.setEnabled(bool(self.entries and has_selected and not self._download_active))

    def _checked_jobs(self) -> list[tuple[int, Entry]]:
        return [(r, self.entries[r]) for r in range(len(self.entries))
                if self.table.item(r, 0).checkState() == Qt.CheckState.Checked]

    def start_download(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
            if sys.platform == "win32":
                install_hint = "Windows: install FFmpeg (for example, winget install Gyan.FFmpeg.Shared)."
            elif sys.platform == "darwin":
                install_hint = "macOS: install FFmpeg with  brew install ffmpeg."
            else:
                install_hint = "Linux: install ffmpeg and ffprobe with your distribution's package manager."
            QMessageBox.warning(
                self, "ffmpeg is missing",
                "ffmpeg and ffprobe are needed to convert audio and embed cover art.\n\n"
                f"{install_hint}\n"
                "On Fedora, install ffmpeg-free; MP3 may require the full FFmpeg from RPM Fusion.")
            return
        jobs = self._checked_jobs()
        if not jobs:
            self.status.setText("Nothing selected.")
            self._update_download_button()
            return
        dest = Path(self.folder.text()).expanduser()
        if self.playlist_title and self.own_folder.isChecked():
            dest = dest / sanitize_filename(self.playlist_title)
        for key, val in (("format", self.format.currentText()), ("folder", self.folder.text()),
                         ("archive", self.use_archive.isChecked()),
                         ("own_folder", self.own_folder.isChecked()),
                         ("crop", self.crop.isChecked())):
            self.settings.setValue(key, val)
        self.worker = DownloadWorker(jobs, dest, self.format.currentText(), self.crop.isChecked())
        self._jobs_total, self._jobs_done = len(jobs), 0
        self.worker.progress.connect(self._progress)
        self.worker.track_done.connect(self._track_done)
        self.worker.track_failed.connect(self._track_failed)
        self.worker.finished_all.connect(self._all_done)
        self._download_active = True
        self.download_btn.setEnabled(False)
        self.fetch_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.worker.start()

    def cancel_download(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.status.setText("Cancelling...")

    def _set_status(self, row: int, text: str) -> None:
        self.table.item(row, 2).setText(text)

    def _progress(self, row: int, pct: float, text: str) -> None:
        self._set_status(row, f"{text} {pct:.0f}%" if text == "Downloading" else text)
        self.table.scrollToItem(self.table.item(row, 0))
        self.bar.setValue(int((self._jobs_done + pct / 100) / self._jobs_total * 100))
        self.status.setText(f"Track {self._jobs_done + 1} of {self._jobs_total}")

    def _track_done(self, row: int, res: Result) -> None:
        self._jobs_done += 1
        playlist = self.playlist_title or ""
        self.lib.add_downloaded(res.key, res.title, res.uploader, res.path, playlist)
        self._set_status(row, "Done" if res.has_thumbnail else "Done (no cover art offered)")
        self.table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
        self._update_download_button()

    def _track_failed(self, row: int, msg: str) -> None:
        self._jobs_done += 1
        self._set_status(row, "Failed")
        self.table.item(row, 2).setToolTip(msg)
        self.status.setText(f"Failed: {msg}")

    def _all_done(self, ok: int, failed: int, cancelled: bool) -> None:
        self.download_btn.setEnabled(True)
        self.fetch_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._download_active = False
        self._update_download_button()
        msg = f"{ok} downloaded, {failed} failed" + (", cancelled" if cancelled else "")
        self.status.setText(msg)
        self.bar.setValue(100 if not cancelled else self.bar.value())
        self.refresh_library()
        if ok or failed:
            notify("Tunegrab", msg)

    # ------------------------------------------------------------------ update tab
    def _build_update_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.upd_table = QTableWidget(0, 4)
        self.upd_table.setHorizontalHeaderLabels(["Component", "Installed", "Latest", "Status"])
        self.upd_table.verticalHeader().setVisible(False)
        self.upd_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.upd_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        hh = self.upd_table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setStretchLastSection(True)
        v.addWidget(self.upd_table)

        src = QHBoxLayout()
        src.addWidget(QLabel("Tunegrab update source (GitHub owner/repo):"))
        repo = self.settings.value("update_repo", "Senuth2004/tunegrab") or "Senuth2004/tunegrab"
        self.repo_edit = QLineEdit(repo)
        self.repo_edit.setPlaceholderText("GitHub owner/repository, e.g. Senuth2004/tunegrab")
        self.repo_edit.textChanged.connect(
            lambda value: self.settings.setValue("update_repo", value.strip()))
        src.addWidget(self.repo_edit, 1)
        v.addLayout(src)
        self.auto_check = QCheckBox("Check for updates when the app starts")
        self.auto_check.setChecked(self.settings.value("auto_check", True, type=bool))
        self.auto_check.toggled.connect(lambda value: self.settings.setValue("auto_check", value))
        v.addWidget(self.auto_check)

        row = QHBoxLayout()
        self.check_btn = QPushButton("Check for updates")
        self.check_btn.clicked.connect(self.check_updates)
        self.update_btn = QPushButton("Get update")
        self.update_btn.setEnabled(False)
        self.update_btn.clicked.connect(self.run_update)
        row.addWidget(self.check_btn)
        row.addWidget(self.update_btn)
        row.addStretch(1)
        v.addLayout(row)

        if updater.is_managed_install():
            note_text = ("Check for updates to see whether a newer Tunegrab release is available. "
                         "Get update opens the release downloads; packaged apps cannot replace their "
                         "own files. ffmpeg is installed separately using your system package manager.")
        else:
            note_text = ("yt-dlp and mutagen come from PyPI. Tunegrab itself comes from the latest GitHub "
                         "release of the source above. ffmpeg and PySide6 belong to your system; update "
                         "them with your system package manager.")
        note = QLabel(note_text)
        note.setWordWrap(True)
        v.addWidget(note)
        self.upd_log = QPlainTextEdit()
        self.upd_log.setReadOnly(True)
        v.addWidget(self.upd_log, 1)
        return w

    def _upd_status_text(self, st: updater.Status) -> str:
        if st.error:
            return f"Could not check: {st.error}"
        if st.name == "tunegrab" and st.latest is None:
            return "No update source set" if not self.repo_edit.text().strip() else "Unknown"
        if st.installed is None:
            return "Not installed"
        return "Update available" if st.outdated else "Up to date"

    def check_updates(self) -> None:
        if self.checker is not None and self.checker.isRunning():
            return
        for key, val in (("update_repo", self.repo_edit.text().strip()),
                         ("auto_check", self.auto_check.isChecked())):
            self.settings.setValue(key, val)
        self.check_btn.setEnabled(False)
        self.upd_log.appendPlainText("Checking for updates...")
        self.checker = CheckWorker(self.repo_edit.text().strip())
        self.checker.done.connect(self._checks_done)
        self.checker.finished.connect(lambda: self.check_btn.setEnabled(True))
        self.checker.start()

    def _checks_done(self, checks) -> None:
        self.checks = checks
        self.upd_table.setRowCount(len(checks.statuses))
        for r, st in enumerate(checks.statuses):
            for c, text in enumerate((st.name, st.installed or "-", st.latest or "-",
                                      self._upd_status_text(st))):
                self.upd_table.setItem(r, c, QTableWidgetItem(text))
        n = len(checks.outdated)
        managed = updater.is_managed_install()
        self.update_btn.setEnabled(n > 0)
        self.update_btn.setText("Get update" if managed else "Update everything")
        self.tabs.setTabText(2, f"Update ({n})" if n else "Update")
        if managed and n:
            self.upd_log.appendPlainText(
                f"{n} update(s) available. Install a newer Tunegrab build to update bundled components.")
        else:
            self.upd_log.appendPlainText(f"{n} update(s) available." if n else "Everything is up to date.")
        if checks.release and any(s.name == "tunegrab" and s.outdated for s in checks.statuses):
            notes = checks.release.notes.strip()[:600]
            self.upd_log.appendPlainText(f"Tunegrab {checks.release.version}:\n{notes}" if notes
                                         else f"Tunegrab {checks.release.version} is available.")

    def run_update(self) -> None:
        if self.checks is None or not self.checks.outdated:
            return
        if updater.is_managed_install():
            repo = self.repo_edit.text().strip()
            if not updater.REPO_RE.fullmatch(repo):
                QMessageBox.warning(self, "Invalid update source",
                                    "Enter a GitHub source in owner/repository format.")
                return
            url = QUrl(f"https://github.com/{repo}/releases/latest")
            if QDesktopServices.openUrl(url):
                self.upd_log.appendPlainText(f"Opened the Tunegrab release downloads: {url.toString()}")
            else:
                QMessageBox.warning(self, "Could not open release page",
                                    "Open this address in your browser:\n" + url.toString())
            return
        if self.updater_thread is not None and self.updater_thread.isRunning():
            return
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Downloads running",
                                    "Finish or cancel the current downloads before updating.")
            return
        names = ", ".join(s.name for s in self.checks.outdated)
        extra = ("\n\nTunegrab itself will be downloaded from "
                 f"github.com/{self.repo_edit.text().strip()} (HTTPS). The old version is kept in .backup/."
                 if any(s.name == "tunegrab" for s in self.checks.outdated) else "")
        if QMessageBox.question(self, "Update", f"Update {names}?{extra}") != QMessageBox.StandardButton.Yes:
            return
        self.update_btn.setEnabled(False)
        self.check_btn.setEnabled(False)
        self.updater_thread = UpdateWorker(self.checks)
        self.updater_thread.line.connect(self.upd_log.appendPlainText)
        self.updater_thread.done.connect(self._update_done)
        self.updater_thread.start()

    def _update_done(self, restart: bool, error: str) -> None:
        self.check_btn.setEnabled(True)
        if error:
            self.upd_log.appendPlainText(f"Update failed: {error}")
            QMessageBox.warning(self, "Update failed", error)
            self.update_btn.setEnabled(True)
            return
        self.tabs.setTabText(2, "Update")
        if restart:
            self.upd_log.appendPlainText("Update finished.")
            if QMessageBox.question(self, "Update finished", "Restart Tunegrab now to use the new version?"
                                    ) == QMessageBox.StandardButton.Yes:
                restart_app()
        else:
            self.upd_log.appendPlainText("Nothing to update.")

    def closeEvent(self, event) -> None:
        if self.updater_thread is not None and self.updater_thread.isRunning():
            QMessageBox.information(self, "Updating", "An update is in progress; please wait until it finishes.")
            event.ignore()
            return
        if self.checker is not None and self.checker.isRunning():
            self.checker.wait(3000)
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(8000)
        super().closeEvent(event)

    # ------------------------------------------------------------------ library tab
    def _build_library_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by title, uploader or playlist")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter_library)
        v.addWidget(self.search)

        self.lib_table = QTableWidget(0, 4)
        self.lib_table.setHorizontalHeaderLabels(["Title", "Uploader", "Playlist", "Status"])
        self.lib_table.verticalHeader().setVisible(False)
        self.lib_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.lib_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.lib_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        hh = self.lib_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        v.addWidget(self.lib_table, 1)

        row = QHBoxLayout()
        for text, fn in (
            ("Delete - never download again", lambda: self.delete_selected(block=True)),
            ("Delete - allow re-download", lambda: self.delete_selected(block=False)),
            ("Unblock", self.unblock_selected),
            ("Open folder", self.open_folder),
            ("Export archive.txt...", self.export_archive),
        ):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        v.addLayout(row)
        self.lib_info = QLabel("")
        v.addWidget(self.lib_info)
        return w

    def _lib_status(self, t) -> str:
        if t.status == BLOCKED:
            return "Deleted (blocked)"
        return "OK" if t.path and os.path.exists(t.path) else "File missing"

    def refresh_library(self) -> None:
        tracks = self.lib.all()
        self.lib_table.setRowCount(len(tracks))
        for r, t in enumerate(tracks):
            first = QTableWidgetItem(t.title)
            first.setData(KEY_ROLE, t.key)
            self.lib_table.setItem(r, 0, first)
            self.lib_table.setItem(r, 1, QTableWidgetItem(t.uploader))
            self.lib_table.setItem(r, 2, QTableWidgetItem(t.playlist))
            self.lib_table.setItem(r, 3, QTableWidgetItem(self._lib_status(t)))
        self._filter_library()

    def _filter_library(self) -> None:
        q = self.search.text().strip().lower()
        for r in range(self.lib_table.rowCount()):
            text = " ".join(self.lib_table.item(r, c).text() for c in range(3)).lower()
            self.lib_table.setRowHidden(r, bool(q) and q not in text)

    def _selected_keys(self) -> list[str]:
        rows = sorted({i.row() for i in self.lib_table.selectedIndexes()})
        return [self.lib_table.item(r, 0).data(KEY_ROLE) for r in rows]

    def delete_selected(self, block: bool) -> None:
        keys = self._selected_keys()
        if not keys:
            return
        what = ("will not be downloaded again while the archive option is on"
                if block else "can be downloaded again")
        if QMessageBox.question(
            self, "Delete tracks",
            f"Move {len(keys)} file(s) to the Trash? These tracks {what}.",
        ) != QMessageBox.StandardButton.Yes:
            return
        problems = 0
        for key in keys:
            t = self.lib.get(key)
            if t and t.path and os.path.exists(t.path) and not move_to_trash(t.path):
                problems += 1  # leave it untouched so library and disk stay in step
                continue
            self.lib.block(key) if block else self.lib.forget(key)
        self.refresh_library()
        self.lib_info.setText(f"{problems} file(s) could not be moved to the Trash and were kept."
                              if problems else f"Deleted {len(keys)} track(s).")

    def unblock_selected(self) -> None:
        n = 0
        for key in self._selected_keys():
            t = self.lib.get(key)
            if t and t.status == BLOCKED:
                self.lib.forget(key)
                n += 1
        self.refresh_library()
        self.lib_info.setText(f"Unblocked {n} track(s); they can be downloaded again.")

    def open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.folder.text()).expanduser())))

    def export_archive(self) -> None:
        dest, _ = QFileDialog.getSaveFileName(self, "Export archive", "archive.txt", "Text (*.txt)")
        if dest:
            n = self.lib.export_archive(Path(dest))
            self.lib_info.setText(f"Exported {n} entries (use with yt-dlp --download-archive).")


def main() -> None:
    app = QApplication(sys.argv)
    apply_theme(app)
    app.setApplicationName("tunegrab")
    app.setDesktopFileName("tunegrab")
    data = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    lib = Library(data / "library.db")
    win = MainWindow(lib)
    win.show()
    code = app.exec()
    lib.close()
    sys.exit(code)


if __name__ == "__main__":
    main()
