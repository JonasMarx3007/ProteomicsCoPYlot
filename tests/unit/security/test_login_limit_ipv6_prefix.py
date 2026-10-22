"""The login limiter counts an IPv6 client by its /64.

Per full address, a customer who owns a /64 can rotate through fresh addresses
and never trip the per-client limit; with the process-wide password budget in
place that turned into a cheap way to keep the budget full and lock every real
viewer out. IPv4 and non-IP identities are unchanged.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.request_security import LoginRateLimit, rate_limit_key


def _request(address: str):
    return SimpleNamespace(client=SimpleNamespace(host=address), headers=SimpleNamespace(getlist=lambda name: []))


def test_ipv6_addresses_in_one_64_share_a_key_and_others_do_not() -> None:
    assert rate_limit_key("2001:db8::1") == rate_limit_key("2001:db8::2") == rate_limit_key("2001:db8:0:0:ffff:ffff:ffff:ffff")
    assert rate_limit_key("2001:db8::1") == "2001:db8::/64"
    assert rate_limit_key("2001:db8:0:1::1") != rate_limit_key("2001:db8::1")
    assert rate_limit_key("10.0.0.7") == "10.0.0.7" and rate_limit_key("10.0.0.8") != "10.0.0.7"
    assert rate_limit_key("::ffff:10.0.0.7") == "10.0.0.7"  # IPv4-mapped is the IPv4 client
    assert rate_limit_key("unknown") == "unknown"


def test_rotating_within_a_64_trips_the_limit(monkeypatch) -> None:
    monkeypatch.setenv("COPYLOT_VIEWER_LOGIN_RATE_LIMIT_MAX_ATTEMPTS", "3")
    limit = LoginRateLimit("VIEWER")
    for suffix in ("1", "2", "3"):
        limit.enforce(_request(f"2001:db8::{suffix}"), bucket="password")
    with pytest.raises(HTTPException) as refused:
        limit.enforce(_request("2001:db8::4"), bucket="password")
    assert refused.value.status_code == 429
    limit.enforce(_request("2001:db8:0:1::1"), bucket="password")  # another /64 is another client
    limit.clear(_request("2001:db8::9"), bucket="password")
    limit.enforce(_request("2001:db8::1"), bucket="password")  # cleared for the whole /64
