"""Command-line entry point:  beaconmap [--port N] [--no-browser] [--update-db]"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import webbrowser

from . import __version__
from .dbupdate import ask_and_download, ask_and_repair, databases_present, update_databases
from .paths import access_token, data_dir, write_private

STALE_DAYS = 100  # DB-IP publishes monthly; nag after about three missed updates


def _free_port(preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("No free port found near %d" % preferred)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="beaconmap",
        description="See every server your computer talks to, live on a 3D globe. 100% local.",
    )
    parser.add_argument("--port", type=int, default=8765, help="local port (default 8765)")
    parser.add_argument("--no-browser", action="store_true", help="don't open the browser automatically")
    parser.add_argument("--update-db", action="store_true", help="download fresh offline databases, then exit")
    parser.add_argument("--version", action="version", version=f"beaconmap {__version__}")
    args = parser.parse_args(argv)

    if args.update_db:
        update_databases()
        return

    if not databases_present() and not ask_and_download():
        sys.exit(1)

    import uvicorn  # imported late so --help stays fast

    from .geo import DatabaseError, GeoLookup
    from .server import create_app

    try:
        geo = GeoLookup()
    except DatabaseError as exc:
        if not ask_and_repair(str(exc)):
            sys.exit(1)
        try:
            geo = GeoLookup()
        except DatabaseError as exc2:
            sys.exit(f"The database still can't be read: {exc2}")

    age = geo.age_days()
    if age > STALE_DAYS:
        print(f"\n  Note: the location database is about {age // 30} months old, so some")
        print("  servers may be placed wrongly. Refresh it with:  beaconmap --update-db")

    if not geo.has_threat_list:
        print("\n  Tip: known-bad-server flags and cloud service names are not installed.")
        print("  Add them with:  beaconmap --update-db")

    port = _free_port(args.port)
    token = access_token()
    url = f"http://127.0.0.1:{port}/?t={token}"
    print(f"\n  BeaconMap is running at {url}")
    print("  Only you, on this computer, can see it. Press Ctrl+C to stop.\n")
    if not args.no_browser:
        threading.Timer(1.2, lambda: _open_browser(url)).start()

    uvicorn.run(create_app(port, token, geo), host="127.0.0.1", port=port, log_level="warning")


def _open_browser(url: str) -> None:
    """Open the browser through a private local file, not the URL itself.

    A URL handed straight to the browser can show up in the process list,
    where other accounts on the computer could read the secret token.
    """
    page = data_dir() / "open.html"
    write_private(
        page,
        '<!doctype html><meta charset="utf-8"><title>BeaconMap</title>'
        f'<meta http-equiv="refresh" content="0;url={url}">'
        f'<a href="{url}">Open BeaconMap</a>',
    )
    webbrowser.open(page.as_uri())


if __name__ == "__main__":
    main()
