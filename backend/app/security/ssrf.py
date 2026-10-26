"""Outbound destination policy: which URLs and IP addresses the monitor may connect to.

Two layers use this module:
  * `validate_url` - static checks at registration and before every request.
  * `DestinationPolicy.resolve` - resolves the hostname and validates *every* address;
    SafeHTTPClient then connects to exactly the validated address (no second DNS lookup),
    which defeats DNS-rebinding / time-of-check-to-time-of-use tricks.
"""

import ipaddress
import re
import socket
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit

from app.core.errors import UnsafeURLError

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

MAX_URL_LENGTH = 2048
ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_HOSTNAMES = {"localhost", "metadata", "metadata.google.internal", "instance-data"}
BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".localdomain", ".home.arpa", ".lan")

_NUMERIC_HOST = re.compile(r"^((0x[0-9a-f]*|\d+)\.?)+$")

# Ranges blocked in addition to everything Python's ipaddress does not consider global.
_EXTRA_BLOCKED = [
    ipaddress.ip_network(net)
    for net in (
        "0.0.0.0/8",
        "100.64.0.0/10",  # carrier-grade NAT (also Alibaba metadata 100.100.100.200)
        "192.0.0.0/24",
        "198.18.0.0/15",
        "64:ff9b::/96",  # NAT64 - embeds IPv4, Python reports these as global
        "64:ff9b:1::/48",
        "2001::/32",  # Teredo
        "2002::/16",  # 6to4 - embeds IPv4
        "fec0::/10",  # deprecated site-local
    )
]

Resolver = Callable[[str, int], Iterable[str]]


def is_public_ip(ip: IPAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False
    return not any(ip.version == net.version and ip in net for net in _EXTRA_BLOCKED)


def system_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    return [str(info[4][0]) for info in infos]


def _parse_ip(host: str) -> IPAddress | None:
    try:
        return ipaddress.ip_address(host.strip("[]").split("%")[0])
    except ValueError:
        return None


def validate_url(url: str, allowed_hosts: Iterable[str] = ()) -> str:
    """Static URL checks. Returns the normalised hostname. Raises UnsafeURLError."""
    if len(url) > MAX_URL_LENGTH:
        raise UnsafeURLError("URL is too long")
    if any(ch.isspace() or ord(ch) < 32 for ch in url) or "\\" in url:
        raise UnsafeURLError("URL contains whitespace, control or backslash characters")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise UnsafeURLError("URL is malformed") from exc
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURLError("Only http and https URLs are allowed")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise UnsafeURLError("URLs with embedded credentials are not allowed")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeURLError("URL has no host")
    if host in set(allowed_hosts):
        return host
    if port is not None and port not in (80, 443) and port < 1024:
        raise UnsafeURLError("Only ports 80, 443 and 1024-65535 are allowed")
    ip = _parse_ip(host)
    if ip is not None:
        if not is_public_ip(ip):
            raise UnsafeURLError("URL points to a non-public IP address")
        return host
    if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_SUFFIXES) or "." not in host:
        raise UnsafeURLError("URL points to a local or internal hostname")
    try:
        host.encode("idna")
    except UnicodeError as exc:
        raise UnsafeURLError("URL host is not a valid domain name") from exc
    if _NUMERIC_HOST.match(host):  # 2130706433, 0177.0.0.1, 0x7f.1 ... inet_aton shorthand forms
        raise UnsafeURLError("Numeric shorthand IP addresses are not allowed")
    return host


class DestinationPolicy:
    def __init__(self, resolver: Resolver = system_resolver, allowed_hosts: Iterable[str] = ()):
        self._resolver = resolver
        self.allowed_hosts = frozenset(h.lower().rstrip(".") for h in allowed_hosts)

    def resolve(self, host: str, port: int) -> list[str]:
        """Resolve `host` and return the addresses to connect to, in resolver order.

        Fails closed: if ANY resolved address is non-public, the whole destination is
        rejected, so an attacker cannot mix a public and a private record.
        """
        normalised = host.strip("[]").rstrip(".").lower()
        literal = _parse_ip(normalised)
        if literal is not None:
            addresses: list[IPAddress] = [literal]
        else:
            try:
                addresses = [ipaddress.ip_address(a.split("%")[0]) for a in self._resolver(normalised, port)]
            except (OSError, UnicodeError, ValueError) as exc:
                raise UnsafeURLError(f"Could not resolve host '{normalised}'") from exc
        if not addresses:
            raise UnsafeURLError(f"Host '{normalised}' has no addresses")
        if normalised not in self.allowed_hosts:
            bad = [str(a) for a in addresses if not is_public_ip(a)]
            if bad:
                raise UnsafeURLError(f"Host '{normalised}' resolves to a non-public address")
        return list(dict.fromkeys(str(a) for a in addresses))

    def check_url(self, url: str) -> None:
        """Static validation plus resolution; used when an endpoint is created or edited."""
        host = validate_url(url, self.allowed_hosts)
        parts = urlsplit(url)
        self.resolve(host, parts.port or (443 if parts.scheme.lower() == "https" else 80))
