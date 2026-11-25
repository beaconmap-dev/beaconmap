"""Session history: what this computer talked to, even after the connection closed."""

from collections import namedtuple

import pytest
from fastapi.testclient import TestClient

from beaconmap import history, paths
from beaconmap.collector import Collector
from beaconmap.geo import GeoInfo
from beaconmap.server import create_app

Addr = namedtuple("Addr", "ip port")
PORT, TOKEN = 8765, "test-token-0123456789abcdef"
ORIGIN = f"http://127.0.0.1:{PORT}"


class Geo:
    def lookup(self, ip):
        if ip == "9.9.9.9":
            return GeoInfo(47.4, 8.5, "Zurich", "Switzerland", "CH", 19281, "Quad9", False)
        return GeoInfo(17.4, 78.5, "Hyderabad", "India", "IN", 9498, "Bharti Airtel", False)

    def age_days(self):
        return 1

    def close(self):
        pass


def make(conns):
    c = Collector(Geo())
    c._connections = lambda: conns
    c.names.get = lambda pid: "chrome.exe"
    return c


def test_closed_connections_stay_in_history(monkeypatch):
    clock = [1_000_000.0]
    monkeypatch.setattr(history.time, "time", lambda: clock[0])
    conns = [(Addr("1.2.3.4", 443), 1, 1), (Addr("1.2.3.5", 443), 1, 1)]
    c = make(conns)
    c.sites.add("1.2.3.4", "cets.example.gov.in")
    c.poll()
    clock[0] += 30
    conns[:] = [(Addr("1.2.3.4", 443), 1, 1)]
    c.poll()
    clock[0] += 600
    conns.clear()
    c.poll()

    snap = c.history.snapshot()
    assert snap["total"] == 1
    e = snap["entries"][0]
    assert (e["app"], e["org"], e["city"], e["active"], e["peak"]) == ("chrome.exe", "Bharti Airtel", "Hyderabad", False, 2)
    assert e["first_seen"] == 1_000_000.0 and e["last_seen"] == 1_000_030.0   # last seen while still open
    assert e["sites"] == ["cets.example.gov.in"]


def test_live_entries_come_first_and_clear_empties_it():
    conns = [(Addr("1.2.3.4", 443), 1, 1)]
    c = make(conns)
    c.poll()
    conns[:] = [(Addr("9.9.9.9", 443), 1, 1)]
    c.poll()
    entries = c.history.snapshot()["entries"]
    assert [(e["org"], e["active"]) for e in entries] == [("Quad9", True), ("Bharti Airtel", False)]
    c.history.clear()
    assert c.history.snapshot()["total"] == 0


def test_history_is_bounded(monkeypatch):
    monkeypatch.setattr(history, "MAX_ENTRIES", 20)
    h = history.History()
    Group = namedtuple("Group", "id app org service cloud city country country_code lat lng worldwide threat count sites")
    for i in range(60):
        h.record([Group(f"g{i}", "a", "o", "", False, "c", "C", "CC", 0.0, 0.0, False, "", 1, [])])
    assert h.snapshot()["total"] <= 20
    assert h.snapshot()["entries"][0]["id"] == "g59"   # the newest is never the one dropped


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    with TestClient(create_app(PORT, TOKEN, Geo()), base_url=ORIGIN, follow_redirects=False) as c:
        yield c


def test_history_is_private_and_clearing_needs_the_right_origin(client):
    assert client.get("/api/history").status_code == 403           # not let in
    client.cookies.set(f"beaconmap_{PORT}", TOKEN)
    body = client.get("/api/history").json()
    assert set(body) == {"started", "now", "total", "entries"}
    assert client.post("/api/history/clear").status_code == 403    # another website can't wipe it
    assert client.post("/api/history/clear", headers={"origin": ORIGIN}).status_code == 200
