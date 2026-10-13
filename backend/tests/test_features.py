"""Navigation proxy, OHGO cameras, OwnTracks ingest, and quiet ADS-B."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from main import app
from modules.nav_proxy import _normalize_trip
from modules.polyline import decode_polyline
from modules.traffic_cams import _is_public_https, normalize_ohgo, reset_cache

TOKEN = "test-alert-token"
AUTH = {"X-Overwatch-Token": TOKEN}


def _encode(points: list[tuple[float, float]]) -> str:
    prev_lat = 0
    prev_lon = 0
    chunks: list[str] = []

    def chunk(delta: int) -> str:
        value = ~(delta << 1) if delta < 0 else (delta << 1)
        chars: list[str] = []
        while value >= 0x20:
            chars.append(chr((0x20 | (value & 0x1F)) + 63))
            value >>= 5
        chars.append(chr(value + 63))
        return "".join(chars)

    for lat, lon in points:
        ilat = int(round(lat * 1_000_000))
        ilon = int(round(lon * 1_000_000))
        chunks.append(chunk(ilat - prev_lat))
        chunks.append(chunk(ilon - prev_lon))
        prev_lat, prev_lon = ilat, ilon
    return "".join(chunks)


@pytest.fixture
def client():
    reset_cache()
    with TestClient(app) as test_client:
        yield test_client
    reset_cache()


def test_polyline6_roundtrip():
    points = [(39.961176, -82.998794), (40.0, -83.01)]
    decoded = decode_polyline(_encode(points), 6)
    assert decoded[0][0] == pytest.approx(points[0][0], abs=1e-5)
    assert decoded[1][1] == pytest.approx(points[1][1], abs=1e-5)


def test_geocode_and_route_require_token_and_config(client: TestClient):
    assert client.get("/api/geocode", params={"q": "columbus ohio"}).status_code == 401
    denied = client.post(
        "/api/route",
        json={
            "origin": {"lat": 39.96, "lon": -82.99},
            "destination": {"lat": 40.0, "lon": -83.0},
            "profile": "auto",
        },
    )
    assert denied.status_code == 401
    missing = client.get("/api/geocode", params={"q": "columbus ohio"}, headers=AUTH)
    assert missing.status_code == 503
    assert missing.json()["detail"] == "geocoder not configured"
    unrouted = client.post(
        "/api/route",
        headers=AUTH,
        json={
            "origin": {"lat": 39.96, "lon": -82.99},
            "destination": {"lat": 40.0, "lon": -83.0},
            "profile": "bicycle",
        },
    )
    assert unrouted.status_code == 503
    bad = client.post(
        "/api/route",
        headers=AUTH,
        json={
            "origin": {"lat": 39.96, "lon": -82.99},
            "destination": {"lat": 40.0, "lon": -83.0},
            "profile": "rocket",
        },
    )
    assert bad.status_code == 422


def test_geocode_proxies_nominatim(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NOMINATIM_URL", "http://nominatim.test")

    class Response:
        status_code = 200

        def json(self):
            return [
                {"display_name": "Columbus, Ohio", "lat": "39.9612", "lon": "-82.9988"},
                {"display_name": "bad"},
            ]

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None, headers=None):
            assert url == "http://nominatim.test/search"
            assert params["q"] == "columbus"
            assert headers["User-Agent"].startswith("SovereignOverwatch")
            return Response()

    monkeypatch.setattr("modules.nav_proxy.httpx.AsyncClient", Client)
    res = client.get("/api/geocode", params={"q": "columbus"}, headers=AUTH)
    assert res.status_code == 200
    assert res.json()["results"] == [
        {"label": "Columbus, Ohio", "lat": 39.9612, "lon": -82.9988}
    ]


def test_route_normalizes_valhalla_polyline(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    shape = _encode([(39.96, -82.99), (39.97, -83.0), (40.0, -83.01)])
    trip = _normalize_trip(
        {
            "trip": {
                "summary": {"length": 4.2, "time": 300},
                "legs": [
                    {
                        "shape": shape,
                        "maneuvers": [
                            {
                                "instruction": "Drive north.",
                                "verbal_pre_transition_instruction": "Drive north on High Street.",
                                "length": 4.2,
                                "time": 300,
                                "begin_shape_index": 0,
                            }
                        ],
                    }
                ],
            }
        },
        "auto",
    )
    assert trip["steps"][0]["instruction"] == "Drive north on High Street."
    assert len(trip["coordinates"]) == 3

    monkeypatch.setenv("VALHALLA_URL", "http://valhalla.test")

    class Response:
        status_code = 200

        def json(self):
            return {
                "trip": {
                    "summary": {"length": 4.2, "time": 300},
                    "legs": [
                        {
                            "shape": shape,
                            "maneuvers": [
                                {
                                    "instruction": "Walk south.",
                                    "length": 1.0,
                                    "time": 600,
                                    "begin_shape_index": 1,
                                }
                            ],
                        }
                    ],
                }
            }

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None):
            assert url == "http://valhalla.test/route"
            assert json["costing"] == "pedestrian"
            return Response()

    monkeypatch.setattr("modules.nav_proxy.httpx.AsyncClient", Client)
    res = client.post(
        "/api/route",
        headers=AUTH,
        json={
            "origin": {"lat": 39.96, "lon": -82.99},
            "destination": {"lat": 40.0, "lon": -83.01},
            "profile": "pedestrian",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["profile"] == "pedestrian"
    assert body["steps"][0]["begin_index"] == 1
    assert body["coordinates"][0][0] == pytest.approx(39.96, abs=1e-5)


def test_cameras_without_key(client: TestClient):
    res = client.get("/api/cameras", params={"lat": 39.96, "lon": -82.99}, headers=AUTH)
    assert res.status_code == 200
    body = res.json()
    assert body["configured"] is False
    assert body["cameras"] == []
    snap = client.get("/api/cameras/view-1/snap", headers=AUTH)
    assert snap.status_code == 404


def test_ohgo_normalizer_drops_private_urls():
    kept = normalize_ohgo(
        {
            "totalPageCount": 1,
            "results": [
                {
                    "id": "site",
                    "latitude": 40.0,
                    "longitude": -83.0,
                    "location": "I-70",
                    "cameraViews": [
                        {
                            "id": "view-1",
                            "direction": "East",
                            "smallUrl": "https://cameras.example.com/east.jpg",
                            "mainRoute": "I-70",
                        }
                    ],
                }
            ],
        }
    )
    assert kept[0]["id"] == "view-1"
    assert kept[0]["name"] == "I-70 East"
    dropped = normalize_ohgo(
        {
            "results": [
                {
                    "id": "bad",
                    "latitude": 40,
                    "longitude": -83,
                    "smallUrl": "http://127.0.0.1/secret.jpg",
                },
                {
                    "id": "lan",
                    "latitude": 40,
                    "longitude": -83,
                    "smallUrl": "https://10.1.1.1/cam.jpg",
                },
            ]
        }
    )
    assert dropped == []
    assert _is_public_https("https://cameras.example.com/a.jpg") is True
    assert _is_public_https("https://127.0.0.1/a.jpg") is False


def test_ohgo_cache_120s(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OHGO_API_KEY", "test-key")
    monkeypatch.setenv("OHGO_API_URL", "https://ohgo.test/cameras")
    clock = {"now": 1_000.0}
    monkeypatch.setattr("modules.traffic_cams.time.time", lambda: clock["now"])
    calls = {"n": 0}

    class Response:
        def __init__(self, page: int):
            self.status_code = 200
            self._page = page

        def json(self):
            if self._page == 1:
                return {
                    "totalPageCount": 1,
                    "results": [
                        {
                            "id": "site",
                            "latitude": 39.96,
                            "longitude": -82.99,
                            "location": "Broad St",
                            "cameraViews": [
                                {
                                    "id": "view-1",
                                    "direction": "North",
                                    "smallUrl": "https://cameras.example.com/n.jpg",
                                }
                            ],
                        },
                        {
                            "id": "far",
                            "latitude": 41.5,
                            "longitude": -81.7,
                            "location": "Cleveland",
                            "cameraViews": [
                                {
                                    "id": "view-2",
                                    "direction": "South",
                                    "smallUrl": "https://cameras.example.com/s.jpg",
                                }
                            ],
                        },
                    ],
                }
            return {"totalPageCount": 1, "results": []}

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None, params=None):
            calls["n"] += 1
            assert headers["Authorization"] == "APIKEY test-key"
            return Response(int(params["page-number"]))

    monkeypatch.setattr("modules.traffic_cams.httpx.AsyncClient", Client)
    first = client.get("/api/cameras", params={"lat": 39.96, "lon": -82.99, "radius_km": 30}, headers=AUTH)
    assert first.status_code == 200
    body = first.json()
    assert body["configured"] is True
    assert body["status"] == "ok"
    assert [cam["id"] for cam in body["cameras"]] == ["view-1"]
    assert "snapshot_url" not in body["cameras"][0]
    second = client.get("/api/cameras", params={"lat": 39.96, "lon": -82.99}, headers=AUTH)
    assert second.status_code == 200
    assert calls["n"] == 1
    clock["now"] += 121
    third = client.get("/api/cameras", params={"lat": 39.96, "lon": -82.99}, headers=AUTH)
    assert third.status_code == 200
    assert calls["n"] == 2


def test_camera_snapshot_proxy(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from modules import traffic_cams

    traffic_cams._cache["ts"] = 10**12
    traffic_cams._cache["key"] = "test-key"
    traffic_cams._cache["status"] = "ok"
    traffic_cams._cache["items"] = [
        {
            "id": "view-1",
            "name": "Broad",
            "lat": 39.96,
            "lon": -82.99,
            "route": "I-71",
            "direction": "North",
            "snapshot_url": "https://cameras.example.com/n.jpg",
        }
    ]
    monkeypatch.setenv("OHGO_API_KEY", "test-key")
    monkeypatch.setattr("modules.traffic_cams._host_is_public", lambda host: host == "cameras.example.com")

    class Response:
        status_code = 200
        headers = {"content-type": "image/jpeg"}
        content = b"\xff\xd8\xff\xd9"

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None):
            assert url == "https://cameras.example.com/n.jpg"
            return Response()

    monkeypatch.setattr("modules.traffic_cams.httpx.AsyncClient", Client)
    denied = client.get("/api/cameras/view-1/snap")
    assert denied.status_code == 401
    ok = client.get("/api/cameras/view-1/snap", headers=AUTH)
    assert ok.status_code == 200
    assert ok.content == b"\xff\xd8\xff\xd9"
    assert ok.headers["content-type"].startswith("image/jpeg")
    missing = client.get("/api/cameras/nope/snap", headers=AUTH)
    assert missing.status_code == 404


def test_owntracks_bearer_and_basic_store_tid(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OWNTRACKS_TOKEN", "ot-secret")
    body = {
        "_type": "location",
        "tid": "K7",
        "lat": 39.11,
        "lon": -84.51,
        "tst": 1_760_000_000,
        "alt": 250,
        "acc": 12,
        "vel": 40,
        "cog": 90,
        "batt": 77,
        "bs": 2,
    }
    assert client.post("/api/tracking/owntracks", json=body).status_code == 401
    wrong = client.post(
        "/api/tracking/owntracks",
        json=body,
        headers={"Authorization": "Bearer nope"},
    )
    assert wrong.status_code == 401
    accepted = client.post(
        "/api/tracking/owntracks",
        json=body,
        headers={"Authorization": "Bearer ot-secret", "X-Limit-D": "iphone"},
    )
    assert accepted.status_code == 200
    assert accepted.json() == []
    basic = base64.b64encode(b"owntracks:ot-secret").decode()
    waypoint = client.post(
        "/api/tracking/owntracks",
        json={"_type": "waypoint", "desc": "home", "lat": 1, "lon": 2, "tid": "K7"},
        headers={"Authorization": f"Basic {basic}"},
    )
    assert waypoint.status_code == 200
    assert waypoint.json() == []
    empty = client.post(
        "/api/tracking/owntracks",
        content=b"",
        headers={"Authorization": "Bearer ot-secret"},
    )
    assert empty.status_code == 200
    latest = client.get("/api/telemetry/latest", headers=AUTH)
    stored = [p for p in latest.json()["points"] if p["callsign"] == "K7"]
    assert len(stored) == 1
    assert stored[0]["deviceId"] == "iphone"
    assert stored[0]["source"] == "owntracks"
    assert stored[0]["lat"] == pytest.approx(39.11)
    assert stored[0]["battery"] == pytest.approx(77)
    assert stored[0]["charging"] is True
    assert stored[0]["encrypted"] is False
    invalid = client.post(
        "/api/tracking/owntracks",
        json={"_type": "location", "tid": "K7", "lat": 95, "lon": 0, "tst": 1},
        headers={"Authorization": "Bearer ot-secret"},
    )
    assert invalid.status_code == 422


def test_adsb_without_receiver_is_quiet(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    offline = client.get("/api/adsb", headers=AUTH)
    assert offline.status_code == 200
    assert offline.json()["configured"] is True
    assert offline.json()["status"] == "offline"
    assert offline.json()["aircraft"] == []

    monkeypatch.setenv("DUMP1090_URL", "")
    quiet = client.get("/api/adsb", headers=AUTH)
    assert quiet.status_code == 200
    body = quiet.json()
    assert body["configured"] is False
    assert body["status"] == "no receiver configured"
    assert body["aircraft"] == []


def test_dashboard_uses_local_tiles_only():
    root = Path(__file__).resolve().parents[2]
    text = "\n".join(
        (root / rel).read_text()
        for rel in (
            "frontend/static/index.html",
            "frontend/static/js/dashboard.js",
            "frontend/static/js/nav.js",
        )
    )
    assert "tile.openstreetmap.org" not in text
    assert "/tiles/styles/basic-preview/" in text


def test_compose_pins_nav_images_on_localhost():
    root = Path(__file__).resolve().parents[2]
    text = (root / "docker-compose.yml").read_text()
    assert 'profiles: ["nav"]' in text
    assert ":latest" not in text
    assert "ghcr.io/valhalla/valhalla-scripted:3.9.1" in text
    assert "mediagis/nominatim:5.3.2" in text
    assert "maptiler/tileserver-gl:v5.6.0" in text
    assert "0.0.0.0:" not in text
    assert "127.0.0.1:${VALHALLA_PORT:-8002}:8002" in text
    assert '127.0.0.1:${NOMINATIM_PORT:-8089}:8080' in text
    assert '127.0.0.1:${TILES_PORT:-8090}:8080' in text
