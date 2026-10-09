"""SQLite persistence for Sovereign Overwatch (local-first, no cloud DB)."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/overwatch.db")


def _db_path() -> Path:
    # sqlite:///./data/overwatch.db → ./data/overwatch.db
    raw = DATABASE_URL
    if raw.startswith("sqlite:///"):
        path = Path(raw.removeprefix("sqlite:///"))
    else:
        path = Path("./data/overwatch.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    db = await aiosqlite.connect(_db_path())
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


async def init_db() -> None:
    async with get_db() as db:
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
        await db.commit()
