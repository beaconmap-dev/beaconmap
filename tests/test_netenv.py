"""VPN / proxy detection: only this computer's own settings are read."""

import socket
import ssl
import urllib.error
from collections import namedtuple

import pytest

from beaconmap import dbupdate, netenv

Stat = namedtuple("Stat", "isup")
Addr = namedtuple("Addr", "family address")


def fake_adapters(monkeypatch, stats, addrs, desc=None):
    monkeypatch.setattr(netenv.psutil, "net_if_stats", lambda: stats)
    monkeypatch.setattr(netenv.psutil, "net_if_addrs", lambda: addrs)
    monkeypatch.setattr(netenv, "_windows_descriptions", lambda: desc or {})
    monkeypatch.setattr(netenv, "_desc_cache", (frozenset(), {}))


def test_finds_a_connected_vpn_only(monkeypatch):
    v4 = [Addr(socket.AF_INET, "10.8.0.2")]
    fake_adapters(monkeypatch, {
        "NordLynx": Stat(True), "wg0": Stat(False),                       # down: ignored
        "utun3": Stat(True), "Tailscale": Stat(True), "Wi-Fi": Stat(True),
        "Ethernet 4": Stat(True), "Ethernet 3": Stat(True),
    }, {
        "NordLynx": v4, "wg0": v4, "Tailscale": v4, "Wi-Fi": v4, "Ethernet 3": v4, "Ethernet 4": v4,
        "utun3": [Addr(socket.AF_INET6, "fe80::1")],                       # idle macOS tunnel
    }, desc={"Ethernet 4": "TAP-Windows Adapter V9", "Ethernet 3": "VirtualBox Host-Only Ethernet Adapter"})
    assert netenv.vpn_adapters() == ["Ethernet 4", "NordLynx"]


def test_no_vpn_on_a_plain_network(monkeypatch):
    fake_adapters(monkeypatch, {"Wi-Fi": Stat(True)}, {"Wi-Fi": [Addr(socket.AF_INET, "192.168.1.5")]})
    assert netenv.vpn_adapters() == []


@pytest.mark.parametrize("proxies, shown", [
    ({}, ""),
    ({"https": "http://user:secret@proxy.corp:8080/"}, "proxy.corp:8080"),   # never show a password
    ({"http": "127.0.0.1:8888"}, "127.0.0.1:8888"),
    ({"no": "localhost"}, ""),
])
def test_system_proxy(monkeypatch, proxies, shown):
    monkeypatch.setattr(netenv.urllib.request, "getproxies", lambda: proxies)
    assert netenv.system_proxy() == shown


def test_download_retries_with_certifi_only_on_certificate_errors(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout, context=None):
        calls.append(context)
        if context is None:
            raise urllib.error.URLError(ssl.SSLCertVerificationError("unable to get local issuer certificate"))
        return "ok"

    monkeypatch.setattr(dbupdate.urllib.request, "urlopen", fake_urlopen)
    assert dbupdate._open("https://example.invalid/") == "ok"
    assert calls[0] is None and calls[1].verify_mode == ssl.CERT_REQUIRED   # still checked

    def offline(req, timeout, context=None):
        raise urllib.error.URLError(OSError("no network"))

    monkeypatch.setattr(dbupdate.urllib.request, "urlopen", offline)
    with pytest.raises(urllib.error.URLError):
        dbupdate._open("https://example.invalid/")
