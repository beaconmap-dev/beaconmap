# Contributing to BeaconMap

Thanks for helping. BeaconMap is small on purpose, so a short read of this
page saves everyone time.

## The one rule: nothing leaves the computer

BeaconMap's promise is that it never phones home. Pull requests that add any
of these will not be merged:

- telemetry, analytics, crash reporting, or update checks
- online lookups of IP addresses, hostnames or locations (reverse DNS, WHOIS,
  geolocation APIs...)
- anything that sends connection data, even "anonymised", off the machine

The only network access allowed is downloading the databases and lists, and
only after the user agrees or runs `beaconmap --update-db`. New lists must be
fetched from their publisher, never bundled, and their licence must allow that use.

## Set up

```
python -m venv .venv
.venv/Scripts/pip install -e . pytest httpx     # Linux/macOS: .venv/bin/pip
.venv/Scripts/pytest
beaconmap --no-browser                          # then open the link it prints
```

The page is plain HTML, CSS and JavaScript in `src/beaconmap/static/`: there is
no build step. Refresh the browser to see changes; restart `beaconmap` for
Python changes.

## Where things live

| File | What it does |
|---|---|
| `collector.py` | Reads the OS connection table and groups connections |
| `geo.py`, `enrich.py` | Offline location / owner lookup, service and region lists |
| `dbupdate.py` | The consented downloads |
| `server.py` | Local web server: Host/Origin checks, token, WebSocket |
| `sites.py`, `extension/` | Optional browser add-on and the website names it sends |
| `history.py` | In-memory session history |
| `netenv.py` | Spots a VPN or proxy from local settings |
| `static/app.js` | Globe, flat map, list, settings |

## Pull requests

- Keep one change per pull request, with a test when it touches Python.
- `pytest` must pass. Test on the OS you have and say which one in the PR;
  Linux and macOS reports are especially welcome.
- Security-sensitive code (`server.py`, the token, the add-on) needs a clear
  explanation of why the change is safe.
- Write user-facing text plainly: short sentences, no jargon unless nerd mode is on.

## Security problems

Please don't open a public issue. See [SECURITY.md](SECURITY.md).
