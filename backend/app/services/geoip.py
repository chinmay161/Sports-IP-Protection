import ipaddress
import socket
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from app.core.config import get_settings


PRIVATE_HOSTS = {"localhost"}


def _country_code(value: object) -> str | None:
    code = getattr(getattr(value, "country", None), "iso_code", None)
    if isinstance(code, str) and len(code) == 2:
        return code.upper()
    return None


@lru_cache(maxsize=1)
def _geoip_reader():
    database_path = get_settings().geoip_database_path
    if database_path is None:
        return None

    try:
        import geoip2.database
    except ImportError:
        return None

    path = Path(database_path)
    if not path.exists():
        return None
    return geoip2.database.Reader(str(path))


def resolve_host_ip(hostname: str) -> str | None:
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            ip = ipaddress.ip_address(socket.gethostbyname(hostname))
        except OSError:
            return None

    if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_multicast:
        return None
    return str(ip)


def country_for_ip(ip_address: str) -> str | None:
    reader = _geoip_reader()
    if reader is None:
        return None

    try:
        return _country_code(reader.country(ip_address))
    except Exception:
        return None


def country_for_url(url: str) -> str | None:
    hostname = urlparse(url).hostname
    if not hostname or hostname.lower() in PRIVATE_HOSTS:
        return None

    ip_address = resolve_host_ip(hostname)
    if ip_address is None:
        return None
    return country_for_ip(ip_address)
