// Runs only on pages at http://127.0.0.1 or http://localhost, and does nothing
// unless the page says it is BeaconMap. It asks BeaconMap for the add-on's
// key and passes it to background.js, which is how the two get linked.
if (document.querySelector('meta[name="beaconmap"]')) {
  fetch("/api/addon-key")
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => {
      if (d && d.app === "beaconmap") chrome.runtime.sendMessage({ type: "beaconmap-pair", port: d.port, key: d.key });
    })
    .catch(() => {});
}
