# Tunegrab

A small desktop app for **KDE Plasma and Linux** that downloads songs and whole playlists as audio
files with **cover art and tags**, remembers what you already have, and keeps itself up to date.
It is a Qt front end for [yt-dlp](https://github.com/yt-dlp/yt-dlp), so it follows your Plasma
colour scheme automatically.

<!-- Add a screenshot: save one to docs/screenshot.png and uncomment the next line.
![Tunegrab](docs/screenshot.png)
-->

> **Status: early (0.2).** The download and update pipelines are covered by automated tests that run
> against a local test server, but the app has had little testing against live sites. Please open an
> issue if something breaks.

## Features

- **One song or a whole playlist** from the same box. "Song only" ignores the `&list=` part of a link.
- **Pick tracks** with checkboxes: all, none, or only the new ones.
- **Formats:** m4a (AAC), opus or mp3.
- **Cover art is always embedded**, optionally centre-cropped to a square, plus title and artist tags.
- **Download archive:** every download is recorded, so known tracks are skipped next time.
- **Library tab** with search. Deleting moves the file to the Trash and you choose:
  *never download again* (the track stays in the archive) or *allow re-download*.
- **Update tab:** updates yt-dlp, mutagen and Tunegrab itself from inside the app.
- **Export** the archive as a yt-dlp compatible `archive.txt`.

## Installation

### Requirements

| What | Why |
|---|---|
| Python 3.10 or newer | runs the app |
| ffmpeg **and** ffprobe | converts audio and embeds cover art |
| PySide6 (Qt 6) | the window (installed by pip below) |
| yt-dlp, mutagen | downloading; mutagen is needed for cover art in `.opus` files (installed by pip below) |

### Fedora (KDE) - step by step

**1. Install the system packages**

```bash
sudo dnf install git python3 ffmpeg-free
```

`ffmpeg-free` is enough for m4a and opus. If mp3 conversion fails, switch to the full ffmpeg from
RPM Fusion (see [Troubleshooting](#troubleshooting)).

**2. Get the code**

```bash
git clone https://github.com/Senuth2004/tunegrab.git
cd tunegrab
```

No git? Download the ZIP from the green **Code** button on GitHub, unzip it and `cd` into the folder.

**3. Create a virtual environment and install the Python packages**

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

If pip cannot find PySide6 for your Python version, use Fedora's own package instead:

```bash
sudo dnf install python3-pyside6
rm -rf .venv
python3 -m venv --system-site-packages .venv
.venv/bin/pip install yt-dlp mutagen
```

**4. Run it**

```bash
.venv/bin/python -m tunegrab
```

**5. Add it to the application launcher (optional)**

```bash
./install-launcher.sh
```

Then search for "Tunegrab" in the KDE launcher. Run the script again if you move the folder.

### Other distributions

The steps are the same, only the system packages differ:

| Distribution | Command |
|---|---|
| Debian / Ubuntu | `sudo apt install git python3-venv ffmpeg` |
| Arch / Manjaro | `sudo pacman -S git python ffmpeg` |
| openSUSE | `sudo zypper install git python3 ffmpeg` |

Then continue with steps 2 to 5 above. Under GNOME or other desktops it works too; it just uses
that desktop's Qt styling.

## Using it

1. Paste a song or playlist link and press **Enter** (or **Fetch**).
2. Tick the tracks you want. With *Skip tracks already in the archive* on, known tracks start unticked.
3. Choose the format and the folder (default `~/Music/Tunegrab`). Playlists get their own sub-folder.
4. Press **Download selected**. A desktop notification appears when it is done (needs `notify-send`, which most KDE installs have).

Files are named `Title [id].ext`. The id stops two songs with the same title from overwriting each
other; change `FILENAME_TEMPLATE` in `tunegrab/downloader.py` if you prefer another pattern.

### The archive and deleting songs

Tunegrab keeps a small database in `~/.local/share/tunegrab/library.db`.

| Action (Library tab) | File | Track in archive |
|---|---|---|
| **Delete - never download again** | moved to the Trash | kept, so it is skipped from now on |
| **Delete - allow re-download** | moved to the Trash | removed, counts as new again |
| **Unblock** | - | removes a "never again" entry |

Files you delete in Dolphin show up as *File missing*. **Export archive.txt** writes a file you can
use with `yt-dlp --download-archive`.

## Updating

Open the **Update** tab:

- **Check for updates** compares your versions with the newest ones. It also runs when the app
  starts (you can switch that off).
- **Update everything** installs what is outdated and offers to restart.

What gets updated, and from where:

| Component | Source |
|---|---|
| yt-dlp, mutagen | PyPI (`pip install --upgrade` in the app's own environment) |
| Tunegrab itself | the latest **GitHub release** of the repo entered under *Update source* (for example `Senuth2004/tunegrab`) |
| ffmpeg, PySide6 | your system: `sudo dnf upgrade` |

yt-dlp is the one to keep current. Sites change often and downloads stop working until yt-dlp is
updated, so if downloads suddenly fail, update first.

**Safety of the self-update:** HTTPS only (also for redirects), size limits, zip paths are checked,
the downloaded code is never run before it replaces the old one, and the old version is kept in
`.backup/tunegrab-<version>` (to roll back, copy it back over the `tunegrab/` folder). Updates are
blocked while downloads are running.

**Running from a git clone?** The in-app updater refuses to overwrite a clone. Update it with
`git pull` and restart. The in-app app-update is meant for copies installed from a ZIP.

## Troubleshooting

**"ffmpeg is missing" dialog** - install it: `sudo dnf install ffmpeg-free` (Fedora).

**MP3 conversion fails on Fedora** - use the full ffmpeg from [RPM Fusion](https://rpmfusion.org):

```bash
sudo dnf install https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm
sudo dnf swap ffmpeg-free ffmpeg --allowerasing
```

Or pick m4a or opus, which need no extra codecs.

**Downloads suddenly fail** - update yt-dlp in the Update tab (or `.venv/bin/pip install -U yt-dlp`).

**No cover art in `.opus` files** - make sure `mutagen` is installed (it is in `requirements.txt`).

**"Could not load the Qt platform plugin xcb"** - install the missing Qt library:
`sudo dnf install xcb-util-cursor` (Fedora) or `sudo apt install libxcb-cursor0` (Debian/Ubuntu).

**Deleting says a file could not be moved to the Trash** - Tunegrab then leaves the file and the
library untouched. It uses Qt's Trash support and falls back to `gio trash`; check that `gio` is installed.

## Development

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q tests
```

The tests cover the library, link parsing, the window logic and the updater. The pipeline test needs
ffmpeg and ffprobe: it runs the real yt-dlp + ffmpeg chain against a local web server (no internet)
for every format and cover type and checks the finished file with ffprobe.

```
tunegrab/
  __main__.py     entry point (python -m tunegrab)
  main.py         Qt window: download, library and update tabs
  downloader.py   yt-dlp wrapper (no Qt)
  library.py      SQLite library and archive (no Qt)
  updater.py      PyPI and GitHub updates (no Qt)
tests/            pytest suite
install-launcher.sh   adds Tunegrab to the KDE launcher
```

### Publishing a new version

1. Raise `__version__` in `tunegrab/__init__.py` and add a line to `CHANGELOG.md`.
2. Commit, then tag and push: `git tag v0.3.0 && git push origin main --tags`
3. On GitHub open **Releases -> Draft a new release**, choose the tag and publish
   (or `gh release create v0.3.0 --title "Tunegrab 0.3.0" --notes "What changed"`).

GitHub's automatic source ZIP is enough; the updater only needs a zip that contains the `tunegrab/`
package folder. Installed copies then offer the update on their next check.

## Responsible use

Tunegrab only automates what yt-dlp already does. Download only what you are allowed to: your own
uploads, Creative Commons or royalty-free music, or content a site explicitly lets you download.
Many sites forbid downloading in their terms, and copyright law differs by country; you are
responsible for how you use this tool. It is not affiliated with YouTube or any other service.

## Credits and licence

Built on [yt-dlp](https://github.com/yt-dlp/yt-dlp), [FFmpeg](https://ffmpeg.org),
[Qt for Python (PySide6)](https://doc.qt.io/qtforpython-6/) and [mutagen](https://github.com/quodlibet/mutagen).
Released under the [MIT licence](LICENSE).
