"""The three locks on the local web server: Host, Origin, and the access token."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from beaconmap import paths
from beaconmap.geo import GeoInfo
from beaconmap.server import create_app

PORT = 8765
HOST = f"127.0.0.1:{PORT}"
ORIGIN = f"http://{HOST}"
TOKEN = "test-token-0123456789abcdef"
COOKIE = f"beaconmap_{PORT}"


class FakeGeo:
    def lookup(self, ip):
        return GeoInfo(None, None, "", "", "", None, "Unknown", False)

    def age_days(self):
        return 12

    def close(self):
        pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    app = create_app(PORT, TOKEN, FakeGeo())
    with TestClient(app, base_url=ORIGIN, follow_redirects=False) as c:
        yield c


def let_in(client):
    client.cookies.set(COOKIE, TOKEN)


def test_rejects_unknown_host(client):
    let_in(client)
    r = client.get("/api/config", headers={"host": "evil.example:8765"})
    assert r.status_code == 403


def test_page_is_closed_without_the_token(client):
    assert client.get("/").status_code == 403
    assert client.get("/api/config").status_code == 403
    assert client.get("/?t=wrong").status_code == 403


def test_token_is_traded_for_a_cookie(client):
    r = client.get(f"/?t={TOKEN}")
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = r.headers["set-cookie"]
    assert f"{COOKIE}={TOKEN}" in cookie
    assert "httponly" in cookie.lower() and "samesite=strict" in cookie.lower()
    # the cookie alone now opens the page, and nothing is cached
    r = client.get("/")
    assert r.status_code == 200 and "BeaconMap" in r.text
    assert r.headers["cache-control"] == "no-cache"


def test_config_reports_database_age(client):
    let_in(client)
    body = client.get("/api/config").json()
    assert body["db_age_days"] == 12 and body["home"] is None


def test_saving_home_needs_the_right_origin(client):
    let_in(client)
    home = {"lat": 33.75, "lng": -84.39, "label": "Atlanta, US"}
    assert client.post("/api/home", json=home).status_code == 403
    assert client.post("/api/home", json=home, headers={"origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/home", json=home, headers={"origin": ORIGIN}).status_code == 200
    assert client.get("/api/config").json()["home"] == home


def test_saving_home_rejects_bad_input(client):
    let_in(client)
    h = {"origin": ORIGIN}
    assert client.post("/api/home", json={"lat": 200, "lng": 0}, headers=h).status_code == 400
    assert client.post("/api/home", json={"lat": "north"}, headers=h).status_code == 400
    assert client.post("/api/home", json=[1, 2], headers=h).status_code == 400


def ws_open(client, origin=None, cookie=True, host=HOST):
    headers = {"host": host}
    if origin:
        headers["origin"] = origin
    if cookie:
        headers["cookie"] = f"{COOKIE}={TOKEN}"
    with client.websocket_connect("/ws", headers=headers):
        return True


def test_live_feed_needs_host_origin_and_cookie(client):
    with pytest.raises(WebSocketDisconnect):
        ws_open(client, origin=ORIGIN, cookie=False)           # another account: no cookie
    with pytest.raises(WebSocketDisconnect):
        ws_open(client, origin="https://evil.example")         # another website
    with pytest.raises(WebSocketDisconnect):
        ws_open(client)                                        # no origin at all
    with pytest.raises(WebSocketDisconnect):
        ws_open(client, origin=ORIGIN, host="evil.example:8765")  # DNS rebinding
    assert ws_open(client, origin=ORIGIN)
