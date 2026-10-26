"""SafeHTTPClient: the only component that talks to monitored endpoints.

Safeguards:
  * Connection-level SSRF protection: a custom httpcore network backend resolves the hostname,
    validates every address with DestinationPolicy and connects to exactly that address.
    TLS still verifies the certificate against the original hostname (SNI = URL host).
  * No redirects are followed (a 3xx is reported as the observed status).
  * No proxies or environment configuration (trust_env=False), TLS verification always on.
  * Total-time deadline, streamed body with a hard byte limit, bounded connection pool.
  * Bounded retries for connect errors and timeouts only (GET is idempotent).
"""

import logging
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import httpcore
import httpx

from app.core.errors import UnsafeURLError
from app.models.enums import CheckOutcome
from app.security.ssrf import DestinationPolicy, validate_url

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    outcome: CheckOutcome | None  # None = HTTP exchange completed; caller classifies the body
    status_code: int | None = None
    latency_ms: float | None = None
    size_bytes: int | None = None
    content_type: str | None = None
    body: bytes | None = None
    error: str | None = None
    attempts: int = 1


class SafeNetworkBackend(httpcore.NetworkBackend):
    def __init__(self, policy: DestinationPolicy):
        self._policy = policy
        self._inner = httpcore.SyncBackend()

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        addresses = self._policy.resolve(host, port)  # every address validated; raises UnsafeURLError
        last_error: Exception | None = None
        for address in addresses:  # e.g. IPv6 then IPv4 for dual-stack hosts
            try:
                return self._inner.connect_tcp(address, port, timeout, local_address, socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

    def connect_unix_socket(self, *args: object, **kwargs: object) -> httpcore.NetworkStream:
        raise UnsafeURLError("Unix sockets are not allowed")

    def sleep(self, seconds: float) -> None:
        self._inner.sleep(seconds)


class SafeTransport(httpx.HTTPTransport):
    def __init__(self, policy: DestinationPolicy, max_connections: int = 20):
        super().__init__(verify=True, trust_env=False, retries=0)
        if not isinstance(getattr(self, "_pool", None), httpcore.ConnectionPool):
            # httpx internals changed: refuse to run rather than silently lose SSRF protection.
            raise RuntimeError("Unsupported httpx version: cannot install the safe network backend")
        self._pool.close()
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=True),
            max_connections=max_connections,
            max_keepalive_connections=max_connections // 2,
            keepalive_expiry=5.0,
            network_backend=SafeNetworkBackend(policy),
        )


class SafeHTTPClient:
    def __init__(
        self,
        policy: DestinationPolicy,
        *,
        max_response_bytes: int,
        max_retries: int = 1,
        user_agent: str = "APIDriftRadar/1.0",
        max_connections: int = 20,
        transport: httpx.BaseTransport | None = None,  # tests inject httpx.MockTransport
        retry_backoff_seconds: float = 0.5,
    ):
        self.policy = policy
        self.max_response_bytes = max_response_bytes
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self._client = httpx.Client(
            transport=transport or SafeTransport(policy, max_connections),
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": user_agent, "Accept": "application/json, */*;q=0.5"},
        )

    def close(self) -> None:
        self._client.close()

    def get(self, url: str, headers: Mapping[str, str], timeout: float) -> FetchResult:
        try:
            validate_url(url, self.policy.allowed_hosts)
        except UnsafeURLError as exc:
            return FetchResult(CheckOutcome.BLOCKED, error=exc.message, attempts=0)

        result = FetchResult(CheckOutcome.NETWORK_ERROR, error="Request not attempted")
        for attempt in range(1, self.max_retries + 2):
            result = self._attempt(url, headers, timeout)
            result.attempts = attempt
            if result.outcome not in (CheckOutcome.TIMEOUT, CheckOutcome.NETWORK_ERROR):
                break
            if attempt <= self.max_retries:
                time.sleep(self.retry_backoff_seconds * attempt)
        return result

    def _attempt(self, url: str, headers: Mapping[str, str], timeout: float) -> FetchResult:
        start = time.perf_counter()
        deadline = start + timeout

        def elapsed_ms() -> float:
            return round((time.perf_counter() - start) * 1000, 2)

        try:
            with self._client.stream("GET", url, headers=dict(headers), timeout=timeout) as resp:
                content_type = resp.headers.get("content-type")
                declared = resp.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > self.max_response_bytes:
                    return self._too_large(resp.status_code, elapsed_ms(), content_type)
                body = bytearray()
                for chunk in resp.iter_bytes():  # decoded bytes: limit also caps decompression
                    body.extend(chunk)
                    if len(body) > self.max_response_bytes:
                        return self._too_large(resp.status_code, elapsed_ms(), content_type)
                    if time.perf_counter() > deadline:
                        return FetchResult(
                            CheckOutcome.TIMEOUT,
                            resp.status_code,
                            elapsed_ms(),
                            error=f"Response not completed within {timeout:g}s",
                        )
                return FetchResult(None, resp.status_code, elapsed_ms(), len(body), content_type, bytes(body))
        except UnsafeURLError as exc:
            return FetchResult(CheckOutcome.BLOCKED, error=exc.message)
        except httpx.TimeoutException:
            return FetchResult(
                CheckOutcome.TIMEOUT, latency_ms=elapsed_ms(), error=f"Request timed out after {timeout:g}s"
            )
        except httpx.DecodingError:
            return FetchResult(
                CheckOutcome.NETWORK_ERROR,
                latency_ms=elapsed_ms(),
                error="Response body could not be decoded",
            )
        except httpx.HTTPError as exc:
            # Only the exception class is reported: messages can contain internal details.
            reason = type(exc).__name__
            if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                reason = "TLS certificate verification failed"
            return FetchResult(
                CheckOutcome.NETWORK_ERROR, latency_ms=elapsed_ms(), error=f"Connection failed ({reason})"
            )

    def _too_large(self, status: int, latency: float, content_type: str | None) -> FetchResult:
        return FetchResult(
            CheckOutcome.RESPONSE_TOO_LARGE,
            status,
            latency,
            None,
            content_type,
            error=f"Response exceeded the {self.max_response_bytes} byte limit",
        )
