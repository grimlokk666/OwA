"""Local scanner / SDR audio stream proxy stubs."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("ScannerProxy")

SCANNER_STREAM_URL = os.getenv("SCANNER_STREAM_URL", "")


async def stream_status() -> dict[str, Any]:
    return {
        "label": "Dispatch Primary",
        "url": SCANNER_STREAM_URL or None,
        "status": "ONLINE" if SCANNER_STREAM_URL else "UNCONFIGURED",
    }
