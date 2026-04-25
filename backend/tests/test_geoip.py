from types import SimpleNamespace

from app.services import geoip


def test_resolve_host_ip_ignores_private_hosts() -> None:
    assert geoip.resolve_host_ip("127.0.0.1") is None
    assert geoip.resolve_host_ip("10.0.0.1") is None


def test_country_for_url_uses_geoip_reader(monkeypatch) -> None:
    class Reader:
        def country(self, ip_address: str):
            assert ip_address == "8.8.8.8"
            return SimpleNamespace(country=SimpleNamespace(iso_code="us"))

    monkeypatch.setattr(geoip, "resolve_host_ip", lambda hostname: "8.8.8.8")
    monkeypatch.setattr(geoip, "_geoip_reader", lambda: Reader())

    assert geoip.country_for_url("https://example.com/watch/1") == "US"


def test_country_for_url_returns_none_without_reader(monkeypatch) -> None:
    monkeypatch.setattr(geoip, "resolve_host_ip", lambda hostname: "8.8.8.8")
    monkeypatch.setattr(geoip, "_geoip_reader", lambda: None)

    assert geoip.country_for_url("https://example.com/watch/1") is None
