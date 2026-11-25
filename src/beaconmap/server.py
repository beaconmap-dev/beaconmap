"""Local web server: serves the globe and streams updates over a WebSocket.

Three locks keep the connection list private:

* it binds to 127.0.0.1 only, so other devices can't reach it;
* Host and Origin checks stop other websites open in your browser from
  reading it (DNS rebinding, cross-site WebSocket hijacking);
* a secret token, swapped for a cookie on first visit, stops other user
  accounts on the same computer from reading it.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import secrets
from importlib import resources

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .collector import Collector, guess_home
from .dbupdate import ATTRIBUTION
from .geo import GeoLookup
from .paths import load_config, save_config

POLL_SECONDS = 0.5
COOKIE_MAX_AGE = 365 * 24 * 3600

NO_ACCESS_PAGE = """<!doctype html><meta charset="utf-8"><title>BeaconMap</title>
<body style="font:16px system-ui;max-width:32em;margin:15vh auto;padding:0 16px;color:#222">
<h1 style="font-size:20px">This browser hasn't been let in yet</h1>
<p>BeaconMap only shows your connections to the person who started it.
Open the full link printed in the BeaconMap window (it ends in <code>?t=…</code>),
or start BeaconMap again and let it open the browser for you.</p></body>"""


def create_app(port: int, token: str, geo: GeoLookup | None = None) -> FastAPI:
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    allowed_origins = {f"http://{h}" for h in allowed_hosts}
    cookie_name = f"beaconmap_{port}"  # cookies ignore ports, so name it per port
    # The browser add-on gets its own key, so it never holds the page's token
    addon_key = hashlib.sha256(f"{token}:addon".encode()).hexdigest()[:40]
    MAX_SITES_PER_REPORT = 500

    geo = geo or GeoLookup()
    collector = Collector(geo)
    clients: set[WebSocket] = set()
    latest: dict = {"payload": None}

    def has_access(cookies) -> bool:
        return secrets.compare_digest(cookies.get(cookie_name, ""), token)

    async def poll_loop() -> None:
        last_sent = None
        while True:
            try:
                # psutil is a blocking call: keep it off the event loop
                snap = await asyncio.to_thread(collector.poll)
                payload = json.dumps(snap, separators=(",", ":"))
                latest["payload"] = payload
                if payload != last_sent and clients:
                    last_sent = payload
                    for ws in list(clients):
                        try:
                            await ws.send_text(payload)
                        except Exception:
                            clients.discard(ws)
            except Exception as exc:  # never let one bad poll kill the stream
                print(f"[beaconmap] poll error: {exc!r}")
            await asyncio.sleep(POLL_SECONDS)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(poll_loop())
        try:
            yield
        finally:
            task.cancel()
            geo.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    class Guard(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if request.headers.get("host") not in allowed_hosts:
                return JSONResponse({"error": "forbidden host"}, status_code=403)

            offered = request.query_params.get("t")
            if offered is not None and secrets.compare_digest(offered, token):
                # Trade the token for a cookie, then drop it from the address bar
                response = RedirectResponse("/", status_code=303)
                response.set_cookie(cookie_name, token, max_age=COOKIE_MAX_AGE,
                                    httponly=True, samesite="strict")
            elif has_access(request.cookies) or request.url.path == "/api/sites":
                # /api/sites is the add-on's door: it checks the add-on's key itself
                response = await call_next(request)
            else:
                response = HTMLResponse(NO_ACCESS_PAGE, status_code=403)
            # Always revalidate, so an upgraded BeaconMap never shows a stale page
            response.headers["Cache-Control"] = "no-cache"
            return response

    app.add_middleware(Guard)

    def check_origin(origin: str | None) -> bool:
        return origin in allowed_origins

    @app.get("/api/config")
    async def get_config():
        cfg = load_config()
        try:
            db_age_days = geo.age_days()
        except Exception:
            db_age_days = None
        home = cfg.get("home")
        return {"home": home, "attribution": ATTRIBUTION, "db_age_days": db_age_days,
                # only worked out when it's needed, on first run
                "home_guess": None if home else await asyncio.to_thread(guess_home, geo),
                "addon_path": str(resources.files("beaconmap") / "extension")}

    @app.post("/api/home")
    async def set_home(request: Request):
        if not check_origin(request.headers.get("origin")):
            raise HTTPException(403, "forbidden origin")
        try:
            body = await request.json()
            lat, lng = float(body["lat"]), float(body["lng"])
            label = str(body.get("label", ""))[:80]
        except (KeyError, TypeError, ValueError, AttributeError):
            raise HTTPException(400, "lat/lng required")
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise HTTPException(400, "lat/lng out of range")
        cfg = load_config()
        cfg["home"] = {"lat": lat, "lng": lng, "label": label}
        save_config(cfg)
        return {"ok": True}

    @app.get("/api/history")
    async def get_history():
        return collector.history.snapshot()

    @app.post("/api/history/clear")
    async def clear_history(request: Request):
        if not check_origin(request.headers.get("origin")):
            raise HTTPException(403, "forbidden origin")
        collector.history.clear()
        return {"ok": True}

    @app.get("/api/addon-key")
    async def get_addon_key():
        # Only a page that already holds the access cookie can read this. The
        # add-on's helper script on the BeaconMap page picks it up from here.
        return {"app": "beaconmap", "key": addon_key, "port": port}

    def addon_cors(request: Request) -> dict:
        origin = request.headers.get("origin", "")
        if origin.startswith(("chrome-extension://", "moz-extension://")):
            return {"Access-Control-Allow-Origin": origin, "Access-Control-Allow-Headers": "content-type",
                    "Access-Control-Allow-Methods": "POST", "Vary": "Origin"}
        return {}

    @app.options("/api/sites")
    async def sites_preflight(request: Request):
        return Response(status_code=204, headers=addon_cors(request))

    @app.post("/api/sites")
    async def report_sites(request: Request):
        try:
            body = await request.json()
            key = str(body["key"])
            sites = list(body.get("sites") or [])[:MAX_SITES_PER_REPORT]
        except (KeyError, TypeError, ValueError, AttributeError):
            raise HTTPException(400, "bad report")
        if not secrets.compare_digest(key, addon_key):
            raise HTTPException(403, "wrong key")
        collector.sites.touch()
        accepted = sum(1 for s in sites if isinstance(s, dict) and collector.sites.add(s.get("ip"), s.get("host")))
        return JSONResponse({"ok": True, "accepted": accepted}, headers=addon_cors(request))

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        # WebSockets ignore CORS and skip the HTTP middleware, so all three
        # checks are repeated here.
        if (
            ws.headers.get("host") not in allowed_hosts
            or not check_origin(ws.headers.get("origin"))
            or not has_access(ws.cookies)
        ):
            await ws.close(code=1008)
            return
        await ws.accept()
        clients.add(ws)
        try:
            if latest["payload"]:
                await ws.send_text(latest["payload"])
            while True:
                await ws.receive_text()  # we don't expect messages; this detects disconnects
        except WebSocketDisconnect:
            pass
        finally:
            clients.discard(ws)

    static_dir = resources.files("beaconmap") / "static"
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
    return app
