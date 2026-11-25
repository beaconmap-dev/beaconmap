from collections import namedtuple

from beaconmap import collector
from beaconmap.collector import Collector, classify_ip
from beaconmap.geo import GeoInfo

Addr = namedtuple("Addr", "ip port")


def test_classify_ip():
    assert classify_ip("8.8.8.8") == ("8.8.8.8", True)
    assert classify_ip("192.168.1.10")[1] is False
    assert classify_ip("127.0.0.1")[1] is False
    assert classify_ip("::1")[1] is False
    assert classify_ip("fe80::1%eth0")[1] is False
    assert classify_ip("::ffff:8.8.8.8") == ("8.8.8.8", True)
    assert classify_ip("2606:4700:4700::1111")[1] is True
    assert classify_ip("not-an-ip")[1] is False


class FakeGeo:
    def lookup(self, ip):
        if ip == "9.9.9.9":
            return GeoInfo(None, None, "", "", "", None, "Unknown", False)
        return GeoInfo(37.4, -122.1, "Mountain View", "United States", "US", 15169, "Google", False)


def make(conns):
    c = Collector(FakeGeo())
    c._connections = lambda: conns
    c.names.get = lambda pid: {1: "chrome.exe"}.get(pid)
    return c


def test_groups_and_filters():
    c = make([
        (Addr("8.8.8.8", 443), 1, 1),
        (Addr("8.8.4.4", 443), 1, 1),
        (Addr("192.168.1.1", 80), 1, 1),   # LAN: counted, not mapped
        (Addr("9.9.9.9", 443), 1, 1),      # no location
        (None, 1, 1),                      # listening socket
    ])
    snap = c.poll()
    assert len(snap["groups"]) == 1
    g = snap["groups"][0]
    assert (g["app"], g["org"], g["count"], g["active"]) == ("chrome.exe", "Google", 2, True)
    assert snap["stats"]["local"] == 1
    assert snap["stats"]["unlocated"] == 1


def test_closed_connection_lingers_then_disappears(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(collector.time, "monotonic", lambda: now[0])
    conns = [(Addr("8.8.8.8", 443), 1, 1)]
    c = make(conns)
    c.poll()
    conns.clear()
    now[0] += 2
    g = c.poll()["groups"][0]
    assert g["active"] is False
    assert g["ips"] == ["8.8.8.8"]  # still shows where it was connected
    now[0] += collector.LINGER_SECONDS
    assert c.poll()["groups"] == []


def test_remembers_app_for_ownerless_socket():
    conns = [(Addr("8.8.8.8", 443), 1, 1)]
    c = make(conns)
    c.poll()
    conns[0] = (Addr("8.8.8.8", 443), 0, 1)  # e.g. TIME_WAIT: no owner
    assert c.poll()["groups"][0]["app"] == "chrome.exe"
