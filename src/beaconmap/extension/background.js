// BeaconMap site names
//
// Everything this add-on does is in this file and pair.js.
//
// What it reads:  for each thing the browser loads, the website's name
//                 (for example "claude.ai") and the server address it came from.
// What it sends:  those two values, to BeaconMap running on THIS computer
//                 (http://127.0.0.1). Nowhere else, ever.
// What it never reads: page contents, full addresses (paths), cookies, form
//                 data, history, or anything from private/incognito windows
//                 unless you switch that on yourself.

const pending = new Map(); // "ip|host" -> { ip, host }
const MAX_PENDING = 400;
let timer = null;

chrome.webRequest.onResponseStarted.addListener(
  (details) => {
    if (!details.ip || details.fromCache) return; // nothing was fetched from a server
    let host;
    try { host = new URL(details.url).hostname; } catch { return; }
    if (!host || host === "localhost" || host === "127.0.0.1" || host === "[::1]") return;
    if (pending.size < MAX_PENDING) pending.set(details.ip + "|" + host, { ip: details.ip, host });
    if (!timer) timer = setTimeout(send, 1000);
  },
  { urls: ["http://*/*", "https://*/*", "ws://*/*", "wss://*/*"] }
);

async function send() {
  timer = null;
  const sites = [...pending.values()];
  pending.clear();
  const { pairing } = await chrome.storage.local.get("pairing");
  if (!pairing) return; // not linked to BeaconMap yet: forget what was collected
  try {
    await fetch(`http://127.0.0.1:${pairing.port}/api/sites`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: pairing.key, sites }),
    });
  } catch {
    // BeaconMap isn't running: nothing is kept for later
  }
}

// Linking: pair.js runs only on the BeaconMap page and hands over the key
// that BeaconMap gave it.
chrome.runtime.onMessage.addListener((msg, sender) => {
  const fromBeaconMap = /^http:\/\/(127\.0\.0\.1|localhost):\d+\//.test(sender.url || "");
  if (!fromBeaconMap || !msg || msg.type !== "beaconmap-pair") return;
  const port = Number(msg.port);
  if (!Number.isInteger(port) || port < 1 || port > 65535 || typeof msg.key !== "string") return;
  chrome.storage.local.set({ pairing: { port, key: msg.key } });
  send();
});

// A quiet check-in once a minute, so BeaconMap can show "add-on connected"
// even when you aren't browsing.
chrome.alarms.create("check-in", { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener(() => send());
