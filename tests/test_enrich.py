"""Optional lists: known-bad servers, cloud services, worldwide addresses."""

import ipaddress
import json
from collections import namedtuple

from beaconmap import geo
from beaconmap.collector import Collector
from beaconmap.enrich import Enrichment, PrefixTable

Addr = namedtuple("Addr", "ip port")


def write_lists(folder):
    (folder / "feodo.json").write_text(json.dumps([{"ip_address": "45.83.1.7", "malware": "Emotet"}]))
    (folder / "drop_v4.json").write_text(
        '{"cidr":"198.51.100.0/24","sblid":"SBL1"}\n{"type":"metadata","records":1}\n')
    (folder / "aws.json").write_text(json.dumps({
        "prefixes": [
            {"ip_prefix": "52.0.0.0/16", "region": "eu-west-1", "service": "AMAZON"},
            {"ip_prefix": "52.0.0.0/16", "region": "eu-west-1", "service": "S3"},
            {"ip_prefix": "13.0.0.0/16", "region": "GLOBAL", "service": "CLOUDFRONT"},
            {"ip_prefix": "54.0.0.0/16", "region": "xx-nowhere-9", "service": "EC2"},
        ],
        "ipv6_prefixes": [{"ipv6_prefix": "2600:1f00::/32", "region": "us-east-1", "service": "EC2"}],
    }))
    (folder / "gcloud.json").write_text(json.dumps({"prefixes": [
        {"ipv4Prefix": "34.0.0.0/16", "scope": "global"},
        {"ipv6Prefix": "2600:1901::/32", "scope": "global"},
    ]}))
    (folder / "cloudflare_v4.txt").write_text("104.16.0.0/13\n")
    (folder / "anycast_v4.txt").write_text("192.0.2.0/24\n")
    (folder / "fastly.json").write_text("this file is damaged")


def test_longest_prefix_wins_and_bad_input_is_ignored():
    t = PrefixTable()
    t.add("10.0.0.0/8", "big")
    t.add("10.1.0.0/16", "small")
    t.add("not a network", "x")
    assert t.get(ipaddress.ip_address("10.1.2.3")) == "small"
    assert t.get(ipaddress.ip_address("10.9.9.9")) == "big"
    assert t.get(ipaddress.ip_address("11.0.0.1")) is None
    assert t.get(ipaddress.ip_address("2001:db8::1")) is None


def test_lists(tmp_path):
    write_lists(tmp_path)
    e = Enrichment(tmp_path)
    assert "fastly.json" not in e.loaded and e.has_threat_list  # a damaged list is skipped, not fatal

    assert "Emotet" in e.lookup("45.83.1.7").threat
    assert "SBL1" in e.lookup("198.51.100.200").threat
    assert e.lookup("8.8.8.8").threat == ""

    s3 = e.lookup("52.0.5.5")  # the real service outranks the catch-all AMAZON entry
    assert (s3.service.org, s3.service.name, s3.place.city, s3.worldwide) == ("Amazon AWS", "S3 storage", "Dublin", False)
    cdn = e.lookup("13.0.0.9")
    assert cdn.service.name == "CloudFront" and cdn.worldwide and cdn.place is None
    assert e.lookup("54.0.0.1").place is None            # unknown region: keep the database's location
    assert e.lookup("2600:1f00::1").place.city == "Ashburn"
    assert e.lookup("2600:1901:0:f6e5::").worldwide     # the "Kansas City" address
    assert e.lookup("104.16.1.1").service.org == "Cloudflare"
    assert e.lookup("192.0.2.9").worldwide and e.lookup("192.0.2.9").service is None
    assert e.lookup("nonsense").threat == ""


def test_no_lists_installed(tmp_path):
    e = Enrichment(tmp_path)
    assert not e.has_threat_list and e.lookup("45.83.1.7").threat == ""


class Reader:
    def __init__(self, rows):
        self.rows = rows

    def get(self, ip):
        return self.rows.get(ip)


def test_lists_change_what_the_map_shows(tmp_path):
    write_lists(tmp_path)
    g = geo.GeoLookup.__new__(geo.GeoLookup)
    kansas = {"location": {"latitude": 39.1, "longitude": -94.6}, "city": {"names": {"en": "Kansas City"}},
              "country": {"iso_code": "US", "names": {"en": "United States"}}}
    g._city = Reader({"52.0.5.5": kansas, "34.0.0.1": kansas, "45.83.1.7": kansas})
    g._asn = Reader({})
    g.extra = Enrichment(tmp_path)

    s3 = g._lookup("52.0.5.5")  # the provider's region replaces the database's guess
    assert (s3.org, s3.service, s3.city, s3.country_code, s3.cloud) == ("Amazon AWS", "S3 storage", "Dublin", "IE", True)
    world = g._lookup("34.0.0.1")
    assert world.worldwide and world.org == "Google Cloud" and world.city == "Kansas City"

    g.lookup = g._lookup
    c = Collector(g)
    c._connections = lambda: [(Addr("45.83.1.7", 443), 1, 1), (Addr("34.0.0.1", 443), 1, 1)]
    c.names.get = lambda pid: "odd.exe"
    snap = c.poll()
    bad = [x for x in snap["groups"] if x["threat"]]
    assert len(bad) == 1 and "Feodo" in bad[0]["threat"]
    assert snap["stats"]["threats"] == 1


def test_threat_count_is_unknown_without_a_list():
    class NoLists:
        def lookup(self, ip):
            return geo.GeoInfo(1.0, 2.0, "X", "Y", "ZZ", None, "Org", False)

    c = Collector(NoLists())
    c._connections = lambda: [(Addr("8.8.8.8", 443), 1, 1)]
    c.names.get = lambda pid: "a.exe"
    assert c.poll()["stats"]["threats"] is None  # "we can't tell", not "zero"
