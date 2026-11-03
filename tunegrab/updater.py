"""Updating: Python dependencies from PyPI, and Tunegrab itself from a GitHub release.

No Qt in here. Safety rules for the self-update:
  * only HTTPS (plain http only for 127.0.0.1, used by the tests), including redirects
  * the zip is unpacked into a scratch folder with path-traversal checks and size limits
  * downloaded code is never executed or imported before the swap: the version is read as text
  * the old package folder is kept in .backup/ and restored automatically if the swap fails
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from . import __version__

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
DEPENDENCIES = ["yt-dlp", "mutagen"]  # updated from PyPI; PySide6 and ffmpeg belong to the system
GITHUB_API = "https://api.github.com"
PYPI_URL = "https://pypi.org/pypi/{name}/json"
MAX_DOWNLOAD = 50 * 1024 * 1024
MAX_UNPACKED = 150 * 1024 * 1024
MAX_FILES = 5000
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class UpdateError(Exception):
    """Something went wrong; the message is meant to be shown to the user."""


# ---------------------------------------------------------------- versions
def version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def is_newer(latest: str, current: str) -> bool:
    a, b = version_tuple(latest), version_tuple(current)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def installed_version(name: str) -> Optional[str]:
    if name == "tunegrab":
        return __version__
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


# ---------------------------------------------------------------- network
def _check_url(url: str) -> None:
    p = urlparse(url)
    if p.scheme == "https" or (p.scheme == "http" and p.hostname in ("127.0.0.1", "localhost")):
        return
    raise UpdateError(f"Refusing to use a non-HTTPS address: {url}")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SafeRedirect)


def _open(url: str, timeout: float = 20):
    _check_url(url)
    req = urllib.request.Request(url, headers={
        "User-Agent": f"tunegrab/{__version__}", "Accept": "application/vnd.github+json, */*"})
    try:
        return _opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"The server answered {exc.code} {exc.reason} for {urlparse(url).netloc}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Network problem: {getattr(exc, 'reason', exc)}") from exc


def _get_json(url: str) -> dict:
    with _open(url) as resp:
        try:
            return json.loads(resp.read(2_000_000))
        except ValueError as exc:
            raise UpdateError("The server sent something that is not JSON.") from exc


def download(url: str, dest: Path, max_bytes: int = MAX_DOWNLOAD) -> None:
    got = 0
    with _open(url, timeout=60) as resp, open(dest, "wb") as out:
        while chunk := resp.read(64 * 1024):
            got += len(chunk)
            if got > max_bytes:
                raise UpdateError("The download is larger than expected; stopped.")
            out.write(chunk)


def latest_pypi(name: str) -> str:
    try:
        return _get_json(PYPI_URL.format(name=name))["info"]["version"]
    except (KeyError, TypeError) as exc:
        raise UpdateError(f"PyPI has no usable answer for {name}.") from exc


@dataclass
class AppRelease:
    version: str
    notes: str
    url: str


def latest_app_release(repo: str, api_base: Optional[str] = None) -> AppRelease:
    if not REPO_RE.match(repo):
        raise UpdateError("The update source must look like owner/repo.")
    data = _get_json(f"{api_base or GITHUB_API}/repos/{repo}/releases/latest")
    tag = str(data.get("tag_name") or "")
    if not version_tuple(tag):
        raise UpdateError("The latest release has no version number in its tag (e.g. v0.3.0).")
    url = next((a.get("browser_download_url") for a in data.get("assets") or []
                if str(a.get("name", "")).lower().endswith(".zip")), None) or data.get("zipball_url")
    if not url:
        raise UpdateError("The latest release has no zip file.")
    return AppRelease(tag.lstrip("vV"), str(data.get("body") or ""), url)


# ---------------------------------------------------------------- checking
@dataclass
class Status:
    name: str
    installed: Optional[str]
    latest: Optional[str] = None
    error: str = ""

    @property
    def outdated(self) -> bool:
        return bool(self.latest and (self.installed is None or is_newer(self.latest, self.installed)))


@dataclass
class Checks:
    statuses: list = field(default_factory=list)
    release: Optional[AppRelease] = None

    @property
    def outdated(self) -> list:
        return [s for s in self.statuses if s.outdated]


def check_all(repo: str = "") -> Checks:
    """Look up the newest versions. Each lookup fails on its own without stopping the others."""
    checks = Checks()
    app = Status("tunegrab", __version__)
    if repo.strip():
        try:
            checks.release = latest_app_release(repo.strip())
            app.latest = checks.release.version
        except UpdateError as exc:
            app.error = str(exc)
    checks.statuses.append(app)
    for name in DEPENDENCIES:
        st = Status(name, installed_version(name))
        try:
            st.latest = latest_pypi(name)
        except UpdateError as exc:
            st.error = str(exc)
        checks.statuses.append(st)
    return checks


# ---------------------------------------------------------------- installing
def pip_upgrade(packages: list, log: Callable[[str], None]) -> bool:
    if importlib.util.find_spec("pip") is None:
        raise UpdateError("pip is not available in this Python environment.")
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--disable-pip-version-check", *packages]
    log("$ " + " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert proc.stdout is not None
    for line in proc.stdout:
        log(line.rstrip())
    return proc.wait() == 0


def _safe_extract(zip_path: Path, dest: Path) -> None:
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise UpdateError("The downloaded file is not a valid zip.") from exc
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_UNPACKED:
            raise UpdateError("The update zip is unexpectedly large.")
        base = dest.resolve()
        for info in infos:
            target = (dest / info.filename).resolve()
            if target != base and base not in target.parents:
                raise UpdateError("The update zip contains unsafe paths; nothing was changed.")
        zf.extractall(dest)


def _find_package(extracted: Path) -> Path:
    found = [p.parent for p in extracted.rglob("__init__.py")
             if p.parent.name == "tunegrab" and (p.parent / "main.py").exists()]
    if not found:
        raise UpdateError("The update zip does not contain the tunegrab package.")
    return min(found, key=lambda p: len(p.parts))


def _read_version(pkg: Path) -> str:
    m = re.search(r"""__version__\s*=\s*['"]([^'"]+)['"]""", (pkg / "__init__.py").read_text("utf-8"))
    if not m or not version_tuple(m.group(1)):
        raise UpdateError("Could not read the version of the downloaded update.")
    return m.group(1)


def install_app_update(zip_path: Path, current_version: str, package_dir: Path = PACKAGE_DIR) -> str:
    """Replace the package folder with the one from the zip; returns the new version."""
    package_dir = Path(package_dir)
    root = package_dir.parent
    if {"site-packages", "dist-packages"} & set(package_dir.parts):
        raise UpdateError("Tunegrab was installed with pip; update it with pip instead.")
    if (root / ".git").exists():
        raise UpdateError("This copy is a git clone; update it with 'git pull' instead.")
    if not os.access(root, os.W_OK):
        raise UpdateError(f"The app folder {root} is not writable.")
    work = Path(tempfile.mkdtemp(prefix=".update-", dir=root))  # same filesystem, so the swap is a rename
    try:
        _safe_extract(zip_path, work)
        new_pkg = _find_package(work)
        new_version = _read_version(new_pkg)  # read as text: downloaded code is not run before the swap
        if not is_newer(new_version, current_version):
            raise UpdateError(f"The download is version {new_version}, which is not newer than {current_version}.")
        backup_dir = root / ".backup"
        backup_dir.mkdir(exist_ok=True)
        backup = backup_dir / f"tunegrab-{current_version}"
        if backup.exists():
            shutil.rmtree(backup)
        os.replace(package_dir, backup)
        try:
            os.replace(new_pkg, package_dir)
        except Exception:
            os.replace(backup, package_dir)  # put the old version back
            raise
        for extra in ("requirements.txt", "README.md"):
            src = new_pkg.parent / extra
            if src.exists():
                shutil.copy2(src, root / extra)
        return new_version
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_update(checks: Checks, log: Callable[[str], None]) -> bool:
    """Apply everything that is outdated. Returns True when a restart is needed."""
    changed = False
    deps = [s.name for s in checks.outdated if s.name != "tunegrab"]
    if deps:
        log(f"Updating {', '.join(deps)} from PyPI...")
        if not pip_upgrade(deps, log):
            raise UpdateError("pip could not update the packages (see the log above).")
        changed = True
    app = next((s for s in checks.statuses if s.name == "tunegrab"), None)
    if app and app.outdated and checks.release:
        log(f"Downloading Tunegrab {checks.release.version}...")
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "update.zip"
            download(checks.release.url, zip_path)
            new = install_app_update(zip_path, __version__)
        log(f"Tunegrab updated to {new}. The previous version is kept in .backup/.")
        changed = True
    return changed
