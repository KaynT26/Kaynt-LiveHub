"""Direct TikTok room moderation requests."""
from __future__ import annotations

from typing import Any

import httpx

import store

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")


class ModError(Exception):
    pass


async def block_user(room_id: str, user_id: str) -> None:
    """Block a user in the specified live room via TikTok's webcast endpoint."""
    session = store.effective_session()
    if not session["sid"]:
        raise ModError("Chưa có sessionid trong Cài đặt")
    if not session["idc"]:
        raise ModError("Thiếu tt-target-idc trong Cài đặt")

    headers = {
        "User-Agent": UA,
        "Referer": "https://www.tiktok.com/",
        "Origin": "https://www.tiktok.com",
    }
    payload = {"room_id": room_id, "kick_uid": user_id}
    async with httpx.AsyncClient(timeout=15, headers=headers) as client:
        response = await client.post(
            "https://webcast.tiktok.com/webcast/room/kick/user/",
            params={"aid": "1988"},
            cookies={"sessionid": session["sid"], "store-idc": session["idc"]},
            json=payload,
        )

    try:
        result: Any = response.json()
    except ValueError:
        result = {}

    if response.status_code != 200:
        message = result.get("message") if isinstance(result, dict) else ""
        raise ModError(f"TikTok từ chối chặn user ({response.status_code}): {message or response.text[:200]}")

    if isinstance(result, dict):
        status_code = result.get("status_code")
        if status_code not in (None, 0, "0"):
            extra = result.get("extra") or {}
            extra_message = extra.get("message") if isinstance(extra, dict) else ""
            message = result.get("status_msg") or result.get("message") or extra_message or response.text[:200]
            raise ModError(f"TikTok từ chối chặn user (status {status_code}): {message}")
