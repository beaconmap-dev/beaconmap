# Third-party files and data

Bundled in `src/beaconmap/static/vendor/`:

| File | Project | License |
|---|---|---|
| `globe.gl.min.js` (2.46.2) | [globe.gl](https://github.com/vasturiano/globe.gl) (includes three.js, h3-js) | MIT / Apache-2.0 |
| `topojson-client.min.js` (3.1.0) | [topojson-client](https://github.com/topojson/topojson-client) | ISC |
| `countries-110m.json` (2.0.2) | [world-atlas](https://github.com/topojson/world-atlas), from Natural Earth | ISC / public domain |

Also bundled: `src/beaconmap/static/cities.js`, a list of city names and coordinates
derived from the DB-IP Lite city database ([DB-IP](https://db-ip.com), CC BY 4.0) by
`tools/build_cities.py`.

Downloaded by the user, never bundled:

- **DB-IP Lite** city and ASN databases: IP Geolocation by [DB-IP](https://db-ip.com), CC BY 4.0.
- **Optional lists**, each fetched from and governed by its publisher:
  [abuse.ch Feodo Tracker](https://feodotracker.abuse.ch/blocklist/) (CC0),
  [Spamhaus DROP](https://www.spamhaus.org/drop/terms/),
  [bgp.tools anycast prefixes](https://github.com/bgptools/anycast-prefixes) (no licence file; used with bgp.tools' permission),
  and the published address ranges of Amazon AWS, Google Cloud, Cloudflare,
  Fastly and GitHub. BeaconMap is not affiliated with or endorsed by any of them.
