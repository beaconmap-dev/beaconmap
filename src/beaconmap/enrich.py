"""Extra facts about an IP address, from optional offline lists.

Three questions, all answered from files on disk (see dbupdate.LISTS):

* Is it on a public list of known-bad servers?
* Which cloud service and region is it, according to the provider itself?
* Is it a shared "anycast" address, answered from many places at once, so
  that no single city is the right answer?

Every list is optional. A missing or damaged file just means fewer labels.
"""

from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Place:
    city: str
    country: str
    country_code: str
    lat: float
    lng: float


@dataclass(frozen=True)
class Service:
    org: str            # company, as shown in the list ("Amazon AWS")
    name: str           # service within it ("CloudFront"), may be empty
    cloud: bool
    region: str         # provider's own region code, may be empty
    worldwide: bool     # served from many places on the same address
    rank: int = 0       # when two entries cover the same range, the higher rank wins


@dataclass(frozen=True)
class Extra:
    service: Service | None = None
    place: Place | None = None
    worldwide: bool = False
    threat: str = ""


NOTHING = Extra()

# Where the providers' regions are. Unknown regions fall back to the IP database.
_P = Place
REGIONS: dict[str, Place] = {
    # Amazon AWS
    "aws:us-east-1": _P("Ashburn", "United States", "US", 39.04, -77.49),
    "aws:us-east-2": _P("Columbus", "United States", "US", 39.96, -83.0),
    "aws:us-west-1": _P("San Jose", "United States", "US", 37.34, -121.89),
    "aws:us-west-2": _P("Boardman", "United States", "US", 45.84, -119.7),
    "aws:ca-central-1": _P("Montreal", "Canada", "CA", 45.5, -73.57),
    "aws:ca-west-1": _P("Calgary", "Canada", "CA", 51.05, -114.07),
    "aws:mx-central-1": _P("Querétaro", "Mexico", "MX", 20.59, -100.39),
    "aws:sa-east-1": _P("São Paulo", "Brazil", "BR", -23.55, -46.63),
    "aws:eu-west-1": _P("Dublin", "Ireland", "IE", 53.35, -6.26),
    "aws:eu-west-2": _P("London", "United Kingdom", "GB", 51.51, -0.13),
    "aws:eu-west-3": _P("Paris", "France", "FR", 48.86, 2.35),
    "aws:eu-central-1": _P("Frankfurt", "Germany", "DE", 50.11, 8.68),
    "aws:eu-central-2": _P("Zurich", "Switzerland", "CH", 47.38, 8.54),
    "aws:eu-north-1": _P("Stockholm", "Sweden", "SE", 59.33, 18.07),
    "aws:eu-south-1": _P("Milan", "Italy", "IT", 45.46, 9.19),
    "aws:eu-south-2": _P("Zaragoza", "Spain", "ES", 41.65, -0.89),
    "aws:me-south-1": _P("Manama", "Bahrain", "BH", 26.07, 50.56),
    "aws:me-central-1": _P("Dubai", "United Arab Emirates", "AE", 25.2, 55.27),
    "aws:il-central-1": _P("Tel Aviv", "Israel", "IL", 32.09, 34.78),
    "aws:af-south-1": _P("Cape Town", "South Africa", "ZA", -33.92, 18.42),
    "aws:ap-south-1": _P("Mumbai", "India", "IN", 19.08, 72.88),
    "aws:ap-south-2": _P("Hyderabad", "India", "IN", 17.39, 78.49),
    "aws:ap-southeast-1": _P("Singapore", "Singapore", "SG", 1.35, 103.82),
    "aws:ap-southeast-2": _P("Sydney", "Australia", "AU", -33.87, 151.21),
    "aws:ap-southeast-3": _P("Jakarta", "Indonesia", "ID", -6.21, 106.85),
    "aws:ap-southeast-4": _P("Melbourne", "Australia", "AU", -37.81, 144.96),
    "aws:ap-southeast-5": _P("Kuala Lumpur", "Malaysia", "MY", 3.14, 101.69),
    "aws:ap-southeast-7": _P("Bangkok", "Thailand", "TH", 13.76, 100.5),
    "aws:ap-northeast-1": _P("Tokyo", "Japan", "JP", 35.68, 139.69),
    "aws:ap-northeast-2": _P("Seoul", "South Korea", "KR", 37.57, 126.98),
    "aws:ap-northeast-3": _P("Osaka", "Japan", "JP", 34.69, 135.5),
    "aws:ap-east-1": _P("Hong Kong", "Hong Kong", "HK", 22.32, 114.17),
    "aws:ap-east-2": _P("Taipei", "Taiwan", "TW", 25.03, 121.57),
    # Google Cloud
    "gcp:us-central1": _P("Council Bluffs", "United States", "US", 41.26, -95.86),
    "gcp:us-east1": _P("Moncks Corner", "United States", "US", 33.2, -80.0),
    "gcp:us-east4": _P("Ashburn", "United States", "US", 39.04, -77.49),
    "gcp:us-east5": _P("Columbus", "United States", "US", 39.96, -83.0),
    "gcp:us-south1": _P("Dallas", "United States", "US", 32.78, -96.8),
    "gcp:us-west1": _P("The Dalles", "United States", "US", 45.6, -121.18),
    "gcp:us-west2": _P("Los Angeles", "United States", "US", 34.05, -118.24),
    "gcp:us-west3": _P("Salt Lake City", "United States", "US", 40.76, -111.89),
    "gcp:us-west4": _P("Las Vegas", "United States", "US", 36.17, -115.14),
    "gcp:northamerica-northeast1": _P("Montreal", "Canada", "CA", 45.5, -73.57),
    "gcp:northamerica-northeast2": _P("Toronto", "Canada", "CA", 43.65, -79.38),
    "gcp:northamerica-south1": _P("Querétaro", "Mexico", "MX", 20.59, -100.39),
    "gcp:southamerica-east1": _P("São Paulo", "Brazil", "BR", -23.55, -46.63),
    "gcp:southamerica-west1": _P("Santiago", "Chile", "CL", -33.45, -70.67),
    "gcp:europe-west1": _P("St. Ghislain", "Belgium", "BE", 50.45, 3.82),
    "gcp:europe-west2": _P("London", "United Kingdom", "GB", 51.51, -0.13),
    "gcp:europe-west3": _P("Frankfurt", "Germany", "DE", 50.11, 8.68),
    "gcp:europe-west4": _P("Eemshaven", "Netherlands", "NL", 53.44, 6.83),
    "gcp:europe-west6": _P("Zurich", "Switzerland", "CH", 47.38, 8.54),
    "gcp:europe-west8": _P("Milan", "Italy", "IT", 45.46, 9.19),
    "gcp:europe-west9": _P("Paris", "France", "FR", 48.86, 2.35),
    "gcp:europe-west10": _P("Berlin", "Germany", "DE", 52.52, 13.4),
    "gcp:europe-west12": _P("Turin", "Italy", "IT", 45.07, 7.69),
    "gcp:europe-north1": _P("Hamina", "Finland", "FI", 60.57, 27.2),
    "gcp:europe-north2": _P("Stockholm", "Sweden", "SE", 59.33, 18.07),
    "gcp:europe-central2": _P("Warsaw", "Poland", "PL", 52.23, 21.01),
    "gcp:europe-southwest1": _P("Madrid", "Spain", "ES", 40.42, -3.7),
    "gcp:me-west1": _P("Tel Aviv", "Israel", "IL", 32.09, 34.78),
    "gcp:me-central1": _P("Doha", "Qatar", "QA", 25.29, 51.53),
    "gcp:me-central2": _P("Dammam", "Saudi Arabia", "SA", 26.43, 50.1),
    "gcp:africa-south1": _P("Johannesburg", "South Africa", "ZA", -26.2, 28.05),
    "gcp:asia-south1": _P("Mumbai", "India", "IN", 19.08, 72.88),
    "gcp:asia-south2": _P("Delhi", "India", "IN", 28.61, 77.21),
    "gcp:asia-southeast1": _P("Singapore", "Singapore", "SG", 1.35, 103.82),
    "gcp:asia-southeast2": _P("Jakarta", "Indonesia", "ID", -6.21, 106.85),
    "gcp:asia-east1": _P("Changhua", "Taiwan", "TW", 24.05, 120.52),
    "gcp:asia-east2": _P("Hong Kong", "Hong Kong", "HK", 22.32, 114.17),
    "gcp:asia-northeast1": _P("Tokyo", "Japan", "JP", 35.68, 139.69),
    "gcp:asia-northeast2": _P("Osaka", "Japan", "JP", 34.69, 135.5),
    "gcp:asia-northeast3": _P("Seoul", "South Korea", "KR", 37.57, 126.98),
    "gcp:australia-southeast1": _P("Sydney", "Australia", "AU", -33.87, 151.21),
    "gcp:australia-southeast2": _P("Melbourne", "Australia", "AU", -37.81, 144.96),
}

# AWS service code -> (friendly name, served worldwide from one address?)
AWS_SERVICES: dict[str, tuple[str, bool]] = {
    "CLOUDFRONT": ("CloudFront", True),
    "CLOUDFRONT_ORIGIN_FACING": ("CloudFront", True),
    "GLOBALACCELERATOR": ("Global Accelerator", True),
    "ROUTE53": ("Route 53", True),
    "S3": ("S3 storage", False),
    "EC2": ("EC2 servers", False),
    "API_GATEWAY": ("API Gateway", False),
    "DYNAMODB": ("DynamoDB", False),
    "CHIME_MEETINGS": ("Chime", False),
    "CHIME_VOICECONNECTOR": ("Chime", False),
    "AMAZON_CONNECT": ("Connect", False),
    "WORKSPACES_GATEWAYS": ("WorkSpaces", False),
}
GITHUB_PARTS = {"web": "", "api": "API", "git": "Git", "pages": "Pages", "packages": "Packages", "copilot": "Copilot"}


class PrefixTable:
    """Longest-prefix match over IPv4 and IPv6 ranges."""

    def __init__(self) -> None:
        self._nets: dict[int, dict[int, dict[int, object]]] = {4: {}, 6: {}}
        self._lengths: dict[int, list[int]] = {4: [], 6: []}
        self.size = 0

    def add(self, cidr: str, value, rank: int = 0) -> None:
        try:
            net = ipaddress.ip_network(str(cidr).strip(), strict=False)
        except ValueError:
            return
        bucket = self._nets[net.version].setdefault(net.prefixlen, {})
        key = int(net.network_address)
        old = bucket.get(key)
        if old is None:
            self.size += 1
        elif old[0] >= rank:
            return
        bucket[key] = (rank, value)
        self._lengths[net.version] = sorted(self._nets[net.version], reverse=True)

    def get(self, ip: ipaddress.IPv4Address | ipaddress.IPv6Address):
        bits = 32 if ip.version == 4 else 128
        number = int(ip)
        for length in self._lengths[ip.version]:
            shift = bits - length
            hit = self._nets[ip.version][length].get((number >> shift) << shift)
            if hit is not None:
                return hit[1]
        return None


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _lines(path: Path) -> list[str]:
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]


class Enrichment:
    def __init__(self, folder: Path | None = None) -> None:
        self.services = PrefixTable()
        self.anycast = PrefixTable()
        self.threats = PrefixTable()
        self.loaded: list[str] = []
        self.lookup = lru_cache(maxsize=20000)(self._lookup)
        if folder is not None:
            self._load(folder)

    @property
    def has_threat_list(self) -> bool:
        return self.threats.size > 0

    def _load(self, folder: Path) -> None:
        loaders = {
            "feodo.json": self._feodo, "drop_v4.json": self._drop, "drop_v6.json": self._drop,
            "aws.json": self._aws, "gcloud.json": self._gcloud,
            "cloudflare_v4.txt": self._cloudflare, "cloudflare_v6.txt": self._cloudflare,
            "fastly.json": self._fastly, "github.json": self._github,
            "anycast_v4.txt": self._anycast, "anycast_v6.txt": self._anycast,
        }
        for name, load in loaders.items():
            path = folder / name
            if not path.exists():
                continue
            try:
                load(path)
                self.loaded.append(name)
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                print(f"[beaconmap] skipping damaged list {name}: {exc!r}")

    # ---- known-bad servers ----
    def _feodo(self, path: Path) -> None:
        for row in _read_json(path):
            malware = row.get("malware") or "botnet"
            self.threats.add(row["ip_address"], f"Feodo Tracker botnet list ({malware} control server)")

    def _drop(self, path: Path) -> None:
        # one JSON object per line; the last line is metadata
        for line in _lines(path):
            row = json.loads(line)
            if "cidr" in row:
                self.threats.add(row["cidr"], f"Spamhaus DROP list of hijacked networks ({row.get('sblid', 'no id')})")

    # ---- cloud providers' own address lists ----
    def _aws(self, path: Path) -> None:
        data = _read_json(path)
        rows = [(p["ip_prefix"], p) for p in data.get("prefixes", [])]
        rows += [(p["ipv6_prefix"], p) for p in data.get("ipv6_prefixes", [])]
        for cidr, p in rows:
            code, region = p.get("service", "AMAZON"), p.get("region", "")
            name, worldwide = AWS_SERVICES.get(code, ("", False))
            worldwide = worldwide or region == "GLOBAL"
            # the same range is listed as AMAZON and again under its real service
            rank = 0 if code == "AMAZON" else 1 if code == "EC2" else 2
            self.services.add(cidr, Service("Amazon AWS", name, True, "" if region == "GLOBAL" else f"aws:{region}", worldwide), rank)

    def _gcloud(self, path: Path) -> None:
        for p in _read_json(path).get("prefixes", []):
            cidr = p.get("ipv4Prefix") or p.get("ipv6Prefix")
            scope = p.get("scope", "")
            worldwide = scope == "global"
            self.services.add(cidr, Service("Google Cloud", "", True, "" if worldwide else f"gcp:{scope}", worldwide))

    def _cloudflare(self, path: Path) -> None:
        for cidr in _lines(path):
            self.services.add(cidr, Service("Cloudflare", "", True, "", True))

    def _fastly(self, path: Path) -> None:
        data = _read_json(path)
        for cidr in data.get("addresses", []) + data.get("ipv6_addresses", []):
            self.services.add(cidr, Service("Fastly", "", True, "", True))

    def _github(self, path: Path) -> None:
        data = _read_json(path)
        for part, name in GITHUB_PARTS.items():
            for cidr in data.get(part, []):
                # "web" is the catch-all, so the named parts outrank it
                self.services.add(cidr, Service("GitHub", name, False, "", False), 1 if name else 0)

    def _anycast(self, path: Path) -> None:
        for cidr in _lines(path):
            self.anycast.add(cidr, True)

    # ---- lookup ----
    def _lookup(self, ip: str) -> Extra:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return NOTHING
        service = self.services.get(addr)
        threat = self.threats.get(addr) or ""
        worldwide = bool(self.anycast.get(addr)) or bool(service and service.worldwide)
        place = REGIONS.get(service.region) if service and service.region and not worldwide else None
        if not (service or threat or worldwide):
            return NOTHING
        return Extra(service=service, place=place, worldwide=worldwide, threat=threat)
