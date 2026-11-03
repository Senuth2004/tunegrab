#!/usr/bin/env bash
# Adds Tunegrab to the KDE application launcher (run once, from the project folder).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
if [ -x "$here/Tunegrab" ]; then
    exec_line="\"$here/Tunegrab\""
elif [ -x "$here/dist/Tunegrab/Tunegrab" ]; then
    exec_line="\"$here/dist/Tunegrab/Tunegrab\""
else
    exec_line="\"$here/.venv/bin/python\" -m tunegrab"
fi
icon_source=""
for candidate in "$here/tunegrab.svg" "$here/tunegrab/assets/tunegrab.svg"; do
    if [ -f "$candidate" ]; then
        icon_source="$candidate"
        break
    fi
done
icon_name=audio-x-generic
if [ -n "$icon_source" ]; then
    icon_dir="$HOME/.local/share/icons/hicolor/scalable/apps"
    mkdir -p "$icon_dir"
    install -m 644 "$icon_source" "$icon_dir/tunegrab.svg"
    icon_name=tunegrab
fi
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/tunegrab.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Tunegrab
Comment=Download songs and playlists with cover art
Exec=$exec_line
Path=$here
Icon=$icon_name
Categories=AudioVideo;Audio;Network;
Terminal=false
StartupWMClass=tunegrab
DESKTOP
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
echo "Done - search for 'Tunegrab' in the launcher."
