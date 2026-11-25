"""Website names from the browser add-on."""

import json
from collections import namedtuple
from importlib import resources

import pytest
from fastapi.testclient import TestClient

from beaconmap import paths, sites
from beaconmap.collector import Collector
from beaconmap.geo import GeoInfo
from beaconmap.server import create_app
from beaconmap.sites import SiteNames, clean_host, is_browser

Addr = namedtuple("Addr", "ip port")
PORT, TOKEN = 8765, "test-token-0123456789abcdef"
ORIGIN = f"http://127.0.0.1:{PORT}"


def test_only_browsers_get_site_names():
    assert is_browser("chrome.exe") and is_browser("msedge.exe") and is_browser("Google Chrome Helper")
    assert not is_browser("spotify.exe") and not is_browser("python.exe")


def test_host_names_are_checked():
    assert clean_host("Claude.AI.") == "claude.ai"
    assert clean_host("a" * 300 + ".com") == ""
    assert clean_host("<script>alert(1)</script>") == ""
    assert clean_host("has space.com") == "" and clean_host(None) == ""


def test_names_are_stored_limited_and_forgotten(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(sites.time, "monotonic", lambda: now[0])
    s = SiteNames()
    assert not s.connected()
    assert s.add("8.8.8.8", "dns.google") and s.add("[2606:4700::1111]", "one.one")
    assert not s.add("192.168.1.1", "router.local")   # local addresses are not the internet
    assert not s.add("8.8.8.8", "bad host") and not s.add("nonsense", "x.com")
    assert s.connected()
    now[0] += 5
    s.add("8.8.8.8", "newer.example")
    assert s.for_ips(["8.8.8.8", "9.9.9.9"]) == ["newer.example", "dns.google"]   # newest first
    for i in range(sites.MAX_NAMES_PER_IP + 5):
        s.add("1.2.3.4", f"h{i}.example")
    assert len(s.for_ips(["1.2.3.4"])) == sites.MAX_NAMES_SHOWN
    now[0] += sites.REMEMBER_SECONDS + 1
    s.prune()
    assert s.for_ips(["8.8.8.8"]) == [] and not s.connected()


class Geo:
    def lookup(self, ip):
        return GeoInfo(37.4, -122.1, "Mountain View", "United States", "US", 15169, "Google", False)

    def age_days(self):
        return 1

    def close(self):
        pass


def test_names_appear_on_browser_rows_only():
    c = Collector(Geo())
    c._connections = lambda: [(Addr("8.8.8.8", 443), 1, 1), (Addr("8.8.8.8", 443), 2, 1)]
    c.names.get = lambda pid: {1: "chrome.exe", 2: "spotify.exe"}[pid]
    c.sites.add("8.8.8.8", "dns.google")
    snap = c.poll()
    by_app = {g["app"]: g for g in snap["groups"]}
    assert by_app["chrome.exe"]["sites"] == ["dns.google"] and by_app["chrome.exe"]["browser"]
    assert by_app["spotify.exe"]["sites"] == [] and not by_app["spotify.exe"]["browser"]
    assert snap["addon"] is True


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    with TestClient(create_app(PORT, TOKEN, Geo()), base_url=ORIGIN, follow_redirects=False) as c:
        yield c


def test_addon_must_know_the_key(client):
    # the key is only handed to a page that is already let in
    assert client.get("/api/addon-key").status_code == 403
    client.cookies.set(f"beaconmap_{PORT}", TOKEN)
    key = client.get("/api/addon-key").json()
    assert key["app"] == "beaconmap" and key["port"] == PORT and key["key"] != TOKEN
    client.cookies.clear()

    report = {"sites": [{"ip": "8.8.8.8", "host": "dns.google"}, {"ip": "10.0.0.1", "host": "nas.local"}, "junk"]}
    ext = {"origin": "chrome-extension://abcdefghijklmnop"}
    assert client.post("/api/sites", json={**report, "key": "wrong"}, headers=ext).status_code == 403
    assert client.post("/api/sites", json=report, headers=ext).status_code == 400          # no key at all
    assert client.post("/api/sites", content=b"not json", headers=ext).status_code == 400
    assert client.post("/api/sites", json={**report, "key": key["key"]},
                       headers={"host": "evil.example:8765"}).status_code == 403            # DNS rebinding
    r = client.post("/api/sites", json={**report, "key": key["key"]}, headers=ext)
    assert r.status_code == 200 and r.json()["accepted"] == 1
    assert r.headers["access-control-allow-origin"] == ext["origin"]
    # a normal website gets no permission to read the answer
    r = client.post("/api/sites", json={**report, "key": key["key"]}, headers={"origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_addon_files_are_packaged_and_ask_for_little():
    folder = resources.files("beaconmap") / "extension"
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 3
    assert sorted(manifest["permissions"]) == ["alarms", "storage", "webRequest"]
    assert (folder / "background.js").is_file() and (folder / "pair.js").is_file()
    # the add-on must only ever talk to this computer
    code = (folder / "background.js").read_text(encoding="utf-8")
    assert "fetch(`http://127.0.0.1:" in code and code.count("fetch(") == 1
