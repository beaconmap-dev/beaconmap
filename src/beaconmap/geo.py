"""Offline IP -> location / company lookups using the DB-IP Lite databases."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from functools import lru_cache

import maxminddb

from .dbupdate import db_path, lists_dir
from .enrich import Enrichment

# Hosting / CDN networks. Servers here are "delivery pipes": the IP's location
# says where a data centre is, not which company you're really dealing with.
CLOUD_ASNS: dict[int, str] = {
    13335: "Cloudflare", 209242: "Cloudflare",
    16509: "Amazon AWS", 14618: "Amazon AWS", 8987: "Amazon AWS",
    396982: "Google Cloud",
    20940: "Akamai", 16625: "Akamai", 63949: "Akamai (Linode)",
    54113: "Fastly",
    14061: "DigitalOcean", 16276: "OVH", 24940: "Hetzner", 20473: "Vultr",
    31898: "Oracle Cloud", 15133: "Edgecast", 22822: "Edgio", 60068: "CDN77",
}

# Big first-party networks: just give them a friendly name.
KNOWN_ASNS: dict[int, str] = {
    15169: "Google", 19527: "Google", 36040: "Google (YouTube)",
    8075: "Microsoft", 8068: "Microsoft",
    32934: "Meta",
    714: "Apple", 6185: "Apple",
    36459: "GitHub", 2635: "Automattic", 2906: "Netflix", 40027: "Netflix",
    46489: "Twitch", 49544: "Discord", 13414: "X (Twitter)", 396986: "ByteDance",
}


@dataclass(frozen=True)
class GeoInfo:
    lat: float | None
    lng: float | None
    city: str
    country: str
    country_code: str
    asn: int | None
    org: str
    cloud: bool
    service: str = ""        # e.g. "CloudFront", from the provider's own list
    worldwide: bool = False  # one address answered from many places: the city is a guess
    threat: str = ""         # why it's on a known-bad list, if it is


class DatabaseError(Exception):
    """An offline database is missing, damaged, or not a database at all."""


def _open(name: str):
    path = db_path(name)
    try:
        return maxminddb.open_database(str(path))
    except (maxminddb.InvalidDatabaseError, OSError, ValueError) as exc:
        raise DatabaseError(f"{path.name} could not be read ({exc})") from exc


class GeoLookup:
    def __init__(self) -> None:
        self._city = _open("dbip-city-lite.mmdb")
        try:
            self._asn = _open("dbip-asn-lite.mmdb")
        except DatabaseError:
            self._city.close()
            raise
        self.extra = Enrichment(lists_dir())
        self.lookup = lru_cache(maxsize=20000)(self._lookup)

    @property
    def has_threat_list(self) -> bool:
        return self.extra.has_threat_list

    def age_days(self) -> int:
        """How old the location data is, from the build date stored inside the file."""
        built = self._city.metadata().build_epoch
        return max(0, int((time.time() - built) // 86400))

    def _lookup(self, ip: str) -> GeoInfo:
        try:
            c = self._city.get(ip) or {}
        except (ValueError, maxminddb.InvalidDatabaseError):
            c = {}
        try:
            a = self._asn.get(ip) or {}
        except (ValueError, maxminddb.InvalidDatabaseError):
            a = {}
        loc = c.get("location") or {}
        country = c.get("country") or {}
        asn = a.get("autonomous_system_number")
        org = a.get("autonomous_system_organization") or "Unknown"
        cloud_name = CLOUD_ASNS.get(asn) if asn else None
        known_name = KNOWN_ASNS.get(asn) if asn else None
        info = GeoInfo(
            lat=loc.get("latitude"),
            lng=loc.get("longitude"),
            city=((c.get("city") or {}).get("names") or {}).get("en", "").split(" (")[0],
            country=(country.get("names") or {}).get("en", ""),
            country_code=country.get("iso_code", ""),
            asn=asn,
            org=cloud_name or known_name or _tidy_org(org),
            cloud=cloud_name is not None,
        )
        extra = getattr(self, "extra", None)
        x = extra.lookup(ip) if extra else None
        if not x or not (x.service or x.worldwide or x.threat):
            return info
        changes: dict = {"worldwide": x.worldwide, "threat": x.threat}
        if x.service:
            # the provider's own list beats a guess from the network's name
            changes.update(org=x.service.org, cloud=x.service.cloud, service=x.service.name)
        if x.place:
            p = x.place
            changes.update(lat=p.lat, lng=p.lng, city=p.city, country=p.country, country_code=p.country_code)
        return replace(info, **changes)

    def close(self) -> None:
        self._city.close()
        self._asn.close()


def _tidy_org(org: str) -> str:
    """'Example Networks, Inc.' -> 'Example Networks'."""
    for suffix in (", Inc.", " Inc.", ", LLC", " LLC", " Ltd", " Limited", " GmbH", " Corporation", " Corp."):
        if org.endswith(suffix):
            return org[: -len(suffix)].rstrip(",")
    return org
