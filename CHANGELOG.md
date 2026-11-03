# Changelog

## 0.3.2
- Enabled update-source editing and update checks in packaged builds; release updates now open the download page.
- Added a Tunegrab application icon for the window and KDE launcher.
- Removed the obsolete quote from KDE launcher working-directory generation.

## 0.3.1
- Fixed TLS certificate verification in Linux release builds by using the system CA store.
- Fixed download button state and selection behavior when fetching or changing tracks.
- Fixed quoting of the KDE launcher working directory.

## 0.3.0
- Added a consistent modern dark theme across Linux and Windows.
- Added standalone Linux and Windows release builds.
- Packaged apps now direct users to install updates through new releases.

## 0.2.0
- New **Update** tab: updates yt-dlp and mutagen from PyPI, and Tunegrab itself from a GitHub release.
- Self-update is HTTPS-only, checks zip paths and sizes, keeps a `.backup/`, and refuses to overwrite a git clone.

## 0.1.0
- Download a song or a whole playlist as m4a, opus or mp3, with tags and embedded cover art (optional square crop).
- Download archive that remembers what was downloaded; "never download again" vs "allow re-download" deletes.
- Library tab with search, Trash-based deleting, missing-file detection and yt-dlp compatible archive export.
