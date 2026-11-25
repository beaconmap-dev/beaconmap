"""The offline first guess at where this computer is."""

import socket
from collections import namedtuple

from beaconmap import collector
from beaconmap.geo import GeoInfo

Nic = namedtuple("Nic", "family address")


class Geo:
    def lookup(self, ip):
        if ip.startswith("2001:"):
            return GeoInfo(33.749, -84.388, "Atlanta", "United States", "US", 7922, "Comcast", False)
        if ip == "1.1.1.1":
            return GeoInfo(-33.8, 151.2, "Sydney", "Australia", "AU", 13335, "Cloudflare", True, worldwide=True)
        return GeoInfo(None, None, "", "", "", None, "Unknown", False)


def guess(monkeypatch, addresses):
    monkeypatch.setattr(collector.psutil, "net_if_addrs", lambda: {"Wi-Fi": addresses})
    return collector.guess_home(Geo())


def test_uses_this_computers_public_address(monkeypatch):
    home = guess(monkeypatch, [
        Nic(socket.AF_INET, "192.168.1.20"),            # behind the router: not usable
        Nic(socket.AF_INET6, "fe80::1%12"),             # link-local: not usable
        Nic(socket.AF_INET6, "2001:558:6000::5"),
    ])
    assert home == {"label": "Atlanta, US", "lat": 33.75, "lng": -84.39}


def test_no_guess_behind_an_ordinary_router(monkeypatch):
    assert guess(monkeypatch, [Nic(socket.AF_INET, "192.168.1.20"), Nic(socket.AF_INET6, "fe80::1")]) is None


def test_no_guess_from_unplaceable_or_worldwide_addresses(monkeypatch):
    assert guess(monkeypatch, [Nic(socket.AF_INET, "9.9.9.9")]) is None
    assert guess(monkeypatch, [Nic(socket.AF_INET, "1.1.1.1")]) is None


def test_a_failing_system_call_is_not_fatal(monkeypatch):
    def boom():
        raise OSError("no network stack")
    monkeypatch.setattr(collector.psutil, "net_if_addrs", boom)
    assert collector.guess_home(Geo()) is None
