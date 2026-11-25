"""Everything this computer has talked to since BeaconMap started.

Live connections vanish when they close, and many close within seconds or
minutes of a page loading. The history keeps one line per app + company +
place, with when it was first and last seen. It lives in memory only and is
gone when BeaconMap quits.
"""

from __future__ import annotations

import threading
import time

MAX_ENTRIES = 2000
MAX_SITES = 12


class History:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, dict] = {}
        self._active: set[str] = set()
        self.started = time.time()

    def record(self, groups) -> None:
        """Called after every poll with the collector's current groups."""
        now = time.time()
        with self._lock:
            self._active = {g.id for g in groups if g.count > 0}
            for g in groups:
                if g.count <= 0:
                    continue
                e = self._entries.get(g.id)
                if e is None:
                    if len(self._entries) >= MAX_ENTRIES:
                        self._drop_oldest()
                    e = self._entries[g.id] = {
                        "id": g.id, "app": g.app, "org": g.org, "service": g.service, "cloud": g.cloud,
                        "city": g.city, "country": g.country, "cc": g.country_code, "lat": g.lat, "lng": g.lng,
                        "worldwide": g.worldwide, "threat": g.threat,
                        "first_seen": now, "last_seen": now, "peak": 0, "sites": [],
                    }
                e["last_seen"] = now
                e["peak"] = max(e["peak"], g.count)
                for site in g.sites:
                    if site not in e["sites"]:
                        e["sites"].insert(0, site)
                del e["sites"][MAX_SITES:]

    def _drop_oldest(self) -> None:
        idle = [i for i in self._entries if i not in self._active] or list(self._entries)
        for i in sorted(idle, key=lambda i: self._entries[i]["last_seen"])[: MAX_ENTRIES // 10]:
            del self._entries[i]

    def snapshot(self, limit: int = 500) -> dict:
        with self._lock:
            entries = [dict(e, sites=list(e["sites"]), active=e["id"] in self._active) for e in self._entries.values()]
        entries.sort(key=lambda e: (not e["active"], -e["last_seen"]))
        return {"started": self.started, "now": time.time(), "total": len(entries), "entries": entries[:limit]}

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self.started = time.time()
