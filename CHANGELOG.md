# Changelog

## 0.4.0
- Added video downloads: mp4 (best, 1080p, 720p, 480p) and mkv, with merged audio, thumbnail and title.
- Added Facebook and Instagram support for videos, reels and multi-video posts, as audio or video.
- Added "Sign-in cookies from" to use a signed-in browser for posts that need a login.
- Video downloads use their own folder and are tracked separately from audio in the library; the
  Library tab shows the type. Exported `archive.txt` stays yt-dlp compatible.
- Login errors now explain how to fix them.
- New **Discover** tab: music suggestions from YouTube's Mixes for your recent downloads, with no
  account or API key. Songs already in the library (or deleted) are left out.

## 0.3.4
- Added automatic in-app updates for packaged Linux and Windows builds.
- Added safe staging and restart helpers so the running app is replaced only after it exits.
- The previous app directory is preserved as a backup during packaged updates.

## 0.3.3
- Bundled FFmpeg with the Windows release so users do not need to install it separately.
- Added a persistent Light mode option under the View menu.

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
