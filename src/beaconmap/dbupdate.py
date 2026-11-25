"""Download the free DB-IP Lite databases.

This is the ONLY code in BeaconMap that touches the internet, and it only
runs when the user explicitly agrees (first run) or asks (--update-db).
It also fetches a few small optional lists (see LISTS).
"""

from __future__ import annotations

import datetime as dt
import gzip
import shutil
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .paths import data_dir

BASE_URL = "https://download.db-ip.com/free/"
DATABASES = {
    # local filename: (remote name prefix, approx download size)
    "dbip-city-lite.mmdb": ("dbip-city-lite", "~60 MB"),
    "dbip-asn-lite.mmdb": ("dbip-asn-lite", "~5 MB"),
}
# Small optional lists, fetched straight from whoever publishes them. They are
# never bundled with BeaconMap: each stays under its publisher's own terms.
LISTS = {
    # known-bad servers
    "feodo.json": "https://feodotracker.abuse.ch/downloads/ipblocklist.json",
    "drop_v4.json": "https://www.spamhaus.org/drop/drop_v4.json",
    "drop_v6.json": "https://www.spamhaus.org/drop/drop_v6.json",
    # cloud providers' own address lists (service and region)
    "aws.json": "https://ip-ranges.amazonaws.com/ip-ranges.json",
    "gcloud.json": "https://www.gstatic.com/ipranges/cloud.json",
    "cloudflare_v4.txt": "https://www.cloudflare.com/ips-v4",
    "cloudflare_v6.txt": "https://www.cloudflare.com/ips-v6",
    "fastly.json": "https://api.fastly.com/public-ip-list",
    "github.json": "https://api.github.com/meta",
    # addresses answered from many places at once
    "anycast_v4.txt": "https://raw.githubusercontent.com/bgptools/anycast-prefixes/master/anycatch-v4-prefixes.txt",
    "anycast_v6.txt": "https://raw.githubusercontent.com/bgptools/anycast-prefixes/master/anycatch-v6-prefixes.txt",
}
LIST_SOURCES = "abuse.ch, spamhaus.org, amazonaws.com, gstatic.com, cloudflare.com, fastly.com, github.com, bgp.tools (via GitHub)"

ATTRIBUTION ="IP Geolocation by DB-IP (https://db-ip.com), licensed CC BY 4.0"


def db_path(name: str) -> Path:
    return data_dir() / name


def databases_present() -> bool:
    return all(db_path(name).exists() for name in DATABASES)


def _candidate_urls(prefix: str) -> list[str]:
    """DB-IP publishes monthly files; try this month, then last month."""
    today = dt.date.today()
    first = today.replace(day=1)
    last_month = (first - dt.timedelta(days=1)).replace(day=1)
    return [f"{BASE_URL}{prefix}-{d:%Y-%m}.mmdb.gz" for d in (first, last_month)]


def _open(url: str):
    """urlopen, with one retry when the OS certificate store lets us down.

    Windows fetches some root certificates only when a browser first needs
    them, so Python can fail on a site that works fine in Chrome. If the
    certifi bundle is installed we try once more with it; it is still a full
    certificate check, never a skipped one."""
    req = urllib.request.Request(url, headers={"User-Agent": "beaconmap"})
    try:
        return urllib.request.urlopen(req, timeout=60)
    except urllib.error.URLError as exc:
        if not isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise
        try:
            import certifi
        except ImportError:
            raise exc from None
        ctx = ssl.create_default_context(cafile=certifi.where())
        return urllib.request.urlopen(req, timeout=60, context=ctx)


def lists_dir() -> Path:
    path = data_dir() / "lists"
    path.mkdir(parents=True, exist_ok=True)
    return path


def lists_present() -> bool:
    return any((lists_dir() / name).exists() for name in LISTS)


def update_lists() -> None:
    """Fetch the optional lists. One failing never stops the rest, or BeaconMap."""
    folder = lists_dir()
    print("  Downloading the optional lists (known-bad servers, cloud services)")
    failed = []
    for name, url in LISTS.items():
        tmp = folder / (name + ".part")
        try:
            with _open(url) as resp, open(tmp, "wb") as out:
                shutil.copyfileobj(resp, out)
            tmp.replace(folder / name)
        except (urllib.error.URLError, OSError) as exc:
            failed.append(f"{name} ({exc})")
        finally:
            tmp.unlink(missing_ok=True)
    print(f"    {len(LISTS) - len(failed)} of {len(LISTS)} lists saved to {folder}")
    for item in failed:
        print(f"    skipped: {item}")


def _download(url: str, dest: Path) -> None:
    with _open(url) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(dest, "wb") as out:
            while chunk := resp.read(1 << 16):
                out.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100 // total
                    sys.stdout.write(f"\r    {pct:3d}%  {done >> 20} / {total >> 20} MB")
                    sys.stdout.flush()
    sys.stdout.write("\n")


def update_databases() -> None:
    folder = data_dir()
    for name, (prefix, _size) in DATABASES.items():
        final = folder / name
        gz_tmp = folder / (name + ".gz.part")
        mmdb_tmp = folder / (name + ".part")
        last_error: Exception | None = None
        for url in _candidate_urls(prefix):
            try:
                print(f"  Downloading {url}")
                _download(url, gz_tmp)
                with gzip.open(gz_tmp, "rb") as src, open(mmdb_tmp, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                mmdb_tmp.replace(final)  # atomic swap: old DB stays usable until done
                last_error = None
                break
            except (urllib.error.URLError, OSError, EOFError) as exc:
                last_error = exc
                print(f"    failed: {exc}")
            finally:
                gz_tmp.unlink(missing_ok=True)
                mmdb_tmp.unlink(missing_ok=True)
        if last_error is not None:
            raise SystemExit(f"Could not download {name}: {last_error}")
    print(f"  Saved to {folder}")
    print(f"  {ATTRIBUTION}")
    update_lists()


def ask_and_download() -> bool:
    """First-run consent prompt. Returns True if databases are ready."""
    print("\nBeaconMap needs two free offline databases to place servers on the map.")
    print("They will be downloaded ONCE from db-ip.com. After that, BeaconMap never")
    print("touches the internet unless you run:  beaconmap --update-db\n")
    for name, (prefix, size) in DATABASES.items():
        print(f"  {size:>7}  {_candidate_urls(prefix)[0]}")
    print(f"    ~3 MB  {len(LISTS)} small lists of known-bad servers and cloud services, from:")
    print(f"           {LIST_SOURCES}")
    print(f"\n  Saved to: {data_dir()}")
    try:
        answer = input("\nDownload now? [Y/n] ").strip().lower()
    except EOFError:
        answer = "n"
    if answer not in ("", "y", "yes"):
        print("OK, nothing downloaded. Run 'beaconmap --update-db' whenever you're ready.")
        return False
    update_databases()
    return True


def ask_and_repair(problem: str) -> bool:
    """A database file is damaged. Offer to download a fresh copy. True if repaired."""
    print(f"\nBeaconMap's location database is damaged: {problem}")
    print("A fresh copy can be downloaded from db-ip.com (about 65 MB).")
    try:
        answer = input("\nDownload it again now? [Y/n] ").strip().lower()
    except EOFError:
        answer = "n"
    if answer not in ("", "y", "yes"):
        print("OK, nothing downloaded. Run 'beaconmap --update-db' to fix it later.")
        return False
    update_databases()
    return True
