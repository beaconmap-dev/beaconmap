"""Company naming, damaged databases, and the settings/token files."""

import os
import sys

import pytest

from beaconmap import dbupdate, geo, paths


class FakeReader:
    def __init__(self, rows):
        self.rows = rows

    def get(self, ip):
        return self.rows.get(ip)

    def close(self):
        pass


def lookup_with(city_rows, asn_rows):
    g = geo.GeoLookup.__new__(geo.GeoLookup)  # skip opening real files
    g._city, g._asn = FakeReader(city_rows), FakeReader(asn_rows)
    return g._lookup


CITY = {
    "location": {"latitude": 39.1, "longitude": -94.6},
    "city": {"names": {"en": "Kansas City (Downtown)"}},
    "country": {"iso_code": "US", "names": {"en": "United States"}},
}


def test_cloud_network_gets_a_friendly_name_and_the_cloud_tag():
    info = lookup_with({"1.1.1.1": CITY}, {"1.1.1.1": {
        "autonomous_system_number": 396982, "autonomous_system_organization": "GOOGLE-CLOUD-PLATFORM"}})("1.1.1.1")
    assert (info.org, info.cloud, info.city, info.country_code) == ("Google Cloud", True, "Kansas City", "US")


def test_known_company_is_named_but_not_tagged_cloud():
    info = lookup_with({}, {"8.8.8.8": {
        "autonomous_system_number": 15169, "autonomous_system_organization": "GOOGLE"}})("8.8.8.8")
    assert (info.org, info.cloud) == ("Google", False)
    assert info.lat is None  # no location row: the collector counts it as unlocated


def test_other_companies_have_legal_suffixes_trimmed():
    info = lookup_with({}, {"9.9.9.9": {
        "autonomous_system_number": 64500, "autonomous_system_organization": "Example Networks, Inc."}})("9.9.9.9")
    assert info.org == "Example Networks"
    assert lookup_with({}, {})("10.0.0.1").org == "Unknown"


def test_damaged_database_gives_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(dbupdate, "data_dir", lambda: tmp_path)
    (tmp_path / "dbip-city-lite.mmdb").write_bytes(b"this is not a database")
    (tmp_path / "dbip-asn-lite.mmdb").write_bytes(b"neither is this")
    with pytest.raises(geo.DatabaseError, match="dbip-city-lite.mmdb"):
        geo.GeoLookup()


def test_repair_prompt_respects_a_no(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    monkeypatch.setattr(dbupdate, "update_databases", lambda: pytest.fail("downloaded without consent"))
    assert dbupdate.ask_and_repair("broken") is False
    assert "nothing downloaded" in capsys.readouterr().out


def test_config_round_trip_and_damaged_file(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    assert paths.load_config() == {}
    paths.save_config({"home": {"lat": 1.5, "lng": 2.5, "label": "Bogotá"}})
    assert paths.load_config()["home"]["label"] == "Bogotá"
    paths.config_path().write_text("{not json", encoding="utf-8")
    assert paths.load_config() == {}  # a broken settings file must not stop the app


def test_access_token_is_stable_and_private(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    first = paths.access_token()
    assert len(first) >= 20 and paths.access_token() == first
    if sys.platform != "win32":
        assert os.stat(tmp_path / "token").st_mode & 0o077 == 0
    (tmp_path / "token").write_text("short", encoding="ascii")
    assert paths.access_token() != "short"  # a damaged token file is replaced
