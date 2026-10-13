"""SQLite persistence for Sovereign Overwatch (local-first, no cloud DB)."""

from __future__ import annotations

import asyncio
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/overwatch.db")

SCHEMA_VERSION = 1


def _db_path() -> Path:
    # sqlite:///./data/overwatch.db or sqlite:////app/data/overwatch.db
    raw = DATABASE_URL
    if raw.startswith("sqlite:///"):
        path = Path(raw.removeprefix("sqlite:///"))
    else:
        path = Path("./data/overwatch.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    db = await aiosqlite.connect(_db_path(), timeout=30)
    await db.execute("PRAGMA busy_timeout=30000")
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


async def init_db() -> None:
    async with get_db() as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                device_id TEXT NOT NULL,
                callsign TEXT NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                alt REAL,
                accuracy REAL,
                heading REAL,
                speed REAL,
                battery REAL,
                charging INTEGER,
                source TEXT,
                encrypted INTEGER DEFAULT 0,
                raw_envelope TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_telemetry_device_ts
            ON telemetry (device_id, ts DESC)
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_telemetry_created ON telemetry (created_at)"
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS poi_cache (
                id TEXT PRIMARY KEY,
                amenity TEXT,
                lat REAL,
                lon REAL,
                tags_json TEXT,
                fetched_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        # Migration hook: bump SCHEMA_VERSION and add ALTERs guarded by user_version.
        cur = await db.execute("PRAGMA user_version")
        row = await cur.fetchone()
        ver = int(row[0]) if row else 0
        if ver < 1:
            await db.execute("PRAGMA user_version = 1")
        await db.commit()


def _backup_sqlite(src: Path, dest: Path) -> None:
    source = sqlite3.connect(src)
    target = sqlite3.connect(dest)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


async def maintenance(retention_days: int, backup_keep: int, poi_cache_days: int = 30) -> None:
    """Delete old telemetry and POI cache rows, then keep a rolling SQLite backup."""
    async with get_db() as db:
        if retention_days > 0:
            await db.execute(
                "DELETE FROM telemetry WHERE created_at < datetime('now', ?)",
                (f"-{int(retention_days)} days",),
            )
        if poi_cache_days > 0:
            await db.execute(
                "DELETE FROM poi_cache WHERE fetched_at < datetime('now', ?)",
                (f"-{int(poi_cache_days)} days",),
            )
        await db.commit()
        checkpoint = await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        await checkpoint.fetchall()

    src = _db_path()
    bdir = Path(os.getenv("BACKUP_DIR", str(src.parent / "backups")))
    bdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    dest = bdir / f"overwatch-{stamp}.db"
    await asyncio.to_thread(_backup_sqlite, src, dest)

    existing = sorted(p for p in bdir.glob("overwatch-*.db") if p.is_file())
    keep = max(int(backup_keep), 0)
    stale = existing if keep == 0 else existing[:-keep]
    for old in stale:
        old.unlink(missing_ok=True)
