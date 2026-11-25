"""Is a VPN or a proxy in the way?

When one is on, apps talk to the VPN/proxy server instead of the real
servers, so the map shows that one place instead of where data really goes.
We only look at this computer's own settings: nothing is sent anywhere.
"""

from __future__ import annotations

import re
import socket
import sys
import time
import urllib.request

import psutil

# Adapter names that full-tunnel VPN apps create.
VPN_NAME = re.compile(
    r"vpn|wireguard|\bwg\d|nordlynx|wintun|tap-windows|\btap\d|\btun\d|\bppp\d|ipsec|mullvad|proton|"
    r"surfshark|expressvpn|cloudflare warp|\bwarp\b|cisco anyconnect|globalprotect|pangp|fortinet|zscaler",
    re.IGNORECASE,
)
# Mesh/virtual networks that don't carry all traffic by default: not worth a warning.
NOT_VPN = re.compile(r"tailscale|zerotier|hamachi|virtualbox|vmware|vethernet|hyper-v|wsl|docker|loopback",
                     re.IGNORECASE)

CHECK_EVERY_SECONDS = 15


_NET_CLASS = "{4D36E972-E325-11CE-BFC1-08002BE10318}"


def _windows_descriptions() -> dict[str, str]:
    """Windows names adapters "Ethernet 4"; the driver description says what
    they really are ("TAP-Windows Adapter V9"). Read-only registry lookup."""
    if sys.platform != "win32":
        return {}
    import winreg

    def subkeys(key):
        i = 0
        while True:
            try:
                yield winreg.EnumKey(key, i)
            except OSError:
                return
            i += 1

    hklm = winreg.HKEY_LOCAL_MACHINE
    by_guid, out = {}, {}
    try:
        with winreg.OpenKey(hklm, rf"SYSTEM\CurrentControlSet\Control\Class\{_NET_CLASS}") as k:
            for sub in subkeys(k):
                try:
                    with winreg.OpenKey(k, sub) as s:
                        guid = winreg.QueryValueEx(s, "NetCfgInstanceId")[0].upper()
                        by_guid[guid] = winreg.QueryValueEx(s, "DriverDesc")[0]
                except OSError:
                    continue
        with winreg.OpenKey(hklm, rf"SYSTEM\CurrentControlSet\Control\Network\{_NET_CLASS}") as k:
            for guid in subkeys(k):
                try:
                    with winreg.OpenKey(k, guid + r"\Connection") as c:
                        out[winreg.QueryValueEx(c, "Name")[0]] = by_guid.get(guid.upper(), "")
                except OSError:
                    continue
    except OSError:
        return {}
    return out


_desc_cache: tuple[frozenset, dict] = (frozenset(), {})


def _descriptions(names) -> dict[str, str]:
    global _desc_cache
    key = frozenset(names)
    if key != _desc_cache[0]:      # only re-read when adapters come or go
        _desc_cache = (key, _windows_descriptions())
    return _desc_cache[1]


def vpn_adapters() -> list[str]:
    """Names of VPN adapters that are up and have an IPv4 address."""
    try:
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
    except (OSError, RuntimeError):
        return []
    desc = _descriptions(stats)
    found = []
    for name, st in stats.items():
        label = f"{name} {desc.get(name, '')}"
        if not st.isup or not VPN_NAME.search(label) or NOT_VPN.search(label):
            continue
        # macOS keeps idle utun/tun adapters around with only IPv6 link-local
        # addresses; a connected VPN hands out an IPv4 one.
        if any(a.family == socket.AF_INET and not a.address.startswith("169.254.") for a in addrs.get(name, [])):
            found.append(name)
    return sorted(found)


def system_proxy() -> str:
    """The proxy this computer is set to use (OS settings or environment), or ''."""
    try:
        proxies = urllib.request.getproxies()
    except (OSError, ValueError):
        return ""
    for scheme in ("https", "http", "all", "socks"):
        value = proxies.get(scheme)
        if value:
            # show host:port only, never a username/password inside the URL
            value = re.sub(r"^[a-z0-9+]+://", "", value, flags=re.IGNORECASE)
            return value.rsplit("@", 1)[-1].rstrip("/")
    return ""


class NetworkCheck:
    """Re-checks now and then; the answer rarely changes."""

    def __init__(self) -> None:
        self._at = 0.0
        self._value = {"vpn": [], "proxy": ""}

    def get(self) -> dict:
        now = time.monotonic()
        if now - self._at >= CHECK_EVERY_SECONDS:
            self._at = now
            self._value = {"vpn": vpn_adapters(), "proxy": system_proxy()}
        return self._value
