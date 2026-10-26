import ipaddress
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.core.errors import UnsafeURLError
from app.models.enums import CheckOutcome
from app.monitoring.http_client import SafeHTTPClient
from app.security.ssrf import DestinationPolicy, is_public_ip, validate_url


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/x",
        "file:///etc/passwd",
        "gopher://example.com",
        "http://user:pass@example.com/",
        "http://@example.com/",
        "http://localhost/",
        "http://LOCALHOST./",
        "http://api.localhost/",
        "http://printer.local/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://127.0.0.1/",
        "http://10.1.2.3/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://100.100.100.200/",
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[fe80::1]/",
        "http://[fd00:ec2::254]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[64:ff9b::7f00:1]/",
        "http://224.0.0.1/",
        "http://2130706433/",
        "http://0x7f.0.0.1/",
        "http://intranet/",
        "http://example.com:22/",
        "http://exa mple.com/",
        "http://example.com\\@evil.com/",
        "http://example.com:99999/",
        "https://" + "a" * 2050 + ".com/",
    ],
)
def test_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(UnsafeURLError):
        validate_url(url)


@pytest.mark.parametrize(
    "url",
    ["https://api.example.com/v1/users?id=1", "http://93.184.216.34:8080/x", "http://[2606:4700::1111]/"],
)
def test_accepts_public_urls(url: str) -> None:
    validate_url(url)


@pytest.mark.parametrize(
    ("ip", "public"),
    [
        ("8.8.8.8", True),
        ("2606:4700::1111", True),
        ("127.0.0.1", False),
        ("10.0.0.1", False),
        ("100.64.1.1", False),
        ("::ffff:10.0.0.1", False),
        ("2002:7f00:1::", False),
        ("ff02::1", False),
    ],
)
def test_is_public_ip(ip: str, public: bool) -> None:
    assert is_public_ip(ipaddress.ip_address(ip)) is public


def test_resolution_rejects_any_private_record() -> None:
    policy = DestinationPolicy(resolver=lambda host, port: ["93.184.216.34", "10.0.0.1"])
    with pytest.raises(UnsafeURLError):
        policy.resolve("mixed.example.com", 443)


def test_unresolvable_host_fails_closed() -> None:
    def resolver(host: str, port: int) -> list[str]:
        raise OSError("nxdomain")

    with pytest.raises(UnsafeURLError):
        DestinationPolicy(resolver=resolver).check_url("https://nope.example.com/")


def test_allowed_hosts_exemption_is_exact() -> None:
    policy = DestinationPolicy(resolver=lambda h, p: ["172.18.0.5"], allowed_hosts=["mock-api"])
    assert policy.resolve("mock-api", 8000) == ["172.18.0.5"]
    with pytest.raises(UnsafeURLError):
        policy.resolve("mock-api.evil.com", 8000)


# --- connection-level tests against a real local socket ------------------------------------


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/")
            self.end_headers()
        elif self.path == "/big":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"[" + b"1," * 5000 + b"1]")
        elif self.path == "/slow":
            self.send_response(200)
            self.end_headers()
            for _ in range(20):
                self.wfile.write(b" ")
                self.wfile.flush()
                time.sleep(0.1)
        else:
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture(scope="module")
def local_server() -> Iterator[int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()


def _client(policy: DestinationPolicy, max_bytes: int = 64_000) -> SafeHTTPClient:
    return SafeHTTPClient(policy, max_response_bytes=max_bytes, max_retries=0)


def test_connection_to_loopback_is_blocked_at_connect_time(local_server: int) -> None:
    # The hostname looks public and passes static checks, but DNS answers 127.0.0.1.
    policy = DestinationPolicy(resolver=lambda h, p: ["127.0.0.1"])
    result = _client(policy).get(f"http://looks-public.example.com:{local_server}/", {}, 2)
    assert result.outcome == CheckOutcome.BLOCKED


def test_dns_rebinding_is_caught_at_connect_time(local_server: int) -> None:
    answers = iter([["93.184.216.34"], ["127.0.0.1"]])  # public at registration, private at fetch
    policy = DestinationPolicy(resolver=lambda h, p: next(answers))
    url = f"http://rebind.example.com:{local_server}/"
    policy.check_url(url)  # registration-time validation passes
    assert _client(policy).get(url, {}, 2).outcome == CheckOutcome.BLOCKED


def test_safe_transport_connects_to_validated_address(local_server: int) -> None:
    # Demo exemption: proves the custom network backend really performs the request.
    policy = DestinationPolicy(resolver=lambda h, p: ["127.0.0.1"], allowed_hosts=["mock-api.test"])
    result = _client(policy).get(f"http://mock-api.test:{local_server}/", {}, 2)
    assert result.outcome is None and result.status_code == 200 and result.body == b'{"ok": true}'


def test_falls_back_to_next_validated_address(local_server: int) -> None:
    # First address refuses connections (nothing listens on ::1 here); the second works.
    policy = DestinationPolicy(resolver=lambda h, p: ["::1", "127.0.0.1"], allowed_hosts=["mock-api.test"])
    result = _client(policy).get(f"http://mock-api.test:{local_server}/", {}, 2)
    assert result.status_code == 200


def test_redirects_are_not_followed(local_server: int) -> None:
    policy = DestinationPolicy(resolver=lambda h, p: ["127.0.0.1"], allowed_hosts=["mock-api.test"])
    result = _client(policy).get(f"http://mock-api.test:{local_server}/redirect", {}, 2)
    assert result.status_code == 302


def test_response_size_limit(local_server: int) -> None:
    policy = DestinationPolicy(resolver=lambda h, p: ["127.0.0.1"], allowed_hosts=["mock-api.test"])
    result = _client(policy, max_bytes=2048).get(f"http://mock-api.test:{local_server}/big", {}, 2)
    assert result.outcome == CheckOutcome.RESPONSE_TOO_LARGE


def test_total_deadline_stops_slow_drip(local_server: int) -> None:
    policy = DestinationPolicy(resolver=lambda h, p: ["127.0.0.1"], allowed_hosts=["mock-api.test"])
    started = time.monotonic()
    result = _client(policy).get(f"http://mock-api.test:{local_server}/slow", {}, 1)
    assert result.outcome == CheckOutcome.TIMEOUT
    assert time.monotonic() - started < 1.9


def test_static_check_runs_before_any_connection() -> None:
    result = _client(DestinationPolicy()).get("http://169.254.169.254/latest/meta-data/", {}, 2)
    assert result.outcome == CheckOutcome.BLOCKED and result.attempts == 0
