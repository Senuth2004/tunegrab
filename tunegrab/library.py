"""The library: what was downloaded, and what the user deleted on purpose.

A track is identified by a key like "youtube dQw4w9WgXcQ" (the same format yt-dlp
uses in its --download-archive file), so the archive can be exported and reused
with the yt-dlp command line. Video downloads get a " video" suffix ("youtube abc video")
so the audio and the video of the same item are tracked separately.

Two states:
  downloaded  the file exists (or should exist) in the music folder
  blocked     the user deleted the file and asked never to download it again
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DOWNLOADED = "downloaded"
BLOCKED = "blocked"


@dataclass
class Track:
    key: str
    title: str
    uploader: str
    path: str
    playlist: str
    status: str


class Library:
    def __init__(self, db_path: Path):
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path)
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS tracks (
                   key      TEXT PRIMARY KEY,
                   title    TEXT NOT NULL DEFAULT '',
                   uploader TEXT NOT NULL DEFAULT '',
                   path     TEXT NOT NULL DEFAULT '',
                   playlist TEXT NOT NULL DEFAULT '',
                   status   TEXT NOT NULL,
                   added    REAL NOT NULL
               )"""
        )
        self.db.commit()

    @staticmethod
    def make_key(ie_key: Optional[str], video_id: str) -> str:
        return f"{(ie_key or 'generic').lower()} {video_id}"

    @staticmethod
    def is_video(key: str) -> bool:
        return key.endswith(" video")

    @staticmethod
    def _row(r) -> Track:
        return Track(*r)

    _COLS = "key, title, uploader, path, playlist, status"

    def get(self, key: str) -> Optional[Track]:
        r = self.db.execute(f"SELECT {self._COLS} FROM tracks WHERE key = ?", (key,)).fetchone()
        return self._row(r) if r else None

    def all(self) -> list[Track]:
        rows = self.db.execute(f"SELECT {self._COLS} FROM tracks ORDER BY added DESC").fetchall()
        return [self._row(r) for r in rows]

    def add_downloaded(self, key: str, title: str, uploader: str, path: str, playlist: str) -> None:
        self.db.execute(
            """INSERT INTO tracks (key, title, uploader, path, playlist, status, added)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                   title = excluded.title, uploader = excluded.uploader,
                   path = excluded.path, playlist = excluded.playlist,
                   status = excluded.status, added = excluded.added""",
            (key, title, uploader, path, playlist, DOWNLOADED, time.time()),
        )
        self.db.commit()

    def block(self, key: str) -> None:
        """File was deleted on purpose: remember the track so it is never fetched again."""
        self.db.execute("UPDATE tracks SET status = ?, path = '' WHERE key = ?", (BLOCKED, key))
        self.db.commit()

    def forget(self, key: str) -> None:
        """Remove the track entirely: it counts as new again and can be re-downloaded."""
        self.db.execute("DELETE FROM tracks WHERE key = ?", (key,))
        self.db.commit()

    def export_archive(self, dest: Path) -> int:
        """Write a yt-dlp compatible archive file (downloaded AND blocked tracks)."""
        keys: list[str] = []
        for (key,) in self.db.execute("SELECT key FROM tracks ORDER BY added"):
            key = key[: -len(" video")] if self.is_video(key) else key
            if key not in keys:
                keys.append(key)
        Path(dest).write_text("".join(k + "\n" for k in keys), encoding="utf-8")
        return len(keys)

    def close(self) -> None:
        self.db.close()
