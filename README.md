# Tunegrab

A cross-platform desktop app for **Linux and Windows** that downloads songs, videos and whole
playlists from **YouTube, Facebook and Instagram**, as audio files with **cover art and tags** or as
**mp4/mkv videos**, and remembers what you already have. It is built with Qt
and [yt-dlp](https://github.com/yt-dlp/yt-dlp), with light and dark themes.

<!-- Add a screenshot: save one to docs/screenshot.png and uncomment the next line.
![Tunegrab](docs/screenshot.png)
-->

> **Status: early development.** Automated tests cover the library, UI, updater and download
> pipeline. Automated release builds are configured for Linux and Windows; please report
> platform-specific problems in the issue tracker.

## Features

- **YouTube, Facebook and Instagram:** videos, reels, playlists and multi-video posts.
- **One item or a whole playlist** from the same box. "Single item only" ignores the `&list=` part of a link.
- **Pick tracks** with checkboxes: all, none, or only the new ones.
- **Audio formats:** m4a (AAC), opus or mp3.
- **Video formats:** mp4 (best, up to 1080p, 720p or 480p) or mkv (best quality, any codec). Video
  and audio are merged without re-encoding, and the thumbnail and title are embedded. Videos are saved
  to their own folder (default `~/Videos/Tunegrab`).
- **Sign-in cookies:** for Instagram and Facebook posts that need you to be signed in, Tunegrab can
  use the cookies of a browser you are already signed in with.
- **Light and dark modes:** switch themes from the **View** menu; your choice is remembered.
- **Cover art is always embedded**, optionally centre-cropped to a square, plus title and artist tags.
- **Download archive:** every download is recorded, so known tracks are skipped next time.
- **Discover tab:** music suggestions from YouTube's Mixes for the songs you downloaded, with no
  account or API key. Songs you already have or deleted are left out.
- **Library tab** with search. Deleting moves the file to the Trash and you choose:
  *never download again* (the track stays in the archive) or *allow re-download*.
- **Update tab:** source installs can update yt-dlp and mutagen. Install a newer app release to
  update Tunegrab itself.
- **Export** the archive as a yt-dlp compatible `archive.txt`.

## Installation

### Requirements

| What | Why |
|---|---|
| Python 3.10 or newer | runs from source |
| FFmpeg | converts audio, merges video and embeds cover art. Bundled with Windows ready-to-run builds. |
| PySide6 (Qt 6) | the window (included in the source-install dependencies) |
| yt-dlp, mutagen | downloading and cover art in `.opus` files (included in the source-install dependencies) |

### Fedora (KDE) - run from source

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

### Other Linux distributions

The steps are the same, only the system packages differ:

| Distribution | Command |
|---|---|
| Debian / Ubuntu | `sudo apt install git python3-venv ffmpeg` |
| Arch / Manjaro | `sudo pacman -S git python ffmpeg` |
| openSUSE | `sudo zypper install git python3 ffmpeg` |

Then continue with steps 2 to 5 above. Other Linux desktops are supported too.

### Ready-to-run builds (Linux and Windows)

The project builds separate Linux and Windows archives for tagged releases. If no release is listed
on the [GitHub Releases page](https://github.com/Senuth2004/tunegrab/releases), install from source
using the steps below.

Download and extract the archive for your operating system. On Linux, run `./Tunegrab`, or run
`./install-launcher.sh` from the extracted folder to add Tunegrab to KDE's application launcher.
On Windows, run `Tunegrab.exe` from the extracted folder. Packaged builds include Python and the
app's Python dependencies; the Windows build also includes FFmpeg, so no separate Python or FFmpeg
installation is needed. Linux builds use the system FFmpeg.

### Windows

Install Python 3.10 or newer and FFmpeg, then get the source and install dependencies:

```powershell
winget install Gyan.FFmpeg.Shared
git clone https://github.com/Senuth2004/tunegrab.git
cd tunegrab
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m tunegrab
```

Restart your terminal after installing FFmpeg so it is available on `PATH`.

## Using it

1. Paste a YouTube, Facebook or Instagram link and press **Enter** (or **Fetch**).
2. Tick the items you want. With *Skip tracks already in the archive* on, known items start unticked.
   Audio and video downloads are tracked separately, so having the song does not skip the video.
3. Choose an audio or video format and the folder (default `~/Music/Tunegrab` for audio,
   `~/Videos/Tunegrab` for video). Playlists get their own sub-folder.
4. Press **Download selected**. A desktop notification appears when it is done (needs `notify-send`, which most KDE installs have).

If Instagram or Facebook says you must log in, sign in with your browser, choose that browser under
**Sign-in cookies from**, and fetch again. Cookies are read locally by yt-dlp and are not stored by
Tunegrab. Private posts only work for an account that can see them.

Files are named `Title [id].ext`. The id stops two songs with the same title from overwriting each
other; change `FILENAME_TEMPLATE` in `tunegrab/downloader.py` if you prefer another pattern.

### Music suggestions (Discover tab)

1. Download a few songs from YouTube first; suggestions start from your most recent YouTube downloads.
2. Open **Discover** and press **Suggest music**. Tunegrab reads YouTube's Mix (the related-songs
   radio) for each of those songs. Songs that come early in a Mix, or that several of your songs'
   Mixes agree on, rank first. Shorts, long compilations, other uploads of songs you already have,
   and more than three songs from one channel are left out.
3. Tick the ones you like and press **Add selected to Download tab**, then download as usual with any
   audio or video format.

No account or API key is needed. Facebook and Instagram downloads are not used as seeds.

### The archive and deleting songs

Tunegrab keeps its library database in the platform's application-data folder (for example,
`~/.local/share/tunegrab/library.db` on Linux).

| Action (Library tab) | File | Track in archive |
|---|---|---|
| **Delete - never download again** | moved to the Trash | kept, so it is skipped from now on |
| **Delete - allow re-download** | moved to the Trash | removed, counts as new again |
| **Unblock** | - | removes a "never again" entry |

Files deleted outside Tunegrab show up as *File missing*. **Export archive.txt** writes a file you
can use with `yt-dlp --download-archive`.

## Updating

Open the **Update** tab to check for a newer Tunegrab release. In source installs, the tab also
checks yt-dlp and mutagen. The update source defaults to `Senuth2004/tunegrab` and can be changed
to another GitHub `owner/repository`.

- **Check for updates** checks the newest Tunegrab release. It also runs when the app starts (you
  can switch that off).
- In a source install, **Update everything** installs outdated Python dependencies and offers to
  restart.
- In a packaged Linux or Windows install, **Install update** downloads the matching release build,
  closes Tunegrab, replaces the app, and relaunches it. The previous app folder is kept as a backup.
  The install folder must be writable by your user. This updater is not for Flatpak or system package
  manager installs.

What gets updated, and from where:

| Component | Source |
|---|---|
| yt-dlp, mutagen | PyPI (`pip install --upgrade` in the source installation's Python environment) |
| Tunegrab itself | download the latest source archive or platform build from GitHub Releases |
| ffmpeg, PySide6 | your system package manager |

yt-dlp is the one to keep current. Sites change often and downloads stop working until yt-dlp is
updated, so if downloads suddenly fail, update first.

**Safety of dependency updates:** pip is run in the source installation's Python environment.
Packaged apps download the platform-specific archive over HTTPS and validate its paths before
installing it. Only the Tunegrab release is updated; system components such as ffmpeg and PySide6
remain under your system package manager.

**Running from a git clone?** The in-app updater refuses to overwrite a clone. Update it with
`git pull` and restart. Packaged builds update Tunegrab and its bundled Python dependencies together.
To enable in-app updating, users of an older packaged release must install the first release with
the automatic updater manually; later releases can be applied from the Update tab.

## Troubleshooting

**"ffmpeg is missing" dialog** - install FFmpeg and make sure `ffmpeg` is on `PATH`. On Fedora,
use `sudo dnf install ffmpeg-free`. The Windows release build includes FFmpeg; Windows source
installs need a separate FFmpeg installation.

**TLS certificate verification failed** - check that your system date and time are correct and
your system CA certificates are current. On Fedora, run
`sudo dnf reinstall ca-certificates && sudo update-ca-trust`. Tunegrab keeps HTTPS certificate
verification enabled.

**MP3 conversion fails on Fedora** - use the full ffmpeg from [RPM Fusion](https://rpmfusion.org):

```bash
sudo dnf install https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm
sudo dnf swap ffmpeg-free ffmpeg --allowerasing
```

Or pick m4a or opus, which need no extra codecs.

**Instagram or Facebook: "login required" or "rate-limit reached"** - pick your browser under
**Sign-in cookies from** (sign in to the site in that browser first). On Chrome-based browsers, close
the browser if its cookie database is locked. Stories and private posts always need sign-in.

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
  theme.py        shared dark theme
  downloader.py   yt-dlp wrapper (no Qt)
  library.py      SQLite library and archive (no Qt)
  updater.py      PyPI and GitHub updates (no Qt)
  recommend.py    music suggestions from YouTube Mixes (no Qt)
packaging/        frozen-app entry point
tests/            pytest suite
.github/workflows/ builds and tests Linux and Windows releases
install-launcher.sh   adds a Linux build to the KDE launcher
```

### Publishing a new version

1. Update `__version__` in `tunegrab/__init__.py` and add a section to `CHANGELOG.md`.
2. Push the changes to `main`, then create and push a matching version tag, for example:
   `git tag v0.3.0 && git push origin main --tags`.
3. The workflow tests the project, builds Linux and Windows archives, and attaches them to a GitHub
   release. Users download and install the new archive for their platform; source checkouts can
   update with `git pull`.

## Responsible use

Tunegrab only automates what yt-dlp already does. Download only what you are allowed to: your own
uploads, Creative Commons or royalty-free music, or content a site explicitly lets you download.
Many sites forbid downloading in their terms, and copyright law differs by country; you are
responsible for how you use this tool. It is not affiliated with YouTube, Facebook, Instagram or any other service.

## Credits and licence

Built on [yt-dlp](https://github.com/yt-dlp/yt-dlp), [FFmpeg](https://ffmpeg.org),
[Qt for Python (PySide6)](https://doc.qt.io/qtforpython-6/) and [mutagen](https://github.com/quodlibet/mutagen).
Released under the [MIT licence](LICENSE).
