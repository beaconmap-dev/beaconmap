"""Website names for browser connections, reported by the optional browser add-on.

The operating system only knows addresses. The browser knows which website
each address was for, and the add-on passes that on: "claude.ai is at
160.79.104.10". Names are kept in memory only and forgotten after a while.
"""

from __future__ import annotations

import re
import threading
import time

from .netaddr import classify_ip

REMEMBER_SECONDS = 30 * 60
ADDON_ALIVE_SECONDS = 150
MAX_IPS = 5000
MAX_NAMES_PER_IP = 12
MAX_NAMES_SHOWN = 8
_HOST = re.compile(r"^(?=.{1,253}$)[a-z0-9_]([a-z0-9_-]{0,62})(\.[a-z0-9_]([a-z0-9_-]{0,62}))*$")

# Process names of browsers the add-on can run in. Names are only attached to
# these apps: another program reaching the same shared server isn't the browser.
BROWSERS = ("chrome", "msedge", "brave", "opera", "vivaldi", "chromium", "arc",
            "google chrome", "microsoft edge", "brave browser")


def is_browser(app: str) -> bool:
    name = app.lower()
    if name.endswith(".exe"):
        name = name[:-4]
    return name.startswith(BROWSERS)


def clean_host(value) -> str:
    host = str(value or "").strip().lower().rstrip(".")
    return host if _HOST.match(host) else ""


class SiteNames:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_ip: dict[str, dict[str, float]] = {}   # ip -> {host: last seen}
        self._last_report = 0.0

    def add(self, ip, host) -> bool:
        """Record one "host is at ip" report. Returns False if it was unusable."""
        host = clean_host(host)
        addr, public = classify_ip(str(ip or "").strip("[]"))
        if not host or not public:
            return False
        now = time.monotonic()
        with self._lock:
            self._last_report = now
            names = self._by_ip.get(addr)
            if names is None:
                if len(self._by_ip) >= MAX_IPS:
                    self._forget_old(now, force=True)
                names = self._by_ip[addr] = {}
            names[host] = now
            if len(names) > MAX_NAMES_PER_IP:
                del names[min(names, key=names.get)]
        return True

    def touch(self) -> None:
        """The add-on checked in, even if it had nothing to report."""
        with self._lock:
            self._last_report = time.monotonic()

    def connected(self) -> bool:
        with self._lock:
            return self._last_report > 0 and time.monotonic() - self._last_report < ADDON_ALIVE_SECONDS

    def for_ips(self, ips) -> list[str]:
        """Website names seen at these addresses, most recent first."""
        now = time.monotonic()
        seen: dict[str, float] = {}
        with self._lock:
            for ip in ips:
                for host, when in (self._by_ip.get(ip) or {}).items():
                    if now - when < REMEMBER_SECONDS and when > seen.get(host, 0):
                        seen[host] = when
        return sorted(seen, key=lambda h: (-seen[h], h))[:MAX_NAMES_SHOWN]

    def prune(self) -> None:
        with self._lock:
            self._forget_old(time.monotonic())

    def _forget_old(self, now: float, force: bool = False) -> None:
        for ip in list(self._by_ip):
            names = self._by_ip[ip]
            for host in [h for h, when in names.items() if now - when >= REMEMBER_SECONDS]:
                del names[host]
            if not names:
                del self._by_ip[ip]
        if force and len(self._by_ip) >= MAX_IPS:
            # still full: drop the quarter that was heard from longest ago
            oldest = sorted(self._by_ip, key=lambda ip: max(self._by_ip[ip].values()))
            for ip in oldest[: MAX_IPS // 4]:
                del self._by_ip[ip]
