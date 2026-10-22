from __future__ import annotations

import ipaddress
import os
import time
from collections import deque
from threading import RLock

from fastapi import HTTPException, Request

from app.services.tool_access import tool_access_enabled
from app.services.env_settings import TRUTHY_VALUES, env_flag, env_int


def trusted_proxy_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """`COPYLOT_TRUSTED_PROXY_IPS` as networks: single addresses or CIDR ranges.

    A reverse proxy in front of the container is seen under the Docker bridge
    gateway address, which is not fixed, so the compose files name the bridge
    range (172.16.0.0/12) rather than one address. Unparseable entries are
    ignored rather than trusted.
    """
    networks = []
    for value in str(os.getenv("COPYLOT_TRUSTED_PROXY_IPS", "")).split(","):
        text = value.strip()
        if not text:
            continue
        try:
            networks.append(ipaddress.ip_network(text, strict=False))
        except ValueError:
            continue
    return networks


def peer_is_trusted_proxy(peer: str) -> bool:
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return False
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return any(address in network for network in trusted_proxy_networks())


def client_address(request: Request) -> str:
    """The client's address: the peer, or the forwarded one behind a trusted proxy.

    The login limiter keys on this. Without a trusted proxy every request
    behind a reverse proxy carries the proxy's own address, so twelve wrong
    passwords from anyone lock everyone out; hence the compose default.
    """
    peer = request.client.host if request.client and request.client.host else "unknown"
    if not peer_is_trusted_proxy(peer):
        return peer

    # Work back from the trusted peer; a client can prepend arbitrary entries.
    forwarded = ",".join(request.headers.getlist("x-forwarded-for"))
    for value in reversed(forwarded.split(",")):
        try:
            address = str(ipaddress.ip_address(value.strip()))
        except ValueError:
            return peer
        if not peer_is_trusted_proxy(address):
            return address
    return peer


def local_path_access_allowed(request: Request) -> bool:
    try:
        address = ipaddress.ip_address(client_address(request).strip())
    except ValueError:
        return False
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if not address.is_loopback:
        return False
    return not tool_access_enabled() or env_flag("COPYLOT_ALLOW_LOCAL_PATH_APIS")


def local_runtime_diagnostics_allowed(request: Request) -> bool:
    """Full diagnostics are for direct local desktop access, never a deployment.

    A loopback proxy is not a local desktop user. Refuse configured proxies and
    forwarded requests, including missing or malformed forwarding information.
    """
    if any(env_flag(name) for name in (
        "COPYLOT_VIEWER_MODE", "COPYLOT_VIEWER_PORTAL_ENABLED", "COPYLOT_TOOL_ACCESS_ENABLED",
    )):
        return False
    peer = request.client.host if request.client else ""
    if peer_is_trusted_proxy(peer) or any(
        name in request.headers for name in ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto")
    ):
        return False
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return False
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_loopback


def _drop_expired(attempts: deque[float], cutoff: float) -> bool:
    """Forget attempts older than the window; report whether any are left."""
    while attempts and attempts[0] < cutoff:
        attempts.popleft()
    return bool(attempts)


def rate_limit_key(address: str) -> str:
    """The client identity a login limiter counts attempts for.

    An IPv4 client is its address. An IPv6 client is its /64: a home or VPS
    customer is routinely given a whole /64, so counting per address lets one
    customer rotate through fresh addresses and never trip the limit (review
    M11, 2026-10-21). Anything that is not an IP address is used unchanged.
    """
    try:
        parsed = ipaddress.ip_address(str(address).strip())
    except ValueError:
        return str(address)
    if parsed.version == 6:
        mapped = parsed.ipv4_mapped
        if mapped is not None:
            return str(mapped)
        return str(ipaddress.ip_network(f"{parsed}/64", strict=False))
    return str(parsed)


class LoginRateLimit:
    """Failed-login counter for one login realm.

    The tool and the viewer each own an instance, so filling up the viewer
    portal's budget never locks the tool as well, and each realm reads its own
    `COPYLOT_<PREFIX>_LOGIN_RATE_LIMIT_*` settings. Within a realm the count is
    per client (`rate_limit_key`: the IPv4 address or the IPv6 /64) and per
    bucket -- the bucket being the way in (password, link, qr), so a failing
    QR code does not spend the password budget.
    """

    def __init__(self, env_prefix: str) -> None:
        self._env_prefix = env_prefix
        self._lock = RLock()
        self.attempts: dict[tuple[str, str], deque[float]] = {}

    def _env_int(self, suffix: str, default: int) -> int:
        return env_int(f"COPYLOT_{self._env_prefix}_LOGIN_RATE_LIMIT_{suffix}", default)

    def enabled(self) -> bool:
        raw = os.getenv(f"COPYLOT_{self._env_prefix}_LOGIN_RATE_LIMIT_ENABLED", "1")
        return str(raw).strip().lower() in TRUTHY_VALUES

    def clear(self, request: Request, *, bucket: str) -> None:
        """A successful login ends the count for that client: their own typos
        should not lock them out right after they got in."""
        with self._lock:
            self.attempts.pop((rate_limit_key(client_address(request)), bucket), None)

    def enforce(self, request: Request, *, bucket: str) -> None:
        if not self.enabled():
            return
        limit = max(1, self._env_int("MAX_ATTEMPTS", 12))
        window_seconds = max(1, self._env_int("WINDOW_SECONDS", 300))
        now = time.monotonic()
        cutoff = now - window_seconds
        key = (rate_limit_key(client_address(request)), bucket)
        with self._lock:
            for stale in [k for k, seen in self.attempts.items() if not _drop_expired(seen, cutoff)]:
                self.attempts.pop(stale, None)
            attempts = self.attempts.setdefault(key, deque())
            if len(attempts) >= limit:
                raise HTTPException(
                    status_code=429,
                    detail="Too many login attempts. Please wait and try again.",
                )
            attempts.append(now)
