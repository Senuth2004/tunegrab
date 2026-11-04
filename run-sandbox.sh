#!/usr/bin/env bash
# Run this source checkout with its own settings, library and download folders, so testing
# never touches the installed Tunegrab (its settings, library.db or archive).
#
#   ./run-sandbox.sh            start with an empty sandbox (or the one from last time)
#   ./run-sandbox.sh --copy     start from a copy of your real library (useful for Discover)
#   ./run-sandbox.sh --reset    delete the sandbox first
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
sandbox="${TUNEGRAB_SANDBOX:-$here/.sandbox}"

case "${1:-}" in
    --reset) rm -rf "$sandbox" ;;
    --copy)
        real="${XDG_DATA_HOME:-$HOME/.local/share}/tunegrab/library.db"
        mkdir -p "$sandbox/share/tunegrab"
        if [ -f "$real" ]; then
            cp "$real" "$sandbox/share/tunegrab/library.db"  # a copy: the real one is never written
            echo "Copied your library into the sandbox."
        else
            echo "No library found at $real; starting empty."
        fi ;;
    "") ;;
    *) echo "usage: $0 [--copy|--reset]" >&2; exit 2 ;;
esac

mkdir -p "$sandbox/config" "$sandbox/share" "$sandbox/Music" "$sandbox/Videos"
# Downloads go inside the sandbox too (only on first run, so changes you make in the app stick).
conf="$sandbox/config/tunegrab/tunegrab.conf"
if [ ! -f "$conf" ]; then
    mkdir -p "$(dirname "$conf")"
    printf '[General]\nfolder=%s\nvideo_folder=%s\nauto_check=false\n' \
        "$sandbox/Music" "$sandbox/Videos" > "$conf"
fi

echo "Sandbox: $sandbox"
cd "$here"
XDG_CONFIG_HOME="$sandbox/config" XDG_DATA_HOME="$sandbox/share" \
    exec "$here/.venv/bin/python" -m tunegrab
