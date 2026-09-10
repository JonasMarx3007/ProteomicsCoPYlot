from __future__ import annotations

import ipaddress
import os

from fastapi import Request

from app.services.tool_access import tool_access_enabled


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


def local_path_access_allowed(request: Request) -> bool:
    try:
        address = ipaddress.ip_address(client_address(request).strip())
    except ValueError:
        return False
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if not address.is_loopback:
        return False
    override = str(os.getenv("COPYLOT_ALLOW_LOCAL_PATH_APIS", "")).strip().lower()
    return not tool_access_enabled() or override in {"1", "true", "yes", "on"}
