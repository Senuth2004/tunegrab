import http.server
import json
import shutil
import subprocess
import threading
import zipfile
from pathlib import Path

import pytest

from tunegrab import updater
from tunegrab.updater import Checks, Status, UpdateError


def test_version_compare():
    assert updater.is_newer("0.2.0", "0.1.9")
    assert updater.is_newer("v1.0", "0.9.9")
    assert updater.is_newer("2026.10.27", "2026.10.26")
    assert not updater.is_newer("0.2", "0.2.0")        # same version, different length
    assert not updater.is_newer("0.1.0", "0.2.0")      # never downgrade


def test_only_https_or_loopback():
    updater._check_url("https://api.github.com/x")
    updater._check_url("http://127.0.0.1:8000/x")
    for bad in ("http://example.com/x", "ftp://example.com/x", "file:///etc/passwd"):
        with pytest.raises(UpdateError):
            updater._check_url(bad)


@pytest.fixture()
def fake_github(tmp_path):
    """A local stand-in for the GitHub API plus a downloadable release zip."""
    z = tmp_path / "release.zip"
    make_zip(z, "0.3.0")
    state = {"release": None}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/repos/me/tunegrab/releases/latest" and state["release"]:
                body = json.dumps(state["release"]).encode()
                self.send_response(200)
            elif self.path == "/release.zip":
                body = z.read_bytes()
                self.send_response(200)
            else:
                body = b"{}"
                self.send_response(404)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    state["release"] = {"tag_name": "v0.3.0", "body": "Modern dark UI and cross-platform builds",
                        "assets": [{"name": "tunegrab-source.zip",
                                    "browser_download_url": f"{base}/release.zip"}],
                        "zipball_url": f"{base}/release.zip"}
    yield base, state
    srv.shutdown()


def make_zip(path: Path, version: str, extra: dict | None = None):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("tunegrab-main/tunegrab/__init__.py", f'__version__ = "{version}"\n')
        z.writestr("tunegrab-main/tunegrab/main.py", f"# main {version}\n")
        z.writestr("tunegrab-main/requirements.txt", "yt-dlp\n")
        for name, data in (extra or {}).items():
            z.writestr(name, data)


def make_install(tmp_path, version="0.2.0") -> Path:
    pkg = tmp_path / "app" / "tunegrab"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(f'__version__ = "{version}"\n')
    (pkg / "main.py").write_text("# old\n")
    return pkg


def test_latest_release_lookup(fake_github):
    base, state = fake_github
    rel = updater.latest_app_release("me/tunegrab", api_base=base)
    assert rel.version == "0.3.0" and rel.notes == "Modern dark UI and cross-platform builds"
    assert rel.url.endswith("/release.zip")
    with pytest.raises(UpdateError):
        updater.latest_app_release("me/does-not-exist", api_base=base)       # 404: no such repo/release
    with pytest.raises(UpdateError):
        updater.latest_app_release("not a repo", api_base=base)              # malformed source
    state["release"] = {"tag_name": "nightly", "assets": []}
    with pytest.raises(UpdateError):
        updater.latest_app_release("me/tunegrab", api_base=base)             # tag without a version


def test_release_lookup_ignores_binary_archives(fake_github):
    base, state = fake_github
    state["release"]["assets"] = [
        {"name": "Tunegrab-windows-x86_64.zip", "browser_download_url": f"{base}/release.zip"},
        {"name": "Tunegrab-linux-x86_64.tar.gz", "browser_download_url": f"{base}/release.zip"},
    ]
    state["release"]["zipball_url"] = f"{base}/release.zip"
    rel = updater.latest_app_release("me/tunegrab", api_base=base)
    assert rel.url == state["release"]["zipball_url"]
    linux = updater.latest_app_release(
        "me/tunegrab", api_base=base, asset_name="Tunegrab-linux-x86_64.tar.gz")
    assert linux.url.endswith("/release.zip")
    with pytest.raises(UpdateError, match="does not include"):
        updater.latest_app_release("me/tunegrab", api_base=base, asset_name="missing.zip")


def test_managed_asset_matches_supported_platforms(monkeypatch):
    monkeypatch.setattr(updater.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(updater.sys, "platform", "linux")
    assert updater.managed_asset_name() == "Tunegrab-linux-x86_64.tar.gz"
    monkeypatch.setattr(updater.sys, "platform", "win32")
    assert updater.managed_asset_name() == "Tunegrab-windows-x86_64.zip"
    monkeypatch.setattr(updater.sys, "platform", "darwin")
    with pytest.raises(UpdateError, match="not available"):
        updater.managed_asset_name()


def make_build_tar(path: Path, executable="Tunegrab/Tunegrab", content=b"new build"):
    import io
    import tarfile

    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo(executable)
        info.size = len(content)
        info.mode = 0o755
        archive.addfile(info, io.BytesIO(content))


def test_safe_extract_build_checks_tar_paths_and_executable(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.sys, "platform", "linux")
    archive = tmp_path / "build.tar.gz"
    make_build_tar(archive)
    extracted = updater._safe_extract_build(archive, tmp_path / "extract")
    assert (extracted / "Tunegrab").read_bytes() == b"new build"
    assert (extracted / "Tunegrab").stat().st_mode & 0o111

    unsafe = tmp_path / "unsafe.tar.gz"
    make_build_tar(unsafe, "../Tunegrab")
    with pytest.raises(UpdateError, match="unsafe path"):
        updater._safe_extract_build(unsafe, tmp_path / "unsafe")

    import io
    import tarfile
    symlink_archive = tmp_path / "symlink.tar.gz"
    with tarfile.open(symlink_archive, "w:gz") as tar:
        executable = tarfile.TarInfo("Tunegrab/Tunegrab")
        executable.size = 4
        executable.mode = 0o755
        tar.addfile(executable, io.BytesIO(b"app!"))
        link = tarfile.TarInfo("Tunegrab/alias")
        link.type = tarfile.SYMTYPE
        link.linkname = "Tunegrab"
        tar.addfile(link)
    extracted = updater._safe_extract_build(symlink_archive, tmp_path / "symlink")
    assert (extracted / "alias").is_symlink()
    assert (extracted / "alias").read_bytes() == b"app!"

    bad_link = tmp_path / "bad-link.tar.gz"
    with tarfile.open(bad_link, "w:gz") as tar:
        executable = tarfile.TarInfo("Tunegrab/Tunegrab")
        executable.size = 4
        executable.mode = 0o755
        tar.addfile(executable, io.BytesIO(b"app!"))
        link = tarfile.TarInfo("Tunegrab/escape")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        tar.addfile(link)
    with pytest.raises(UpdateError, match="unsafe symbolic link"):
        updater._safe_extract_build(bad_link, tmp_path / "bad-link")

    monkeypatch.setattr(updater.sys, "platform", "win32")
    windows_zip = tmp_path / "build.zip"
    with zipfile.ZipFile(windows_zip, "w") as archive:
        archive.writestr("Tunegrab/Tunegrab.exe", b"windows app")
    extracted = updater._safe_extract_build(windows_zip, tmp_path / "windows")
    assert (extracted / "Tunegrab.exe").read_bytes() == b"windows app"


def test_managed_update_downloads_and_schedules_matching_build(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater.sys, "platform", "linux")
    install = tmp_path / "Tunegrab"
    install.mkdir()
    (install / "Tunegrab").write_text("old")
    monkeypatch.setattr(updater.sys, "executable", str(install / "Tunegrab"))
    archive = tmp_path / "release.tar.gz"
    make_build_tar(archive)
    monkeypatch.setattr(updater, "download", lambda url, dest: shutil.copyfile(archive, dest))
    scheduled = []
    monkeypatch.setattr(updater, "_start_managed_update_helper",
                        lambda work, staged, root, version, pid:
                        scheduled.append((work, staged, root, version, pid)))
    logs = []
    updater.update_managed_app(updater.AppRelease("99.0.0", "", "https://example.com/release.tar.gz"),
                               logs.append)

    assert len(scheduled) == 1
    assert scheduled[0][1].is_dir() and (scheduled[0][1] / "Tunegrab").read_bytes() == b"new build"
    assert scheduled[0][2] == install
    assert "install it and relaunch" in logs[-1]


def test_linux_update_helper_script_has_valid_shell_syntax(tmp_path, monkeypatch):
    work = tmp_path / "update work"
    install = tmp_path / "app folder" / "Tunegrab"
    staged = work / "staged app"
    work.mkdir()
    install.parent.mkdir()
    staged.mkdir()
    commands = []
    real_popen = subprocess.Popen
    with monkeypatch.context() as patch:
        patch.setattr(updater.subprocess, "Popen", lambda command, **kwargs: commands.append(command))
        updater._start_managed_update_helper(work, staged, install, "0.3.3", 1234)

    assert commands[0][0] == "/bin/sh"
    checked = subprocess.run([commands[0][0], "-n", commands[0][1]], capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr


def test_windows_update_helper_waits_and_rolls_back(tmp_path, monkeypatch):
    work = tmp_path / "update work"
    install = tmp_path / "app folder" / "Tunegrab"
    staged = work / "staged app"
    work.mkdir()
    install.parent.mkdir()
    staged.mkdir()
    commands = []
    with monkeypatch.context() as patch:
        patch.setattr(updater.os, "name", "nt")
        patch.setattr(updater.subprocess, "Popen", lambda command, **kwargs: commands.append(command))
        updater._start_managed_update_helper(work, staged, install, "0.3.3", 1234)

    assert commands[0][0] == "powershell.exe"
    script = Path(commands[0][-1]).read_text()
    assert "Get-Process -Id $pidToWait" in script
    assert "Start-Process" in script and "Move-Item -LiteralPath $backup" in script


def test_download_respects_size_cap(fake_github, tmp_path):
    base, _ = fake_github
    with pytest.raises(UpdateError):
        updater.download(f"{base}/release.zip", tmp_path / "x.zip", max_bytes=10)


def test_install_swaps_package_and_keeps_backup(tmp_path):
    pkg = make_install(tmp_path)
    z = tmp_path / "u.zip"
    make_zip(z, "0.3.0")
    assert updater.install_app_update(z, "0.2.0", pkg) == "0.3.0"
    assert 'm' in (pkg / "main.py").read_text() and "0.3.0" in (pkg / "main.py").read_text()
    assert (pkg.parent / ".backup" / "tunegrab-0.2.0" / "main.py").read_text() == "# old\n"
    assert (pkg.parent / "requirements.txt").exists()
    assert not [p for p in pkg.parent.iterdir() if p.name.startswith(".update-")]   # scratch dir cleaned


def test_install_refuses_same_or_older(tmp_path):
    pkg = make_install(tmp_path, "0.3.0")
    z = tmp_path / "u.zip"
    make_zip(z, "0.3.0")
    with pytest.raises(UpdateError, match="not newer"):
        updater.install_app_update(z, "0.3.0", pkg)
    assert (pkg / "main.py").read_text() == "# old\n"


def test_install_rejects_path_traversal(tmp_path):
    pkg = make_install(tmp_path)
    z = tmp_path / "evil.zip"
    make_zip(z, "0.9.0", extra={"../../escaped.txt": "pwned"})
    with pytest.raises(UpdateError, match="unsafe"):
        updater.install_app_update(z, "0.2.0", pkg)
    assert not (tmp_path / "escaped.txt").exists() and not (tmp_path.parent / "escaped.txt").exists()
    assert (pkg / "main.py").read_text() == "# old\n"


def test_install_rejects_symlink_entries(tmp_path):
    pkg = make_install(tmp_path)
    archive = tmp_path / "symlink.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("source/tunegrab/__init__.py", '__version__ = "0.9.0"\n')
        zf.writestr("source/tunegrab/main.py", "# new\n")
        link = zipfile.ZipInfo("source/link")
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        zf.writestr(link, "../../escaped")
    with pytest.raises(UpdateError, match="unsupported file type"):
        updater.install_app_update(archive, "0.2.0", pkg)
    assert (pkg / "main.py").read_text() == "# old\n"
    assert not (tmp_path.parent / "escaped").exists()


@pytest.mark.parametrize("content", [b"this is not a zip", None])
def test_bad_zip_leaves_install_untouched(tmp_path, content):
    pkg = make_install(tmp_path)
    z = tmp_path / "bad.zip"
    if content is not None:
        z.write_bytes(content)
    else:                                   # valid zip, but no tunegrab package inside
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("readme.txt", "hi")
    with pytest.raises(UpdateError):
        updater.install_app_update(z, "0.2.0", pkg)
    assert (pkg / "main.py").read_text() == "# old\n"


def test_pip_installed_copy_is_not_self_updated(tmp_path):
    pkg = tmp_path / "venv" / "lib" / "site-packages" / "tunegrab"
    pkg.mkdir(parents=True)
    with pytest.raises(UpdateError, match="pip"):
        updater.install_app_update(tmp_path / "x.zip", "0.1.0", pkg)


def test_check_all_survives_individual_failures(monkeypatch):
    def fake_pypi(name):
        if name == "mutagen":
            raise UpdateError("offline")
        return "9999.1.1"
    monkeypatch.setattr(updater, "latest_pypi", fake_pypi)
    checks = updater.check_all("")                      # no app source configured
    by = {s.name: s for s in checks.statuses}
    assert by["yt-dlp"].outdated and by["mutagen"].error == "offline" and not by["mutagen"].outdated
    assert by["tunegrab"].latest is None and checks.release is None


def test_run_update_order_and_restart_flag(monkeypatch):
    calls = []
    monkeypatch.setattr(updater, "pip_upgrade", lambda pk, log: calls.append(("pip", pk)) or True)
    monkeypatch.setattr(updater, "download", lambda url, dest: calls.append(("download", url)) or dest.write_bytes(b""))
    monkeypatch.setattr(updater, "install_app_update", lambda z, cur: calls.append(("install", cur)) or "9.9.9")
    rel = updater.AppRelease("9.9.9", "", "https://x/y.zip")
    checks = Checks([Status("tunegrab", updater.__version__, "9.9.9"), Status("yt-dlp", "1", "2"),
                     Status("mutagen", "1.0", "1.0")], rel)
    assert updater.run_update(checks, lambda s: None) is True
    assert calls == [("pip", ["yt-dlp"]), ("download", "https://x/y.zip"), ("install", updater.__version__)]
    assert updater.run_update(Checks([Status("yt-dlp", "2", "2")]), lambda s: None) is False


def test_pip_failure_stops_update(monkeypatch):
    monkeypatch.setattr(updater, "pip_upgrade", lambda pk, log: False)
    checks = Checks([Status("yt-dlp", "1", "2")])
    with pytest.raises(UpdateError, match="pip"):
        updater.run_update(checks, lambda s: None)


def test_managed_install_must_be_updated_by_its_package(monkeypatch):
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    assert updater.is_managed_install()
    assert updater.run_update(Checks([Status("yt-dlp", "1", "2")]), lambda s: None) is False


def test_real_pypi_and_pip():
    """Needs internet; skipped when PyPI is not reachable."""
    try:
        latest = updater.latest_pypi("yt-dlp")
    except UpdateError:
        pytest.skip("PyPI not reachable")
    assert updater.version_tuple(latest)
    lines = []
    assert updater.pip_upgrade(["yt-dlp"], lines.append) is True      # already current: a no-op
    assert any("yt-dlp" in l for l in lines)


def test_git_clone_is_not_overwritten(tmp_path):
    pkg = make_install(tmp_path)
    (pkg.parent / ".git").mkdir()
    z = tmp_path / "u.zip"
    make_zip(z, "0.3.0")
    with pytest.raises(UpdateError, match="git pull"):
        updater.install_app_update(z, "0.2.0", pkg)
    assert (pkg / "main.py").read_text() == "# old\n"
