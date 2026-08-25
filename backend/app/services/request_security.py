from __future__ import annotations

import ipaddress
import os

from fastapi import Request


def client_address(request: Request) -> str:
    peer = request.client.host if request.client and request.client.host else "unknown"
    trusted = {
        value.strip()
        for value in str(os.getenv("COPYLOT_TRUSTED_PROXY_IPS", "")).split(",")
        if value.strip()
    }
    if peer not in trusted:
        return peer

    forwarded = str(request.headers.get("x-forwarded-for", "")).split(",", 1)[0].strip()
    try:
        return str(ipaddress.ip_address(forwarded))
    except ValueError:
        return peer
