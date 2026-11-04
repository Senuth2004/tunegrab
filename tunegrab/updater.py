"""Update Python dependencies and source installs, or replace packaged release builds.

No Qt in here. Safety rules for the self-update:
  * only HTTPS (plain http only for 127.0.0.1, used by the tests), including redirects
  * archives are unpacked into a scratch folder with path and size checks
  * source code is inspected before the swap; packaged updates are staged until the app exits
  * the previous app folder is kept as a backup
"""
from __future__ import annotations

import importlib.util
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Callable, Optional
from urllib.parse import urlparse

from . import __version__

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
DEPENDENCIES = ["yt-dlp", "mutagen"]  # updated from PyPI; PySide6 and ffmpeg belong to the system
GITHUB_API = "https://api.github.com"
PYPI_URL = "https://pypi.org/pypi/{name}/json"
MAX_DOWNLOAD = 512 * 1024 * 1024
MAX_UNPACKED = 1024 * 1024 * 1024
MAX_FILES = 20000
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


def is_managed_install() -> bool:
    """Return whether this is a frozen build or a package-manager-managed installation."""
    return bool(getattr(sys, "frozen", False) or os.environ.get("FLATPAK_ID"))


def managed_asset_name() -> str:
    """Return the release archive matching the supported packaged build platform."""
    if os.environ.get("FLATPAK_ID"):
        raise UpdateError("Update this Flatpak installation through your software center.")
    machine = platform.machine().lower()
    if machine not in ("x86_64", "amd64"):
        raise UpdateError(f"Automatic updates are not available for {machine or 'this architecture'}.")
    if sys.platform == "win32":
        return "Tunegrab-windows-x86_64.zip"
    if sys.platform.startswith("linux"):
        return "Tunegrab-linux-x86_64.tar.gz"
    raise UpdateError(f"Automatic updates are not available on {sys.platform}.")


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


def latest_app_release(
    repo: str, api_base: Optional[str] = None, asset_name: Optional[str] = None,
) -> AppRelease:
    if not REPO_RE.match(repo):
        raise UpdateError("The update source must look like owner/repo.")
    data = _get_json(f"{api_base or GITHUB_API}/repos/{repo}/releases/latest")
    tag = str(data.get("tag_name") or "")
    if not version_tuple(tag):
        raise UpdateError("The latest release has no version number in its tag (e.g. v0.3.0).")
    wanted_asset = asset_name or "tunegrab-source.zip"
    url = next((a.get("browser_download_url") for a in data.get("assets") or []
                if str(a.get("name", "")).lower() == wanted_asset.lower()), None)
    if asset_name is None:
        url = url or data.get("zipball_url")
    if not url:
        raise UpdateError(f"The latest release does not include {wanted_asset}.")
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
            asset = managed_asset_name() if is_managed_install() else None
            checks.release = latest_app_release(repo.strip(), asset_name=asset)
            app.latest = checks.release.version
        except UpdateError as exc:
            app.error = str(exc)
    checks.statuses.append(app)
    if is_managed_install():
        return checks
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
        with zipfile.ZipFile(zip_path) as zf:
            dest.mkdir(parents=True, exist_ok=True)
            base = dest.resolve()
            infos = zf.infolist()
            if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_UNPACKED:
                raise UpdateError("The update zip is unexpectedly large.")
            for info in infos:
                rel = PurePosixPath(info.filename)
                if (not info.filename or "\\" in info.filename or rel.is_absolute()
                        or ".." in rel.parts):
                    raise UpdateError("The update zip contains unsafe paths; nothing was changed.")
                target = (dest / Path(*rel.parts)).resolve()
                if target != base and base not in target.parents:
                    raise UpdateError("The update zip contains unsafe paths; nothing was changed.")
                mode = info.external_attr >> 16
                file_type = mode & 0o170000
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                elif file_type not in (0, 0o100000):
                    raise UpdateError("The update zip contains an unsupported file type.")
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
    except zipfile.BadZipFile as exc:
        raise UpdateError("The downloaded file is not a valid zip.") from exc
    except OSError as exc:
        raise UpdateError(f"Could not unpack the update zip: {exc}") from exc


def _safe_extract_build(archive: Path, dest: Path) -> Path:
    """Extract a platform build archive without following links or writing outside dest."""
    dest.mkdir(parents=True, exist_ok=True)
    base = dest.resolve()

    def target_for(name: str) -> Path:
        rel = PurePosixPath(name)
        if not name or "\\" in name or rel.is_absolute() or ".." in rel.parts:
            raise UpdateError("The update archive contains an unsafe path; nothing was changed.")
        target = (dest / Path(*rel.parts)).resolve()
        if target != base and base not in target.parents:
            raise UpdateError("The update archive contains an unsafe path; nothing was changed.")
        return target

    def check_link_target(name: str, linkname: str) -> None:
        if not linkname or "\\" in linkname:
            raise UpdateError("The update archive contains an unsafe symbolic link.")
        link = PurePosixPath(linkname)
        if link.is_absolute():
            raise UpdateError("The update archive contains an unsafe symbolic link.")
        parts = list(PurePosixPath(name).parent.parts)
        for part in link.parts:
            if part in ("", "."):
                continue
            if part == "..":
                if len(parts) <= 1:
                    raise UpdateError("The update archive contains an unsafe symbolic link.")
                parts.pop()
            else:
                parts.append(part)

    try:
        if archive.name.lower().endswith(".tar.gz"):
            with tarfile.open(archive, "r:gz") as tf:
                members = tf.getmembers()
                if len(members) > MAX_FILES or sum(m.size for m in members) > MAX_UNPACKED:
                    raise UpdateError("The update archive is unexpectedly large.")
                links = []
                for member in members:
                    target = target_for(member.name)
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif member.isfile():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        source = tf.extractfile(member)
                        if source is None:
                            raise UpdateError("The update archive contains an unreadable file.")
                        with source, target.open("xb") as output:
                            shutil.copyfileobj(source, output)
                        target.chmod(member.mode & 0o777)
                    elif member.issym():
                        check_link_target(member.name, member.linkname)
                        links.append((target, member.linkname))
                    else:
                        raise UpdateError("The update archive contains an unsupported file type.")
                for target, linkname in links:
                    os.symlink(linkname, target)
        else:
            with zipfile.ZipFile(archive) as zf:
                infos = zf.infolist()
                if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_UNPACKED:
                    raise UpdateError("The update archive is unexpectedly large.")
                for info in infos:
                    target = target_for(info.filename)
                    mode = info.external_attr >> 16
                    file_type = mode & 0o170000
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif file_type not in (0, 0o100000):
                        raise UpdateError("The update archive contains an unsupported file type.")
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as source, target.open("xb") as output:
                            shutil.copyfileobj(source, output)
                        if mode & 0o777:
                            target.chmod(mode & 0o777)
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise UpdateError(f"Could not unpack the update archive: {exc}") from exc

    app_dir = dest / "Tunegrab"
    executable = app_dir / ("Tunegrab.exe" if sys.platform == "win32" else "Tunegrab")
    if app_dir.is_symlink() or not app_dir.is_dir() or not executable.is_file():
        raise UpdateError("The update archive does not contain a valid Tunegrab application.")
    return app_dir


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _start_managed_update_helper(
    work_dir: Path, staged_app: Path, install_dir: Path, current_version: str, pid: int,
) -> None:
    backup = install_dir.with_name(
        f"{install_dir.name}.backup-{current_version}-{pid}-{uuid.uuid4().hex[:8]}")
    if os.name == "nt":
        script = work_dir / "install-update.ps1"
        script.write_text(
            "$ErrorActionPreference = 'Stop'\n"
            f"$install = {_ps_quote(str(install_dir))}\n"
            f"$staged = {_ps_quote(str(staged_app))}\n"
            f"$backup = {_ps_quote(str(backup))}\n"
            f"$pidToWait = {pid}\n"
            "while (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue) { "
            "Start-Sleep -Milliseconds 250 }\n"
            "Move-Item -LiteralPath $install -Destination $backup\n"
            "try { Move-Item -LiteralPath $staged -Destination $install } "
            "catch { Move-Item -LiteralPath $backup -Destination $install; throw }\n"
            "try { Start-Process -FilePath (Join-Path $install 'Tunegrab.exe') } "
            "catch { Remove-Item -LiteralPath $install -Recurse -Force; "
            "Move-Item -LiteralPath $backup -Destination $install; throw }\n"
            f"Remove-Item -LiteralPath {_ps_quote(str(work_dir))} -Recurse -Force\n",
            encoding="utf-8",
        )
        command = [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(script),
        ]
        options = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    else:
        script = work_dir / "install-update.sh"
        script.write_text(
            "#!/bin/sh\n"
            "set -eu\n"
            f"while kill -0 {pid} 2>/dev/null; do sleep 0.25; done\n"
            f"mv -- {shlex.quote(str(install_dir))} {shlex.quote(str(backup))}\n"
            f"if ! mv -- {shlex.quote(str(staged_app))} {shlex.quote(str(install_dir))}; then\n"
            f"  mv -- {shlex.quote(str(backup))} {shlex.quote(str(install_dir))}\n"
            "  exit 1\n"
            "fi\n"
            f"nohup {shlex.quote(str(install_dir / 'Tunegrab'))} >/dev/null 2>&1 </dev/null &\n"
            f"rm -rf -- {shlex.quote(str(work_dir))}\n",
            encoding="utf-8",
        )
        script.chmod(0o700)
        command = ["/bin/sh", str(script)]
        options = {"start_new_session": True}
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True, **options)


def update_managed_app(release: AppRelease, log: Callable[[str], None]) -> None:
    """Download a matching packaged build and schedule its replacement after this process exits."""
    install_dir = Path(sys.executable).resolve().parent
    if not install_dir.is_dir() or not os.access(install_dir.parent, os.W_OK):
        raise UpdateError(f"The app folder {install_dir} is not writable by this user.")
    if not is_newer(release.version, __version__):
        raise UpdateError(f"The download is version {release.version}, which is not newer than {__version__}.")
    log(f"Downloading Tunegrab {release.version}...")
    try:
        work_dir = Path(tempfile.mkdtemp(prefix=".tunegrab-update-", dir=install_dir.parent))
    except OSError as exc:
        raise UpdateError(f"Could not prepare the update next to {install_dir}: {exc}") from exc
    archive_name = Path(urlparse(release.url).path).name or "release.zip"
    archive = work_dir / archive_name
    try:
        download(release.url, archive)
        staged = _safe_extract_build(archive, work_dir / "unpacked")
        staged_app = work_dir / "staged-app"
        os.replace(staged, staged_app)
        _start_managed_update_helper(work_dir, staged_app, install_dir, __version__, os.getpid())
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
    log(f"Tunegrab {release.version} is ready. Closing the app will install it and relaunch Tunegrab.")


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
    if is_managed_install():
        app = next((s for s in checks.statuses if s.name == "tunegrab"), None)
        if app and app.outdated:
            if checks.release is None:
                raise UpdateError("No matching Tunegrab release was found to install.")
            update_managed_app(checks.release, log)
            return True
        return False
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
