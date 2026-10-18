"""Shared outbound proxy configuration for TikTok traffic."""
from __future__ import annotations

import os
from urllib.parse import urlsplit

import httpx


def tiktok_proxy() -> httpx.Proxy | None:
    """Return the configured HTTP/SOCKS proxy without exposing credentials in errors."""
    return parse_tiktok_proxy(os.environ.get("TIKTOK_PROXY", ""))


def parse_tiktok_proxy(value: str | None) -> httpx.Proxy | None:
    """Parse a proxy URL from an explicit configuration value."""
    value = (value or "").strip()
    if not value:
        return None

    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https", "socks5"} or not parsed.hostname:
            raise ValueError
        parsed.port
        return httpx.Proxy(value)
    except (ValueError, httpx.InvalidURL) as ex:
        raise ValueError(
            "TIKTOK_PROXY không hợp lệ; dùng URL dạng http://user:pass@host:port hoặc socks5://host:port"
        ) from ex
