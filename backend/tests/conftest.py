"""Test env must be set before main/database import their settings."""

from __future__ import annotations

import base64
import os
import tempfile

_root = tempfile.mkdtemp(prefix="overwatch-test-")
_key = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()

os.environ["DATABASE_URL"] = f"sqlite:///{_root}/overwatch.db"
os.environ["BACKUP_DIR"] = f"{_root}/backups"
os.environ["TELEMETRY_ENCRYPTION_KEY"] = _key
os.environ["ALERT_TOKEN"] = "test-alert-token"
os.environ["TELEMETRY_REQUIRE_KEY"] = "true"
os.environ["DISCORD_WEBHOOK_URL"] = ""
os.environ["CORS_ORIGINS"] = "http://127.0.0.1:3012"
os.environ["TELEMETRY_RETENTION_DAYS"] = "365"
os.environ["BACKUP_KEEP"] = "14"
os.environ["POI_CACHE_DAYS"] = "30"
os.environ["OVERWATCH_DISABLE_WORKERS"] = "1"
os.environ["DUMP1090_URL"] = "http://127.0.0.1:9/data/aircraft.json"
os.environ["SCANNER_STREAM_URL"] = ""
