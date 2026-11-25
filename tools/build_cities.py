"""Build src/beaconmap/static/cities.js, the searchable "where are you?" list.

Run once by a maintainer, not by users:   python tools/build_cities.py

It scans the DB-IP Lite city database already on disk and keeps the cities
with the most internet addresses (a rough stand-in for size), plus the top
few in every country so small countries aren't left out.
Source data: DB-IP (https://db-ip.com), CC BY 4.0.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import maxminddb

from beaconmap.dbupdate import db_path

KEEP_OVERALL = 7000
KEEP_PER_COUNTRY = 12
OUT = Path(__file__).resolve().parent.parent / "src" / "beaconmap" / "static" / "cities.js"


def main() -> None:
    reader = maxminddb.open_database(str(db_path("dbip-city-lite.mmdb")))
    weight: dict[tuple[str, str, str], float] = defaultdict(float)
    where: dict[tuple[str, str, str], tuple[float, float]] = {}
    for n, (network, rec) in enumerate(reader):
        if n % 500000 == 0:
            print(f"  {n:,} networks read", flush=True)
        if not isinstance(rec, dict):
            continue
        city = ((rec.get("city") or {}).get("names") or {}).get("en", "").split(" (")[0].strip()
        cc = (rec.get("country") or {}).get("iso_code", "")
        loc = rec.get("location") or {}
        if not city or not cc or loc.get("latitude") is None or loc.get("longitude") is None:
            continue
        subs = rec.get("subdivisions") or [{}]
        region = ((subs[0] or {}).get("names") or {}).get("en", "")
        key = (city, region, cc)
        # IPv6 networks are astronomically large: count each as one small unit
        weight[key] += min(network.num_addresses, 4096) if network.version == 4 else 16
        where.setdefault(key, (round(loc["latitude"], 2), round(loc["longitude"], 2)))

    ranked = sorted(weight, key=weight.get, reverse=True)
    keep = set(ranked[:KEEP_OVERALL])
    per_country: dict[str, int] = defaultdict(int)
    for key in ranked:
        if per_country[key[2]] < KEEP_PER_COUNTRY:
            per_country[key[2]] += 1
            keep.add(key)

    rows = []
    # biggest first, so a search for "London" offers the one in England before the others
    for city, region, cc in sorted(keep, key=weight.get, reverse=True):
        label = ", ".join(part for part in (city, region if region != city else "", cc) if part)
        lat, lng = where[(city, region, cc)]
        rows.append([label, lat, lng])

    OUT.write_text(
        "// Cities for the \"where are you?\" search. Built by tools/build_cities.py from the\n"
        "// DB-IP Lite city database (https://db-ip.com, CC BY 4.0). [label, lat, lng]\n"
        "window.BEACON_CITIES = " + json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    print(f"wrote {len(rows):,} cities to {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    sys.exit(main())
