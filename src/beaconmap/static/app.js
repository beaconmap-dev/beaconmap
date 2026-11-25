/* BeaconMap frontend: draws live connections from the local collector on a globe. */
(() => {
  "use strict";

  // ---------- helpers ----------
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  // Only touch the page when the HTML really changed, so hovering and clicking
  // aren't interrupted by live updates. Returns true if it changed.
  const setHtml = (el, html) => {
    if (el._html === html) return false;
    el._html = html;
    el.innerHTML = html;
    return true;
  };
  const appName = (a) => String(a || "Unknown").replace(/\.exe$/i, "");
  const store = {
    get(k, d) { try { const v = localStorage.getItem("beaconmap." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("beaconmap." + k, JSON.stringify(v)); } catch { /* private mode etc. */ } },
  };
  // Arc colours (r,g,b). "tracker" and "threat" are reserved for the upcoming
  // flagging feature: the collector does not set a flag yet.
  const FLAG = { tracker: "255,176,64", threat: "255,59,92" };
  const THEMES = {
    dark: {
      ocean: "#0b1424", emissive: "#070d18", land: "#2d3744", border: "rgba(255,255,255,0.10)",
      atmosphere: "#7fb0ff", direct: "222,238,255", cloud: "120,170,255", packet: "255,255,255", home: "77,163,255",
    },
    light: {
      ocean: "#c9d8e8", emissive: "#8ea2b9", land: "#f5f7fa", border: "rgba(30,50,80,0.28)",
      atmosphere: "#9cc4ff", direct: "24,58,110", cloud: "52,120,246", packet: "0,90,255", home: "0,113,227",
    },
  };
  const T = () => THEMES[state.theme] || THEMES.dark;
  const rgbOf = (d) => FLAG[d.flag] || (d.cloud ? T().cloud : T().direct);
  const PACKET_MS = 1100;
  const MAX_PACKETS = 40;
  const WORLD_EXPLAIN = "Shared worldwide address. Many data centres around the world answer on this same address, " +
    "and you reach whichever is nearest. The city shown is only the database's guess.";
  const THREAT_EXPLAIN = "This doesn't prove your computer is infected: lists can be out of date, and a bad server can share " +
    "an address with harmless ones. But check which app made this connection, and whether you expected it.";
  const siteList = (sites, max) => (sites.length > max
    ? `${sites.slice(0, max).join(", ")} +${sites.length - max}` : sites.join(", "));
  const orgLabel = (g) => (g.service ? `${g.org} · ${g.service}` : g.org);
  const placeLabel = (d) => (d.worldwide ? "Worldwide network" : (d.city || "Unknown city"));
  const CLOUD_EXPLAIN = "Cloud / CDN data centre. The owner rents servers to thousands of websites and apps, " +
    "so this location shows where the data centre is — not who you're really talking to.";

  // ---------- state ----------
  const state = {
    home: null,
    groups: [],
    locs: new Map(),        // key -> location object (reused so globe.gl keeps animations)
    seenLocs: new Set(),
    rings: [],
    packets: [],            // short-lived light pulses racing along an arc
    prevCounts: null,       // key -> connection count in the previous snapshot
    filterApp: null,
    search: "",
    selected: null,         // location key
    nerd: store.get("nerd", false),
    rotate: store.get("autorotate", false),
    theme: store.get("theme", "dark"),
    panelOpen: store.get("panel", window.innerWidth > 760),
    snapshot: null,
    closedAt: new Map(),    // group id -> when this page first saw it closed (drives the fade)
    linger: 8,              // seconds the collector keeps a closed group
    limited: false,
    threats: 0,
    pickingHome: false,
    addon: false,           // is the browser add-on reporting website names?
    addonPath: "",
    view: "live",           // which tab of the list is showing
    history: { started: 0, now: 0, total: 0, entries: [] },
    hideHome: false,        // true only while an image without your location is being drawn
    dbAgeDays: null,
  };

  // ---------- globe ----------
  const globe = new Globe($("globe"), { animateIn: true })
    .backgroundColor("rgba(0,0,0,0)")
    .showAtmosphere(true)
    .atmosphereColor("#7fb0ff")
    .atmosphereAltitude(0.13)
    .showGraticules(true)
    // land: matte slate on a navy ocean
    .polygonCapColor(() => T().land)
    .polygonSideColor(() => "rgba(0,0,0,0)")
    .polygonStrokeColor(() => T().border)
    .polygonAltitude(0.004)
    .polygonsTransitionDuration(0)
    // arcs: a steady thin thread per place, plus short-lived packets
    .arcsTransitionDuration(0)
    .arcStartLat(() => state.home.lat)
    .arcStartLng(() => state.home.lng)
    .arcEndLat((d) => d.lat)
    .arcEndLng((d) => d.lng)
    .arcColor((d) => {
      if (d.packet) return `rgba(${T().packet},1)`;
      const rgb = rgbOf(d);
      const boost = d.key === state.selected ? 1 : 0.7;
      return [`rgba(${rgb},${0.25 * boost * d.fade})`, `rgba(${rgb},${boost * d.fade})`];
    })
    .arcStroke((d) => {
      if (d.packet) return 0.4;
      return 0.1 + Math.min(0.3, Math.log2(d.count + 1) * 0.06) + (d.key === state.selected ? 0.25 : 0);
    })
    .arcAltitudeAutoScale(0.45)
    .arcDashLength((d) => (d.packet ? 0.12 : 1))
    .arcDashGap((d) => (d.packet ? 2 : 0))
    .arcDashInitialGap(0)
    .arcDashAnimateTime((d) => (d.packet ? PACKET_MS : 0))
    .arcLabel((d) => (d.packet ? "" : tipHtml(d)))
    .onArcClick((d) => select(d.key, true))
    .onGlobeClick((at) => pickHome(at))
    .onPolygonClick((_p, _e, at) => pickHome(at))
    // points
    .pointLat((d) => d.lat)
    .pointLng((d) => d.lng)
    .pointAltitude((d) => (d.home ? 0.012 : 0.007))
    .pointRadius((d) => (d.home ? 0.4 : 0.16 + Math.min(0.35, d.count * 0.02)))
    .pointColor((d) => (d.home ? `rgb(${T().home})` :`rgba(${rgbOf(d)},${0.35 + 0.6 * d.fade})`))
    .pointLabel((d) => (d.home ? `<div class="tip"><b>You</b><br>${esc(state.home.label || "Home")}</div>` : tipHtml(d)))
    .onPointClick((d) => !d.home && select(d.key, true))
    // rings: a slow "breathing" pulse at home, one soft ripple for a new place
    .ringLat((d) => d.lat)
    .ringLng((d) => d.lng)
    .ringColor((d) => (t) => `rgba(${d.home ? T().home : T().direct},${(1 - t) * (d.home ? 0.9 : 0.6)})`)
    .ringMaxRadius((d) => (d.home ? 2.6 : 3))
    .ringPropagationSpeed((d) => (d.home ? 1.1 : 2.5))
    .ringRepeatPeriod((d) => (d.home ? 2400 : 1200));

  const mat = globe.globeMaterial();
  mat.emissiveIntensity = 0.55;
  mat.shininess = 2;

  function applyTheme() {
    const t = T();
    document.documentElement.dataset.theme = state.theme;
    mat.color.set(t.ocean);
    mat.emissive.set(t.emissive);
    // re-setting an accessor makes globe.gl redraw that layer with the new colours
    globe.atmosphereColor(t.atmosphere)
      .polygonCapColor(globe.polygonCapColor())
      .polygonStrokeColor(globe.polygonStrokeColor())
      .arcColor(globe.arcColor())
      .pointColor(globe.pointColor())
      .ringColor(globe.ringColor());
    const btn = $("btn-theme");
    btn.textContent = state.theme === "dark" ? "☀" : "☾";
    btn.title = state.theme === "dark" ? "Switch to light mode" : "Switch to dark mode";
  }
  applyTheme();
  $("btn-theme").onclick = () => {
    state.theme = state.theme === "dark" ? "light" : "dark";
    store.set("theme", state.theme);
    applyTheme();
  };

  globe.controls().autoRotate = state.rotate;
  globe.controls().autoRotateSpeed = 0.35;
  const resize = () => globe.width(window.innerWidth).height(window.innerHeight);
  window.addEventListener("resize", resize);
  resize();

  fetch("vendor/countries-110m.json")
    .then((r) => r.json())
    .then((world) => {
      const land = cleanFeatures(topojson.feature(world, world.objects.countries).features);
      globe.polygonsData(land);
      flat.features = land;
      flat.landKey = "";
    })
    .catch(() => {});

  // The world map contains a few zero-size sliver polygons (e.g. one in North
  // Korea's outline) that can break shape processing. Drop them.
  function cleanFeatures(features) {
    const bigEnough = (poly) => {
      const xs = poly[0].map((p) => p[0]), ys = poly[0].map((p) => p[1]);
      return Math.max(...xs) - Math.min(...xs) > 0.01 && Math.max(...ys) - Math.min(...ys) > 0.01;
    };
    return features.map((f) => {
      const g = f.geometry;
      if (g.type === "Polygon") return bigEnough(g.coordinates) ? f : null;
      const polys = g.coordinates.filter(bigEnough);
      return polys.length ? { ...f, geometry: { type: "MultiPolygon", coordinates: polys } } : null;
    }).filter(Boolean);
  }

  function tipHtml(loc) {
    const apps = [...new Set(loc.groups.map((g) => appName(g.app)))];
    const orgs = [...new Set(loc.groups.map(orgLabel))];
    return `<div class="tip">${loc.flag === "threat" ? '<b class="bad">⚠ On a known-bad list</b><br>' : ""}` +
      `<b>${esc(orgs.join(", "))}</b><br>${esc(placeLabel(loc))}${loc.worldwide ? "" : ", " + esc(loc.country)}` +
      `<br>${esc(apps.slice(0, 4).join(", "))}${apps.length > 4 ? " +" + (apps.length - 4) : ""} · ${loc.count} conn</div>`;
  }

  // ---------- data -> globe ----------
  function visibleGroups() {
    const q = state.search.trim().toLowerCase();
    return state.groups.filter((g) => {
      if (state.filterApp && g.app !== state.filterApp) return false;
      if (!q) return true;
      return [g.app, g.org, g.service, g.city, g.country, g.cc, g.threat && "known bad threat", (g.sites || []).join(" ")].some((v) => String(v || "").toLowerCase().includes(q));
    });
  }

  // A packet of light races out whenever new connections open to a place.
  // (BeaconMap doesn't measure data volume, so this is "new activity", not bytes.)
  function detectSpikes(groups) {
    const counts = new Map();
    for (const g of groups) {
      const key = `${g.lat},${g.lng}`;
      counts.set(key, (counts.get(key) || 0) + g.count);
    }
    if (state.prevCounts) {
      const now = performance.now();
      let spawned = false;
      for (const [key, n] of counts) {
        if (n <= (state.prevCounts.get(key) || 0)) continue;
        if (state.packets.length >= MAX_PACKETS || state.packets.some((p) => p.key === key)) continue;
        const [lat, lng] = key.split(",").map(Number);
        state.packets.push({ packet: true, key, lat, lng, until: now + PACKET_MS });
        spawned = true;
      }
      if (spawned) setTimeout(pushGlobe, PACKET_MS + 60);
    }
    state.prevCounts = counts;
  }

  function rebuild() {
    if (!state.home) return;
    const groups = visibleGroups();
    const next = new Map();
    for (const g of groups) {
      const key = `${g.lat},${g.lng}`;
      let loc = next.get(key);
      if (!loc) {
        loc = state.locs.get(key) || { key, lat: g.lat, lng: g.lng };
        Object.assign(loc, { city: g.city, country: g.country, cc: g.cc, count: 0, fade: 0, active: false, cloudCount: 0, worldCount: 0, flag: null, groups: [] });
        next.set(key, loc);
      }
      loc.groups.push(g);
      loc.count += g.count;
      loc.fade = Math.max(loc.fade, g.fade);
      loc.active = loc.active || g.active;
      if (g.cloud) loc.cloudCount += 1;
      if (g.worldwide) loc.worldCount += 1;
      if (g.threat) loc.flag = "threat";
    }
    const now = performance.now();
    for (const loc of next.values()) {
      loc.cloud = loc.cloudCount === loc.groups.length;
      loc.worldwide = loc.worldCount === loc.groups.length;
      if (!state.seenLocs.has(loc.key)) {
        state.seenLocs.add(loc.key);
        if (state.snapshot) state.rings.push({ lat: loc.lat, lng: loc.lng, until: now + 1300 });
      }
    }
    state.locs = next;
    pushGlobe();
  }

  function pushGlobe() {
    if (!state.home) return;
    const now = performance.now();
    state.rings = state.rings.filter((r) => r.until > now);
    state.packets = state.packets.filter((p) => p.until > now);
    const locs = [...state.locs.values()];
    const home = { home: true, lat: state.home.lat, lng: state.home.lng };
    if (state.hideHome) {
      // every line starts at home, so hiding home means hiding the lines too
      globe.arcsData([]).pointsData(locs).ringsData([]);
      return;
    }
    globe.arcsData([...locs, ...state.packets.filter((p) => state.locs.has(p.key))]);
    globe.pointsData([home, ...locs]);
    globe.ringsData([home, ...state.rings]);
  }

  // ---------- panel ----------
  function renderChips() {
    const byApp = new Map();
    for (const g of state.groups) if (g.active) byApp.set(g.app, (byApp.get(g.app) || 0) + g.count);
    const top = [...byApp.entries()].sort((a, b) => b[1] - a[1]).slice(0, 30);
    if (state.filterApp && !byApp.has(state.filterApp)) top.push([state.filterApp, 0]);
    setHtml($("app-chips"),
      `<button class="chip ${state.filterApp ? "" : "on"}" data-app="">All</button>` +
      top.map(([a, n]) => `<button class="chip ${a === state.filterApp ? "on" : ""}" data-app="${esc(a)}">${esc(appName(a))}<b>${n}</b></button>`).join(""));
  }

  // The collector only says "closed"; the page times the fade-out itself, so a
  // quiet network sends nothing at all. Returns true while anything is fading.
  function stampFades() {
    const now = performance.now();
    const live = new Set();
    let fading = false;
    for (const g of state.groups) {
      live.add(g.id);
      if (g.active) { state.closedAt.delete(g.id); g.fade = 1; continue; }
      if (!state.closedAt.has(g.id)) state.closedAt.set(g.id, now);
      g.fade = Math.max(0, 1 - (now - state.closedAt.get(g.id)) / (state.linger * 1000));
      fading = true;
    }
    for (const id of [...state.closedAt.keys()]) if (!live.has(id)) state.closedAt.delete(id);
    return fading;
  }
  setInterval(() => { if (stampFades()) renderAll(); }, 500);

  const rowEls = new Map(); // group id -> its <li>, reused between updates

  function renderRows() {
    const groups = visibleGroups().slice().sort((a, b) => (!!b.threat - !!a.threat) || (b.active - a.active) || (b.count - a.count) || a.app.localeCompare(b.app));
    $("empty").classList.toggle("hidden", groups.length > 0);
    $("empty").textContent = state.groups.length ? "Nothing matches your filter." : "Waiting for connections…";
    const list = $("rows");
    const wanted = new Set(groups.map((g) => g.id));
    for (const [id, li] of rowEls) if (!wanted.has(id)) { li.remove(); rowEls.delete(id); }
    let prev = null;
    for (const g of groups) {
      let li = rowEls.get(g.id);
      if (!li) { li = document.createElement("li"); rowEls.set(g.id, li); }
      const key = `${g.lat},${g.lng}`;
      const cls = `row${g.active ? "" : " closed"}${key === state.selected ? " sel" : ""}${g.threat ? " bad" : ""}`;
      const opacity = g.active ? "" : String(Math.round((0.15 + 0.35 * g.fade) * 100) / 100);
      if (li.dataset.key !== key) li.dataset.key = key;
      if (li.className !== cls) li.className = cls;
      if (li.style.opacity !== opacity) li.style.opacity = opacity;
      setHtml(li,
        `<span class="app">${esc(appName(g.app))} <span style="color:var(--muted);font-weight:400">→ ${esc(orgLabel(g))}</span></span>` +
        `<span class="count">${g.active ? g.count : "×"}</span>` +
        `<span class="where">${g.worldwide ? "" : `<span class="cc">${esc(g.cc || "??")}</span>`}${esc(g.worldwide ? "Worldwide network" : (g.city || g.country || "Unknown"))}` +
        `${g.threat ? '<span class="tag bad">known bad</span>' : ""}${g.cloud ? '<span class="tag cloud">cloud</span>' : ""}${g.ipv6 ? '<span class="tag v6">ipv6</span>' : ""}</span>` +
        (g.sites && g.sites.length ? `<span class="sites">${esc(siteList(g.sites, 2))}</span>` : ""));
      // put it in order, without moving rows that are already in the right place
      const next = prev ? prev.nextSibling : list.firstChild;
      if (next !== li) list.insertBefore(li, next);
      prev = li;
    }
  }

  function renderDetails() {
    const el = $("details");
    const loc = state.selected && state.locs.get(state.selected);
    if (!loc) { el.classList.add("hidden"); return; }
    el.classList.remove("hidden");
    const orgs = [...new Set(loc.groups.map(orgLabel))];
    const threats = [...new Set(loc.groups.map((g) => g.threat).filter(Boolean))];
    // Per-site breakdown: each website once, with who served it and how busy it is
    const bySite = new Map();
    for (const g of loc.groups) {
      for (const s of g.sites || []) {
        const e = bySite.get(s) || { name: s, orgs: new Set(), apps: new Set(), conns: 0, live: false };
        e.orgs.add(g.org);
        e.apps.add(appName(g.app));
        if (g.active) { e.conns += g.count; e.live = true; }
        bySite.set(s, e);
      }
    }
    const multiApp = new Set(loc.groups.filter((g) => g.sites && g.sites.length).map((g) => g.app)).size > 1;
    const sites = [...bySite.values()].sort((a, b) => (b.live - a.live) || (b.conns - a.conns) || a.name.localeCompare(b.name));
    const siteHtml = sites.length
      ? `<h4 class="section">Websites (${sites.length})</h4><table class="sitetable">` +
        sites.map((e) => `<tr><td><span class="sitenames">${esc(e.name)}</span><div class="muted small">via ${esc([...e.orgs].join(", "))}` +
          `${multiApp ? ` · ${esc([...e.apps].join(", "))}` : ""}</div></td><td>${e.live ? e.conns : "closed"}</td></tr>`).join("") +
        "</table>"
      : "";
    const rows = loc.groups.slice().sort((a, b) => b.count - a.count).map((g) =>
      `<tr><td>${esc(appName(g.app))} → ${esc(orgLabel(g))}${g.threat ? ' <span class="tag bad">known bad</span>' : ""}` +
      `${state.nerd ? `<div class="nerd">AS${esc(g.asn ?? "?")} · ${esc(g.protocols.join("/"))} · ports ${esc(g.ports.join(", "))}<br>${esc(g.ips.join(", "))}</div>` : ""}</td>` +
      `<td>${g.active ? g.count : "closed"}</td></tr>`).join("");
    const changed = setHtml(el, `<button class="close" aria-label="Close">×</button>` +
      `<h3>${esc(orgs.join(", "))}</h3>` +
      `<div class="sub">${loc.worldwide ? `Worldwide network (drawn at ${esc(loc.city || loc.country || "a guessed spot")})` : `${esc(loc.city || "Unknown city")}, ${esc(loc.country || "Unknown country")}`} · ${loc.count} active connection${loc.count === 1 ? "" : "s"}</div>` +
      threats.map((t) => `<div class="explain bad">⚠ <b>On the ${esc(t)}.</b> ${esc(THREAT_EXPLAIN)}</div>`).join("") +
      (!state.addon && loc.groups.some((g) => g.browser)
        ? '<div class="explain offer">Want to know which websites these are? <a href="#" id="addon-link">Add the BeaconMap browser add-on</a> (optional).</div>' : "") +
      (loc.worldwide ? `<div class="explain">🌐 ${esc(WORLD_EXPLAIN)}</div>` : "") +
      (loc.cloud && !loc.worldwide ? `<div class="explain">☁ ${esc(CLOUD_EXPLAIN)}</div>` : "") +
      siteHtml +
      (siteHtml ? '<h4 class="section">Apps</h4>' : "") +
      `<table>${rows}</table>`);
    if (changed) el.querySelector(".close").onclick = () => select(null);
    const link = el.querySelector("#addon-link");
    if (link) link.onclick = (e) => { e.preventDefault(); openAddonHelp(); };
  }

  function renderStats(snap) {
    const s = snap.stats;
    $("s-conn").textContent = s.connections;
    $("s-co").textContent = s.companies;
    $("s-cc").textContent = s.countries;
    $("s-apps").textContent = s.apps;
    $("lan").textContent = s.local;
    // "—" = no known-bad list installed, which is different from a real zero
    $("s-bad").textContent = s.threats == null ? "—" : s.threats;
    $("stat-bad").classList.toggle("alert", s.threats > 0);
    $("stat-bad").title = s.threats == null
      ? "No known-bad list installed. Run: beaconmap --update-db"
      : "Connections to servers on a public known-bad list. Zero is not a guarantee: BeaconMap can't see everything.";
    state.threats = s.threats || 0;
    state.limited = !!snap.limited;
    state.network = snap.network || { vpn: [], proxy: "" };
    renderBanners();
  }

  function renderBanners() {
    const banners = [];
    if (state.limited) banners.push("Your OS is hiding other apps' connections. Run BeaconMap with sudo / as administrator to see everything.");
    if (state.dbAgeDays > 100) {
      banners.push(`The location database is about ${Math.floor(state.dbAgeDays / 30)} months old, so some servers may be placed wrongly. ` +
        "Refresh it by running: beaconmap --update-db");
    }
    let html = banners.map((b) => `<div class="banner">${esc(b)}</div>`).join("");
    // A VPN or proxy sits between this computer and the real servers, so the
    // map shows the VPN/proxy server instead. Say so, once, and let it be hidden.
    const net = state.network || { vpn: [], proxy: "" };
    const netKey = `${net.vpn.join(",")}|${net.proxy}`;
    if ((net.vpn.length || net.proxy) && netKey !== store.get("netDismissed", "")) {
      const what = net.vpn.length
        ? `A VPN looks switched on (${net.vpn.join(", ")}). Most traffic goes to the VPN server first, so the map may show the VPN's location instead of the real servers.`
        : `This computer is set to use a proxy (${net.proxy}). Apps that follow it connect to the proxy, so their real destinations won't show on the map.`;
      html += `<div class="banner net">${esc(what)}<button class="banner-x" id="net-dismiss" aria-label="Hide this">×</button></div>`;
    }
    if (state.threats > 0) {
      html = `<div class="banner bad">⚠ ${state.threats} connection${state.threats === 1 ? "" : "s"} to a server on a public known-bad list. ` +
        "Click the red row in the list for details.</div>" + html;
    }
    if (state.pickingHome) html += `<div class="banner hint"><i class="hint-dot"></i>Click the ${flat.on ? "map" : "globe"} where you are. Press Esc to cancel.</div>`;
    // Quiet network: say so, or a blank globe looks like a broken app
    if (state.snapshot !== null && !state.groups.length) {
      html += '<div class="banner hint"><i class="hint-dot"></i>Listening for network traffic… open a website or an app and watch it appear.</div>';
    }
    setHtml($("banners"), html);
  }
  $("banners").addEventListener("click", (e) => {
    if (e.target.id !== "net-dismiss") return;
    const net = state.network;
    store.set("netDismissed", `${net.vpn.join(",")}|${net.proxy}`);
    renderBanners();
  });

  // ---------- flat map ----------
  // The same data as the globe, drawn on a flat world map so every place is
  // visible at once. Drag to move, scroll to zoom, double-click to reset.
  const flat = {
    on: store.get("flat", false),
    canvas: $("flat"), ctx: $("flat").getContext("2d"),
    k: 1, cx: 0, cy: 15,                       // zoom, and the lng/lat at the centre of the screen
    features: [], land: document.createElement("canvas"), landKey: "",
    arcs: new Map(),                           // location key -> points along its line
    hover: null, drag: null,
  };
  const clampN = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const flatScale = () => Math.min(innerWidth / 360, innerHeight / 165) * flat.k;   // pixels per degree
  const fx = (lng) => (lng - flat.cx) * flatScale() + innerWidth / 2;
  const fy = (lat) => (flat.cy - lat) * flatScale() + innerHeight / 2;
  const unproject = (x, y) => ({ lng: (x - innerWidth / 2) / flatScale() + flat.cx, lat: flat.cy - (y - innerHeight / 2) / flatScale() });

  function clampFlat() {
    flat.k = clampN(flat.k, 1, 24);
    const s = flatScale();
    const halfW = innerWidth / 2 / s, halfH = innerHeight / 2 / s;
    flat.cx = halfW >= 180 ? 0 : clampN(flat.cx, -180 + halfW, 180 - halfW);
    flat.cy = halfH >= 90 ? clampN(flat.cy, -20, 20) : clampN(flat.cy, -90 + halfH, 90 - halfH);
  }

  function sizeFlat() {
    const d = window.devicePixelRatio || 1;
    for (const c of [flat.canvas, flat.land]) {
      c.width = Math.round(innerWidth * d);
      c.height = Math.round(innerHeight * d);
    }
    flat.landKey = "";
  }
  window.addEventListener("resize", sizeFlat);

  // Land, ocean and grid only change when you move, zoom, resize or switch
  // theme, so they are drawn once and reused for every frame.
  function drawLand() {
    const key = [flat.k, flat.cx, flat.cy, flat.land.width, flat.land.height, state.theme, flat.features.length].join("|");
    if (key === flat.landKey) return;
    flat.landKey = key;
    const d = window.devicePixelRatio || 1, c = flat.land.getContext("2d"), t = T();
    c.setTransform(d, 0, 0, d, 0, 0);
    c.clearRect(0, 0, innerWidth, innerHeight);
    c.fillStyle = t.ocean;
    c.fillRect(fx(-180), fy(90), fx(180) - fx(-180), fy(-90) - fy(90));
    c.strokeStyle = t.border;
    c.lineWidth = 0.5;
    c.beginPath();
    for (let lng = -180; lng <= 180; lng += 30) { c.moveTo(fx(lng), fy(90)); c.lineTo(fx(lng), fy(-90)); }
    for (let lat = -60; lat <= 60; lat += 30) { c.moveTo(fx(-180), fy(lat)); c.lineTo(fx(180), fy(lat)); }
    c.stroke();
    c.fillStyle = t.land;
    c.lineWidth = 0.6;
    // Shapes that cross the map's left/right edge (eastern Russia, Fiji) are
    // drawn twice, once at each edge, and trimmed to the map. Otherwise they
    // smear a stripe across the whole world.
    c.save();
    c.beginPath();
    c.rect(fx(-180), fy(90), fx(180) - fx(-180), fy(-90) - fy(90));
    c.clip();
    c.beginPath();
    const trace = (ring, shift) => {
      let prev = null, lng = 0;
      ring.forEach((p, i) => {
        lng = prev === null ? p[0] : p[0] + 360 * Math.round((prev - p[0]) / 360);   // no 360° jumps
        prev = lng;
        if (i) c.lineTo(fx(lng + shift), fy(p[1])); else c.moveTo(fx(lng + shift), fy(p[1]));
      });
      c.closePath();
    };
    for (const f of flat.features) {
      const polys = f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates;
      for (const poly of polys) {
        for (const ring of poly) {
          const crosses = ring.some((p, i) => i && Math.abs(p[0] - ring[i - 1][0]) > 180);
          trace(ring, 0);
          if (crosses) { trace(ring, -360); trace(ring, 360); }
        }
      }
    }
    c.fill("evenodd");
    c.stroke();
    c.restore();
  }

  // Points along the shortest path over the earth's surface, which is why
  // long lines curve on a flat map.
  function arcPoints(lat1, lng1, lat2, lng2, n = 48) {
    const R = Math.PI / 180;
    const vec = (lat, lng) => { const c = Math.cos(lat * R); return [c * Math.cos(lng * R), c * Math.sin(lng * R), Math.sin(lat * R)]; };
    const a = vec(lat1, lng1), b = vec(lat2, lng2);
    const angle = Math.acos(clampN(a[0] * b[0] + a[1] * b[1] + a[2] * b[2], -1, 1));
    const pts = [];
    for (let i = 0; i <= n; i++) {
      const t = i / n;
      let p = a;
      if (angle > 1e-6) {
        const s1 = Math.sin((1 - t) * angle) / Math.sin(angle), s2 = Math.sin(t * angle) / Math.sin(angle);
        p = [a[0] * s1 + b[0] * s2, a[1] * s1 + b[1] * s2, a[2] * s1 + b[2] * s2];
      }
      pts.push([Math.asin(clampN(p[2], -1, 1)) / R, Math.atan2(p[1], p[0]) / R]);
    }
    return pts;
  }
  function arcFor(loc) {
    let pts = flat.arcs.get(loc.key);
    if (!pts) { pts = arcPoints(state.home.lat, state.home.lng, loc.lat, loc.lng); flat.arcs.set(loc.key, pts); }
    return pts;
  }

  function drawFlat(now) {
    const d = window.devicePixelRatio || 1, c = flat.ctx, t = T();
    drawLand();
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.clearRect(0, 0, flat.canvas.width, flat.canvas.height);
    c.drawImage(flat.land, 0, 0);
    c.setTransform(d, 0, 0, d, 0, 0);
    if (!state.home) return;
    const locs = [...state.locs.values()];
    for (const key of [...flat.arcs.keys()]) if (!state.locs.has(key)) flat.arcs.delete(key);

    if (!state.hideHome) {
      c.lineCap = "round";
      for (const loc of locs) {
        const sel = loc.key === state.selected;
        c.strokeStyle = `rgba(${rgbOf(loc)},${(sel ? 1 : 0.6) * loc.fade})`;
        c.lineWidth = 0.7 + Math.min(1.6, Math.log2(loc.count + 1) * 0.35) + (sel ? 1.2 : 0);
        c.beginPath();
        let prev = null;
        for (const [lat, lng] of arcFor(loc)) {
          // a line that crosses the edge of the map is cut there, not drawn across it
          if (prev === null || Math.abs(lng - prev) > 180) c.moveTo(fx(lng), fy(lat)); else c.lineTo(fx(lng), fy(lat));
          prev = lng;
        }
        c.stroke();
      }
      // packets of light for new activity
      for (const p of state.packets) {
        const loc = state.locs.get(p.key);
        if (!loc || p.until <= now) continue;
        const pts = arcFor(loc);
        // a packet made just after this frame's timestamp would give a negative index
        const [lat, lng] = pts[clampN(Math.floor((1 - (p.until - now) / PACKET_MS) * pts.length), 0, pts.length - 1)];
        c.fillStyle = `rgba(${t.packet},1)`;
        c.shadowColor = `rgba(${t.packet},0.9)`;
        c.shadowBlur = 8;
        c.beginPath(); c.arc(fx(lng), fy(lat), 2.6, 0, 7); c.fill();
        c.shadowBlur = 0;
      }
    }
    for (const loc of locs) {
      c.fillStyle = `rgba(${rgbOf(loc)},${0.35 + 0.6 * loc.fade})`;
      c.beginPath(); c.arc(fx(loc.lng), fy(loc.lat), 2.2 + Math.min(4, loc.count * 0.25) + (loc.key === state.selected ? 1.5 : 0), 0, 7); c.fill();
    }
    if (!state.hideHome) {
      for (const r of state.rings) {
        const ph = 1 - (r.until - now) / 1300;
        if (ph < 0 || ph > 1) continue;
        c.strokeStyle = `rgba(${t.direct},${(1 - ph) * 0.6})`;
        c.lineWidth = 1;
        c.beginPath(); c.arc(fx(r.lng), fy(r.lat), 3 + ph * 16, 0, 7); c.stroke();
      }
      const hx = fx(state.home.lng), hy = fy(state.home.lat), ph = (now % 2400) / 2400;
      c.strokeStyle = `rgba(${t.home},${(1 - ph) * 0.9})`;
      c.lineWidth = 1.5;
      c.beginPath(); c.arc(hx, hy, 5 + ph * 18, 0, 7); c.stroke();
      c.fillStyle = `rgb(${t.home})`;
      c.beginPath(); c.arc(hx, hy, 4.5, 0, 7); c.fill();
    }
  }
  function flatLoop(now) {
    if (!flat.on) return;
    state.rings = state.rings.filter((r) => r.until > now);
    state.packets = state.packets.filter((p) => p.until > now);
    drawFlat(now);
    requestAnimationFrame(flatLoop);
  }

  function setFlat(on) {
    flat.on = on;
    store.set("flat", on);
    $("globe").style.display = on ? "none" : "";
    flat.canvas.classList.toggle("hidden", !on);
    $("flat-tip").classList.add("hidden");
    const btn = $("btn-view");
    btn.textContent = on ? "🌐" : "🗺";
    btn.title = on ? "Switch to the globe" : "Switch to the flat map";
    $("home-pick").textContent = on ? "Pick it on the map" : "Pick it on the globe";
    if (on) {
      globe.pauseAnimation();
      sizeFlat();
      clampFlat();
      requestAnimationFrame(flatLoop);
    } else {
      globe.resumeAnimation();
      resize();
    }
  }
  $("btn-view").onclick = () => setFlat(!flat.on);

  // Turn whichever view is showing towards a place
  function flyTo(lat, lng) {
    globe.controls().autoRotate = false;
    globe.pointOfView({ lat, lng, altitude: 1.9 }, 900);
    flat.cx = lng;
    flat.cy = lat;
    flat.k = Math.max(flat.k, 3);
    clampFlat();
  }

  function flatHit(x, y) {
    let best = null, bestD = 14 * 14;
    for (const loc of state.locs.values()) {
      const dx = fx(loc.lng) - x, dy = fy(loc.lat) - y, dd = dx * dx + dy * dy;
      if (dd < bestD) { best = loc; bestD = dd; }
    }
    return best;
  }
  flat.canvas.addEventListener("pointerdown", (e) => {
    flat.drag = { x: e.clientX, y: e.clientY, cx: flat.cx, cy: flat.cy, moved: false };
    flat.canvas.setPointerCapture(e.pointerId);
  });
  flat.canvas.addEventListener("pointermove", (e) => {
    const tip = $("flat-tip");
    if (flat.drag) {
      const dx = e.clientX - flat.drag.x, dy = e.clientY - flat.drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 4) flat.drag.moved = true;
      if (flat.drag.moved && !state.pickingHome) {
        flat.cx = flat.drag.cx - dx / flatScale();
        flat.cy = flat.drag.cy + dy / flatScale();
        clampFlat();
        tip.classList.add("hidden");
      }
      return;
    }
    const loc = state.pickingHome ? null : flatHit(e.clientX, e.clientY);
    flat.canvas.style.cursor = state.pickingHome ? "crosshair" : loc ? "pointer" : "grab";
    tip.classList.toggle("hidden", !loc);
    if (loc) {
      setHtml(tip, tipHtml(loc));
      tip.style.left = Math.min(e.clientX + 14, innerWidth - 260) + "px";
      tip.style.top = (e.clientY + 14) + "px";
    }
  });
  flat.canvas.addEventListener("pointerup", (e) => {
    const drag = flat.drag;
    flat.drag = null;
    if (!drag || drag.moved) return;
    if (state.pickingHome) { pickHome(unproject(e.clientX, e.clientY)); return; }
    const loc = flatHit(e.clientX, e.clientY);
    if (loc) select(loc.key, false);
  });
  flat.canvas.addEventListener("pointerleave", () => $("flat-tip").classList.add("hidden"));
  flat.canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const before = unproject(e.clientX, e.clientY);
    flat.k = clampN(flat.k * Math.exp(-e.deltaY * 0.0015), 1, 24);
    const after = unproject(e.clientX, e.clientY);
    flat.cx += before.lng - after.lng;   // keep the spot under the cursor where it is
    flat.cy += before.lat - after.lat;
    clampFlat();
  }, { passive: false });
  flat.canvas.addEventListener("dblclick", () => { flat.k = 1; flat.cx = 0; flat.cy = 15; clampFlat(); });
  if (flat.on) setFlat(true);

  // ---------- history: everything seen since BeaconMap started ----------
  const RECENT_MS = 5 * 60 * 1000;
  const clockTime = (sec) => new Date(sec * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  function ago(sec) {
    const s = Math.max(0, Math.round(Date.now() / 1000 - sec));
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.floor(s / 60)} min ago`;
    return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min ago`;
  }
  function matchesFilter(g) {
    if (state.filterApp && g.app !== state.filterApp) return false;
    const q = state.search.trim().toLowerCase();
    if (!q) return true;
    return [g.app, g.org, g.service, g.city, g.country, g.cc, g.threat && "known bad threat", (g.sites || []).join(" ")]
      .some((v) => String(v || "").toLowerCase().includes(q));
  }
  function pastRowHtml(e) {
    return `<span class="app">${esc(appName(e.app))} <span style="color:var(--muted);font-weight:400">→ ${esc(orgLabel(e))}</span></span>` +
      `<span class="when ${e.active ? "now" : ""}">${e.active ? "live" : esc(ago(e.last_seen))}</span>` +
      `<span class="where">${e.worldwide ? "" : `<span class="cc">${esc(e.cc || "??")}</span>`}${esc(e.worldwide ? "Worldwide network" : (e.city || e.country || "Unknown"))}` +
      `${e.threat ? '<span class="tag bad">known bad</span>' : ""}${e.cloud ? '<span class="tag cloud">cloud</span>' : ""}</span>` +
      (e.sites && e.sites.length ? `<span class="sites">${esc(siteList(e.sites, 3))}</span>` : "") +
      `<span class="seen">first seen ${esc(clockTime(e.first_seen))} · up to ${e.peak} at once</span>`;
  }
  const pastEls = { recent: new Map(), history: new Map() };
  function renderPastList(listId, entries) {
    const list = $(listId), els = pastEls[listId];
    const wanted = new Set(entries.map((e) => e.id));
    for (const [id, li] of els) if (!wanted.has(id)) { li.remove(); els.delete(id); }
    let prev = null;
    for (const e of entries) {
      let li = els.get(e.id);
      if (!li) { li = document.createElement("li"); els.set(e.id, li); }
      const cls = `row past${e.threat ? " bad" : ""}`;
      if (li.className !== cls) li.className = cls;
      li.dataset.lat = e.lat;
      li.dataset.lng = e.lng;
      setHtml(li, pastRowHtml(e));
      const next = prev ? prev.nextSibling : list.firstChild;
      if (next !== li) list.insertBefore(li, next);
      prev = li;
    }
  }
  function renderHistory() {
    const h = state.history;
    $("history-count").textContent = h.total ? h.total : "";
    const liveIds = new Set(state.groups.filter((g) => g.active).map((g) => g.id));
    const cutoff = Date.now() / 1000 - RECENT_MS / 1000;
    const recent = h.entries.filter((e) => !e.active && !liveIds.has(e.id) && e.last_seen >= cutoff && matchesFilter(e)).slice(0, 8);
    $("recent-wrap").classList.toggle("hidden", recent.length === 0);
    renderPastList("recent", recent);
    if (state.view !== "history") return;
    const all = h.entries.filter(matchesFilter).sort((a, b) => (!!b.threat - !!a.threat) || (b.active - a.active) || (b.last_seen - a.last_seen));
    $("history-since").textContent = h.started ? `since ${clockTime(h.started)}` : "";
    $("history-empty").classList.toggle("hidden", all.length > 0);
    $("history-empty").textContent = h.entries.length ? "Nothing matches your filter." : "Nothing yet.";
    renderPastList("history", all);
  }
  async function loadHistory() {
    if (document.hidden) return;
    try {
      const r = await fetch("api/history");
      if (r.ok) { state.history = await r.json(); renderHistory(); }
    } catch { /* server stopped: keep what we have */ }
  }
  setInterval(loadHistory, 3000);

  function setView(view) {
    state.view = view;
    $("tab-live").classList.toggle("on", view === "live");
    $("tab-history").classList.toggle("on", view === "history");
    $("view-live").classList.toggle("hidden", view !== "live");
    $("view-history").classList.toggle("hidden", view !== "history");
    renderHistory();
  }
  $("tab-live").onclick = () => setView("live");
  $("tab-history").onclick = () => { setView("history"); loadHistory(); };
  $("history-clear").onclick = async (e) => {
    e.preventDefault();
    try { await fetch("api/history/clear", { method: "POST" }); } catch { /* ignore */ }
    loadHistory();
  };
  // clicking a past connection turns the globe to where it was
  for (const id of ["recent", "history"]) {
    $(id).addEventListener("click", (e) => {
      const li = e.target.closest(".row");
      if (!li) return;
      flyTo(Number(li.dataset.lat), Number(li.dataset.lng));
    });
  }

  function renderAll() {
    rebuild();
    renderChips();
    renderRows();
    renderDetails();
    renderHistory();
  }

  function select(key, fly) {
    state.selected = key;
    if (key && fly) {
      const loc = state.locs.get(key);
      if (loc) {
        flyTo(loc.lat, loc.lng);
      }
    }
    // re-evaluate colour and thickness for the highlight
    globe.arcColor(globe.arcColor()).arcStroke(globe.arcStroke());
    renderRows();
    renderDetails();
  }

  // ---------- UI events ----------
  $("app-chips").addEventListener("click", (e) => {
    const b = e.target.closest(".chip");
    if (!b) return;
    state.filterApp = b.dataset.app || null;
    renderAll();
  });
  $("rows").addEventListener("click", (e) => {
    const r = e.target.closest(".row");
    if (r) select(r.dataset.key, true);
  });
  $("search").addEventListener("input", (e) => { state.search = e.target.value; renderAll(); });

  const panel = $("panel");
  panel.classList.toggle("collapsed", !state.panelOpen);
  $("btn-panel").onclick = () => {
    state.panelOpen = !state.panelOpen;
    panel.classList.toggle("collapsed", !state.panelOpen);
    store.set("panel", state.panelOpen);
  };

  // ---------- settings / home ----------
  const homes = window.BEACON_HOMES || [];     // timezone -> city, for the first guess
  const cities = window.BEACON_CITIES || [];   // searchable list: [label, lat, lng]
  const cityIndex = cities.map((c) => c[0].toLowerCase());
  let pendingHome = null;                      // chosen in the dialog, applied on Save

  function searchCities(text) {
    const q = text.trim().toLowerCase();
    if (q.length < 2) return [];
    const starts = [], contains = [];
    for (let i = 0; i < cities.length && starts.length < 8; i++) {
      const at = cityIndex[i].indexOf(q);
      if (at === 0) starts.push(cities[i]);
      else if (at > 0 && contains.length < 8) contains.push(cities[i]);
    }
    return [...starts, ...contains].slice(0, 8);
  }

  function showHomeChoice(home, note) {
    pendingHome = home;
    $("home-current").textContent = home ? `${home.label} (${home.lat}, ${home.lng})${note ? " — " + note : ""}` : "";
  }

  function renderCityResults() {
    const hits = searchCities($("home-search").value);
    setHtml($("home-results"), hits.map((c, i) => `<li data-i="${i}">${esc(c[0])}</li>`).join("") ||
      ($("home-search").value.trim().length >= 2 ? '<li class="none">No match. Try a bigger city nearby, or pick it on the globe.</li>' : ""));
    $("home-results")._hits = hits;
  }
  function chooseCity(c) {
    if (!c) return;
    showHomeChoice({ label: c[0], lat: c[1], lng: c[2] }, "press Save");
    $("home-search").value = "";
    renderCityResults();
  }
  $("home-search").addEventListener("input", renderCityResults);
  $("home-search").addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();   // Enter must not close the dialog
    chooseCity(($("home-results")._hits || [])[0]);
  });
  $("home-results").addEventListener("click", (e) => {
    const li = e.target.closest("li[data-i]");
    if (li) chooseCity($("home-results")._hits[Number(li.dataset.i)]);
  });

  // Precise location: the BROWSER works this out, usually by sending nearby
  // Wi-Fi details to its location service. BeaconMap only receives the result.
  $("home-precise").onclick = () => {
    const msg = $("home-precise-msg");
    if (!navigator.geolocation) { msg.textContent = "This browser can't share a location."; return; }
    msg.textContent = "Waiting for the browser…";
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const r = (v) => Math.round(v * 1000) / 1000;
        showHomeChoice({ label: "My location", lat: r(pos.coords.latitude), lng: r(pos.coords.longitude) }, "press Save");
        msg.textContent = "Got it.";
      },
      (err) => {
        msg.textContent = err.code === 1
          ? "The browser was not allowed to share a location. Nothing changed."
          : "The browser couldn't work out a location. Search for your city instead.";
      },
      { enableHighAccuracy: false, timeout: 15000, maximumAge: 600000 },
    );
  };

  function guessHome() {
    // best: this computer's own public address, looked up in the offline database
    if (state.homeGuess) return state.homeGuess;
    let tz = "";
    try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch { /* ignore */ }
    const hit = homes.find((h) => h[0] === tz);
    if (hit) return { label: hit[1], lat: hit[2], lng: hit[3] };
    const region = tz.split("/")[0];
    const sameRegion = homes.find((h) => h[0].startsWith(region + "/"));
    const h = sameRegion || homes.find((x) => x[0] === "Europe/London");
    return { label: h[1], lat: h[2], lng: h[3] };
  }

  function openSettings(firstRun) {
    const cur = state.home || guessHome();
    $("settings-title").textContent = firstRun ? "Where are you?" : "Settings";
    $("settings-intro").style.display = firstRun ? "" : "none";
    $("settings-cancel").style.display = firstRun ? "none" : "";
    showHomeChoice(cur, firstRun ? "our guess" : "");
    $("home-search").value = "";
    renderCityResults();
    $("home-precise-msg").textContent = "";
    $("home-lat").value = "";
    $("home-lng").value = "";
    $("nerd").checked = state.nerd;
    $("rotate").checked = state.rotate;
    $("settings").showModal();
  }
  $("btn-settings").onclick = () => openSettings(false);

  // "Pick it on the globe": the next click on the globe becomes home
  const stopPicking = () => {
    state.pickingHome = false;
    document.body.classList.remove("picking");
    renderBanners();
  };
  $("home-pick").onclick = () => {
    state.pickingHome = true;
    $("settings").close("pick");
    document.body.classList.add("picking");
    renderBanners();
  };
  function pickHome(at) {
    if (!state.pickingHome || !at) return;
    stopPicking();
    setHome({ label: "Custom location", lat: Math.round(at.lat * 100) / 100, lng: Math.round(at.lng * 100) / 100 }, true);
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && state.pickingHome) stopPicking(); });

  $("settings").addEventListener("close", async () => {
    if ($("settings").returnValue !== "save") return;
    state.nerd = $("nerd").checked;
    state.rotate = $("rotate").checked;
    store.set("nerd", state.nerd);
    store.set("autorotate", state.rotate);
    globe.controls().autoRotate = state.rotate;

    const lat = parseFloat($("home-lat").value), lng = parseFloat($("home-lng").value);
    const typed = Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180;
    const home = typed ? { label: "Custom location", lat, lng } : pendingHome;
    if (home) await setHome(home, true);
  });

  async function setHome(home, save) {
    state.home = home;
    if (save) {
      try {
        await fetch("api/home", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(home) });
      } catch { /* server down; still use it for this session */ }
    }
    globe.pointOfView({ lat: home.lat, lng: home.lng, altitude: 2.4 }, 1200);
    flat.arcs.clear();   // every line starts at home, so they all change
    globe.arcsData([]); // force start points to refresh
    renderAll();
  }

  // ---------- browser add-on ----------
  function openAddonHelp() {
    $("addon-path").textContent = state.addonPath || "the 'extension' folder inside BeaconMap";
    $("addon-status").textContent = state.addon ? "Connected: website names are showing." : "Not connected yet.";
    $("addon").showModal();
  }
  $("btn-addon").onclick = openAddonHelp;
  $("addon-pill").onclick = openAddonHelp;

  // ---------- save the globe as an image ----------
  // Made entirely in the browser: nothing is uploaded. The list of apps is
  // never part of the image, and your location can be left out.
  $("btn-share").onclick = () => {
    $("share-hide").checked = store.get("shareHide", true);
    $("share").showModal();
  };
  $("share").addEventListener("close", () => {
    if ($("share").returnValue !== "save") return;
    const hide = $("share-hide").checked;
    store.set("shareHide", hide);
    saveImage(hide).catch((err) => console.error("BeaconMap: could not save the image", err));
  });

  const pause = (ms) => new Promise((r) => setTimeout(r, ms));
  const nextFrame = () => new Promise((r) => requestAnimationFrame(r));

  async function saveImage(hideHome) {
    state.hideHome = hideHome;
    pushGlobe();
    await pause(450);      // let the globe apply the change
    await nextFrame();

    // Draw one frame and copy it straight away: a WebGL picture only stays
    // readable until the browser moves on to its next task.
    let src;
    if (flat.on) {
      drawFlat(performance.now());
      src = flat.canvas;
    } else {
      const composer = typeof globe.postProcessingComposer === "function" && globe.postProcessingComposer();
      if (composer) composer.render(); else globe.renderer().render(globe.scene(), globe.camera());
      src = globe.renderer().domElement;
    }
    const out = document.createElement("canvas");
    out.width = src.width;
    out.height = src.height;
    const ctx = out.getContext("2d");
    const css = getComputedStyle(document.documentElement);
    ctx.fillStyle = css.getPropertyValue("--bg").trim() || "#05070c";
    ctx.fillRect(0, 0, out.width, out.height);
    ctx.drawImage(src, 0, 0);

    state.hideHome = false;
    pushGlobe();

    const k = out.width / window.innerWidth;   // screen pixels -> image pixels
    const font = css.getPropertyValue("--font").trim() || "system-ui, sans-serif";
    ctx.textBaseline = "alphabetic";
    ctx.fillStyle = css.getPropertyValue("--text").trim() || "#fff";
    ctx.font = `600 ${22 * k}px ${font}`;
    ctx.fillText("BeaconMap", 24 * k, out.height - 46 * k);
    ctx.fillStyle = css.getPropertyValue("--muted").trim() || "#999";
    ctx.font = `${14 * k}px ${font}`;
    const n = (id, word) => `${$(id).textContent} ${word}`;
    ctx.fillText([n("s-conn", "connections"), n("s-co", "companies"), n("s-cc", "countries")].join("  ·  "), 24 * k, out.height - 22 * k);

    const blob = await new Promise((r) => out.toBlob(r, "image/png"));
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "beaconmap.png";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }

  // ---------- live stream ----------
  let retry = 500;
  function connect() {
    const ws = new WebSocket(`ws://${location.host}/ws`);
    ws.onopen = () => { retry = 500; $("live").textContent = "live"; $("live").classList.remove("off"); };
    ws.onmessage = (e) => {
      let snap;
      try { snap = JSON.parse(e.data); } catch { return; }
      state.groups = snap.groups;
      state.linger = snap.linger || 8;
      state.addon = !!snap.addon;
      $("addon-pill").classList.toggle("hidden", !state.addon);
      stampFades();
      detectSpikes(snap.groups);
      renderAll();          // runs before the line below, so the first load draws no ripples
      state.snapshot = snap;
      renderStats(snap);
    };
    ws.onclose = () => {
      $("live").textContent = "offline";
      $("live").classList.add("off");
      setTimeout(connect, retry);
      retry = Math.min(retry * 2, 8000);
    };
  }

  fetch("api/config")
    .then((r) => r.json())
    .then((cfg) => {
      state.dbAgeDays = cfg.db_age_days;
      state.homeGuess = cfg.home_guess || null;
      state.addonPath = cfg.addon_path || "";
      renderBanners();
      if (cfg.home) setHome(cfg.home, false);
      else { setHome(guessHome(), false); openSettings(true); }
    })
    .catch(() => setHome(guessHome(), false))
    .finally(() => { connect(); loadHistory(); });
})();
