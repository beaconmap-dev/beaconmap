"""Collect live network connections and turn them into map-ready groups.

Only connection metadata is read (who talks to whom). No packets, no content.
"""

from __future__ import annotations

import hashlib
import socket
import sys
import time
from dataclasses import dataclass, field

import psutil

from .geo import GeoLookup
from .history import History
from .netaddr import classify_ip  # noqa: F401  (re-exported)
from .netenv import NetworkCheck
from .sites import SiteNames, is_browser

LINGER_SECONDS = 8.0       # keep closed connections on the map, fading out
NAME_RECHECK_SECONDS = 10.0
IP_APP_MEMORY_SECONDS = 300.0

SYSTEM_PIDS = {0: "System", 4: "System"} if sys.platform == "win32" else {0: "kernel"}


class ProcessNames:
    """PID -> app name cache, keyed by (pid, start time) so reused PIDs are never mislabeled."""

    def __init__(self) -> None:
        self._cache: dict[int, tuple[float, str, float]] = {}  # pid -> (create_time, name, checked_at)

    def get(self, pid: int | None) -> str | None:
        if not pid:
            return None  # pid 0/None: closed (TIME_WAIT) or hidden socket
        if pid in SYSTEM_PIDS:
            return SYSTEM_PIDS[pid]
        now = time.monotonic()
        cached = self._cache.get(pid)
        if cached and now - cached[2] < NAME_RECHECK_SECONDS:
            return cached[1]
        try:
            proc = psutil.Process(pid)
            created = proc.create_time()
            if cached and cached[0] == created:
                self._cache[pid] = (created, cached[1], now)
                return cached[1]
            name = proc.name()
        except psutil.NoSuchProcess:
            self._cache.pop(pid, None)
            return None
        except psutil.AccessDenied:
            name, created = f"pid {pid} (protected)", 0.0
        self._cache[pid] = (created, name, now)
        return name

    def prune(self, live_pids: set[int]) -> None:
        for pid in list(self._cache):
            if pid not in live_pids:
                del self._cache[pid]


@dataclass
class Group:
    """All connections from one app to one company in one city."""
    id: str
    app: str
    org: str
    asn: int | None
    cloud: bool
    city: str
    country: str
    country_code: str
    lat: float
    lng: float
    first_seen: float
    last_seen: float = 0.0
    count: int = 0
    ips: set[str] = field(default_factory=set)
    ports: set[int] = field(default_factory=set)
    protocols: set[str] = field(default_factory=set)
    ipv6: bool = False
    service: str = ""
    worldwide: bool = False
    threat: str = ""
    sites: list[str] = field(default_factory=list)   # website names, from the browser add-on

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "app": self.app,
            "org": self.org,
            "asn": self.asn,
            "cloud": self.cloud,
            "city": self.city,
            "country": self.country,
            "cc": self.country_code,
            "lat": self.lat,
            "lng": self.lng,
            "count": self.count,
            "ips": sorted(self.ips)[:20],
            "ports": sorted(self.ports)[:20],
            "protocols": sorted(self.protocols),
            "ipv6": self.ipv6,
            "service": self.service,
            "worldwide": self.worldwide,   # shared address: the city is only a guess
            "threat": self.threat,         # non-empty if on a known-bad list
            "sites": self.sites,
            "browser": is_browser(self.app),
            # False once every connection has closed. The group is then kept
            # for LINGER_SECONDS so the browser can fade it out.
            "active": self.count > 0,
        }


class Collector:
    def __init__(self, geo: GeoLookup) -> None:
        self.geo = geo
        self.names = ProcessNames()
        self.groups: dict[str, Group] = {}
        self.ip_app: dict[str, tuple[str, float]] = {}  # remember which app last used an IP
        self.limited = False  # True if the OS hid other apps' connections (needs admin/sudo)
        self.sites = SiteNames()
        self.history = History()
        self.network = NetworkCheck()

    def _connections(self) -> list[tuple]:
        """Return (remote addr, pid, socket type) for every connection we can see."""
        try:
            self.limited = False
            return [(c.raddr, c.pid, c.type) for c in psutil.net_connections(kind="inet")]
        except psutil.AccessDenied:
            # macOS without sudo: fall back to the processes we're allowed to see
            self.limited = True
            conns = []
            for proc in psutil.process_iter():
                try:
                    conns.extend((c.raddr, proc.pid, c.type) for c in proc.net_connections(kind="inet"))
                except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                    continue
            return conns

    def poll(self) -> dict:
        now = time.monotonic()
        conns = self._connections()

        # Rebuild each group's live details from scratch, but remember the old
        # ones: a group that just closed keeps showing where it was connected.
        previous = {gid: (g.ips, g.ports, g.protocols) for gid, g in self.groups.items()}
        for g in self.groups.values():
            g.count = 0
            g.ips, g.ports, g.protocols = set(), set(), set()

        local_ips: set[str] = set()
        unlocated = 0
        unnamed = 0
        live_pids: set[int] = set()

        for raddr, pid, sock_type in conns:
            if not raddr:
                continue  # listening sockets etc. aren't talking to anyone
            ip, public = classify_ip(raddr.ip)
            if not public:
                local_ips.add(ip)
                continue

            if pid:
                live_pids.add(pid)
            app = self.names.get(pid)
            if app:
                self.ip_app[ip] = (app, now)
            else:
                remembered = self.ip_app.get(ip)
                if remembered:
                    app = remembered[0]
                else:
                    app = "Unknown"
                    unnamed += 1

            info = self.geo.lookup(ip)
            if info.lat is None or info.lng is None:
                unlocated += 1
                continue

            lat, lng = round(info.lat, 2), round(info.lng, 2)
            key = f"{app}|{lat}|{lng}|{info.org}|{info.service}|{info.worldwide}|{info.threat}"
            gid = hashlib.blake2s(key.encode(), digest_size=6).hexdigest()
            g = self.groups.get(gid)
            if g is None:
                g = self.groups[gid] = Group(
                    id=gid, app=app, org=info.org, asn=info.asn, cloud=info.cloud,
                    city=info.city, country=info.country, country_code=info.country_code,
                    lat=lat, lng=lng, first_seen=now,
                    service=info.service, worldwide=info.worldwide, threat=info.threat,
                )
            g.count += 1
            g.last_seen = now
            g.ips.add(ip)
            g.ports.add(raddr.port)
            g.protocols.add("TCP" if sock_type == socket.SOCK_STREAM else "UDP")
            if ":" in ip:
                g.ipv6 = True

        # drop groups that faded out, and forget stale memories
        for gid in [gid for gid, g in self.groups.items() if g.count == 0 and now - g.last_seen > LINGER_SECONDS]:
            del self.groups[gid]
        for ip in [ip for ip, (_, t) in self.ip_app.items() if now - t > IP_APP_MEMORY_SECONDS]:
            del self.ip_app[ip]
        self.names.prune(live_pids)

        for gid, g in self.groups.items():
            if g.count == 0 and gid in previous:
                g.ips, g.ports, g.protocols = previous[gid]

        self.sites.prune()
        for g in self.groups.values():
            g.sites = self.sites.for_ips(g.ips) if is_browser(g.app) else []

        self.history.record(self.groups.values())

        groups = [g.to_json() for g in self.groups.values()]
        active = [g for g in groups if g["active"]]
        return {
            "groups": groups,
            "stats": {
                "connections": sum(g["count"] for g in active),
                "companies": len({g["org"] for g in active}),
                "countries": len({g["cc"] for g in active if g["cc"]}),
                "apps": len({g["app"] for g in active}),
                "local": len(local_ips),
                "unlocated": unlocated,
                "unnamed": unnamed,
                # None means "no known-bad list installed", which is not the same as zero
                "threats": (sum(g["count"] for g in active if g["threat"])
                            if getattr(self.geo, "has_threat_list", False) else None),
            },
            "limited": self.limited,
            "linger": LINGER_SECONDS,
            "addon": self.sites.connected(),
            "network": self.network.get(),   # VPN / proxy in the way?
        }


def guess_home(geo) -> dict | None:
    """A first guess at where this computer is, without asking anyone.

    Looks up the computer's own public address in the offline database. Most
    home computers only have one when their provider gives them IPv6; behind
    an ordinary router there is nothing to look up, and this returns None.
    """
    try:
        for addrs in psutil.net_if_addrs().values():
            for a in addrs:
                if a.family not in (socket.AF_INET, socket.AF_INET6):
                    continue
                ip, public = classify_ip(a.address)
                if not public:
                    continue
                info = geo.lookup(ip)
                if info.lat is not None and info.lng is not None and info.city and not info.worldwide:
                    return {"label": f"{info.city}, {info.country_code}", "lat": round(info.lat, 2), "lng": round(info.lng, 2)}
    except Exception:
        pass
    return None
