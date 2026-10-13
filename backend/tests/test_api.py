"""API hardening: health, envelope auth, bounds, and read-token checks."""

from __future__ import annotations

import base64
import json
import os
import sqlite3
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient

from database import _db_path, init_db, maintenance
from main import app

TOKEN = os.environ["ALERT_TOKEN"]
KEY = base64.b64decode(os.environ["TELEMETRY_ENCRYPTION_KEY"])
AUTH = {"X-Overwatch-Token": TOKEN}


def _point(**overrides: object) -> dict:
    base: dict = {
        "ts": "2026-10-13T12:00:00.000Z",
        "deviceId": "device-1",
        "callsign": "ALPHA-1",
        "lat": 40.5,
        "lon": -84.5,
        "alt": 250.0,
        "accuracy": 8.0,
        "heading": 180.0,
        "speed": 0.0,
        "battery": 87,
        "charging": False,
        "source": "capacitor",
    }
    base.update(overrides)
    return base


def _envelope(point: dict, key: bytes = KEY) -> dict:
    iv = b"0123456789ab"
    ciphertext = AESGCM(key).encrypt(iv, json.dumps(point).encode(), None)
    return {
        "v": "sovereign-aes-gcm-v1",
        "deviceId": point["deviceId"],
        "callsign": point["callsign"],
        "iv": base64.b64encode(iv).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
        "ts": point["ts"],
    }


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health(client: TestClient):
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "operational"
    assert body["sovereign_mode"] is True


def test_plaintext_rejected(client: TestClient):
    res = client.post("/api/telemetry", json=_point())
    assert res.status_code == 401
    assert "encrypted envelope" in res.json()["detail"]


def test_valid_envelope_accepted(client: TestClient):
    point = _point(deviceId="device-accepted", lat=41.25, lon=-81.5)
    res = client.post("/api/telemetry", json=_envelope(point))
    assert res.status_code == 200
    assert res.json()["accepted"] == 1

    latest = client.get("/api/telemetry/latest", headers=AUTH)
    assert latest.status_code == 200
    stored = next(p for p in latest.json()["points"] if p["deviceId"] == "device-accepted")
    assert stored["lat"] == pytest.approx(41.25)
    assert stored["lon"] == pytest.approx(-81.5)
    assert stored["encrypted"] is True


def test_envelope_without_key_is_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TELEMETRY_ENCRYPTION_KEY", "")
    before = client.get("/api/telemetry/latest", headers=AUTH).json()["points"]
    res = client.post("/api/telemetry", json=_envelope(_point(deviceId="no-key")))
    assert res.status_code == 401
    assert res.json()["detail"] == "encryption key not configured"
    after = client.get("/api/telemetry/latest", headers=AUTH).json()["points"]
    assert [p["deviceId"] for p in after] == [p["deviceId"] for p in before]
    assert all(not (p["lat"] == 0 and p["lon"] == 0 and p["deviceId"] == "no-key") for p in after)


def test_bounds_validation(client: TestClient):
    res = client.post("/api/telemetry", json=_envelope(_point(lat=95)))
    assert res.status_code == 422

    lon = client.post("/api/telemetry", json=_envelope(_point(lon=200)))
    assert lon.status_code == 422

    huge = client.post(
        "/api/telemetry",
        json=_envelope(_point(deviceId="x" * 80)),
    )
    assert huge.status_code == 422


def test_read_endpoints_require_token(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    async def no_pois(*_args, **_kwargs):
        return []

    monkeypatch.setattr("main.osm_pois.query_local_osm_pois", no_pois)

    reads = [
        ("/api/telemetry/latest", {}),
        ("/api/pois", {"lat": 40.0, "lon": -80.0}),
        ("/api/cameras", {"lat": 40.0, "lon": -80.0}),
        ("/api/adsb", {}),
        ("/api/scanner", {}),
    ]
    for path, params in reads:
        denied = client.get(path, params=params)
        assert denied.status_code == 401, path
        wrong = client.get(path, params=params, headers={"X-Overwatch-Token": "nope"})
        assert wrong.status_code == 401, path
        allowed = client.get(path, params=params, headers=AUTH)
        assert allowed.status_code == 200, path


def test_alert_requires_token(client: TestClient):
    body = {"level": "info", "message": "check", "source": "test"}
    assert client.post("/api/alert", json=body).status_code == 401
    ok = client.post("/api/alert", json=body, headers=AUTH)
    assert ok.status_code == 200
    assert ok.json()["status"] == "alert_dispatched"


def test_sqlite_wal_migration_and_backup():
    import asyncio

    asyncio.run(init_db())
    asyncio.run(maintenance(365, 14, 30))

    con = sqlite3.connect(_db_path())
    try:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 1
        assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        con.close()

    backups = list(Path(os.environ["BACKUP_DIR"]).glob("overwatch-*.db"))
    assert len(backups) == 1
