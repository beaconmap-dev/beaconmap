"""Telling public internet addresses from local ones."""

from __future__ import annotations

import ipaddress


def classify_ip(raw: str) -> tuple[str, bool]:
    """Return (normalized ip, is_public). Handles IPv6 zones and IPv4-mapped IPv6."""
    raw = raw.split("%", 1)[0]
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return raw, False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    public = not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_unspecified or ip.is_reserved
    )
    return str(ip), public
