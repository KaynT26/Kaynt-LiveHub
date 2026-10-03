"""Opt-in probes for direct TikTok LIVE chat and the TikTokLive/Euler route."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping
from typing import Any

import httpx
from dotenv import dotenv_values
from TikTokLive.client.errors import UserOfflineError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_ENV = os.path.join(ROOT, "test.env")
CHAT_URL = "https://webcast.tiktok.com/webcast/room/chat/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
)


class ProbeError(ValueError):
    pass


def _required(values: Mapping[str, Any], key: str) -> str:
    value = str(values.get(key) or "").strip()
    if not value or value.startswith("REPLACE_"):
        raise ProbeError(f"Fill {key} in test.env")
    return value


def build_direct_request(
    values: Mapping[str, Any], room_id: str | None = None
) -> tuple[str, dict[str, str], dict[str, str], dict[str, str]]:
    """Build a TikTok chat request using the user's supplied request shape."""
    username = _required(values, "TIKTOK_USERNAME").lstrip("@")
    if not username or any(char in username for char in "/?# \r\n"):
        raise ProbeError("TIKTOK_USERNAME must be a TikTok username without a URL")
    configured_room = _required(values, "TIKTOK_ROOM_ID")
    if not configured_room.isdigit():
        raise ProbeError("TIKTOK_ROOM_ID must contain digits only")
    actual_room = str(room_id or configured_room).strip()
    if not actual_room.isdigit():
        raise ProbeError("Connected live returned an invalid room ID")
    if actual_room != configured_room:
        raise ProbeError(
            f"Connected room ID {actual_room} does not match TIKTOK_ROOM_ID"
        )
    comment = _required(values, "TIKTOK_TEST_COMMENT")
    if any(char in comment for char in "\r\n"):
        raise ProbeError("TIKTOK_TEST_COMMENT cannot contain newlines")
    sessionid = _required(values, "TIKTOK_SESSIONID")
    target_idc = _required(values, "TIKTOK_TARGET_IDC")
    if any(char in sessionid + target_idc for char in "\r\n;"):
        raise ProbeError("Session cookie values contain invalid characters")

    params = {
        "aid": "1988",
        "app_name": "tiktok_web",
        "device_platform": "web_pc",
        "room_id": actual_room,
        "content": comment,
    }
    cookies = {"sessionid": sessionid, "tt-target-idc": target_idc}
    headers = {
        "User-Agent": USER_AGENT,
        "Origin": "https://www.tiktok.com",
        "Referer": "https://www.tiktok.com/",
    }
    return CHAT_URL, params, cookies, headers


def _safe_response(response: httpx.Response) -> dict[str, Any]:
    result: dict[str, Any] = {
        "http_status": response.status_code,
        "response_bytes": len(response.content),
    }
    try:
        data = response.json()
    except (ValueError, json.JSONDecodeError):
        result["json_response"] = False
    else:
        result["json_response"] = True
        if isinstance(data, dict):
            result["response_keys"] = sorted(data.keys())
            for key in ("status_code", "code", "message"):
                if key in data and isinstance(data[key], (str, int, float, bool, type(None))):
                    result[key] = data[key]
    return result


async def run_direct(values: Mapping[str, Any]) -> dict[str, Any]:
    url, params, cookies, headers = build_direct_request(values)
    username = _required(values, "TIKTOK_USERNAME").lstrip("@")
    print(f"Connecting to TikTok LIVE for user {username}...")
    expected_room = _required(values, "TIKTOK_ROOM_ID")
    comment = _required(values, "TIKTOK_TEST_COMMENT")
    from TikTokLive import TikTokLiveClient
    from TikTokLive.events import ConnectEvent

    live_client = TikTokLiveClient(unique_id=username)
    connected = asyncio.get_running_loop().create_future()
    sent = False

    @live_client.on(ConnectEvent)
    async def on_connect(event: ConnectEvent) -> None:
        nonlocal sent
        if sent:
            return
        sent = True
        try:
            actual_room = str(event.room_id)
            if actual_room != expected_room:
                raise ProbeError(
                    f"Connected room ID {actual_room} does not match TIKTOK_ROOM_ID"
                )
            await asyncio.sleep(2)
            async with httpx.AsyncClient(
                cookies=cookies,
                headers=headers,
                timeout=httpx.Timeout(15.0),
                follow_redirects=False,
            ) as http:
                response = await http.post(
                    url,
                    params={**params, "room_id": actual_room, "content": comment},
                )
            if not connected.done():
                connected.set_result(_safe_response(response))
        except Exception as ex:
            if not connected.done():
                connected.set_exception(ex)

    try:
        await live_client.start(fetch_live_check=True, room_id=int(expected_room))
        result = await asyncio.wait_for(connected, timeout=120)
        return result
    finally:
        try:
            await live_client.disconnect()
        finally:
            await live_client.web.close()


async def run_euler(values: Mapping[str, Any]) -> dict[str, Any]:
    if values.get("ALLOW_EULER_SESSION") != "I_UNDERSTAND":
        raise ProbeError(
            "Set ALLOW_EULER_SESSION=I_UNDERSTAND to authorize sending your session to Euler"
        )
    api_key = _required(values, "EULER_SIGN_API_KEY")
    username = _required(values, "TIKTOK_USERNAME").lstrip("@")
    room_id = _required(values, "TIKTOK_ROOM_ID")
    content = _required(values, "TIKTOK_TEST_COMMENT")
    sessionid = _required(values, "TIKTOK_SESSIONID")
    target_idc = _required(values, "TIKTOK_TARGET_IDC")

    os.environ["SIGN_API_KEY"] = api_key
    os.environ["WHITELIST_AUTHENTICATED_SESSION_ID_HOST"] = "api.eulerstream.com"
    from TikTokLive import TikTokLiveClient

    client = TikTokLiveClient(unique_id=username)
    client.web.set_session(sessionid, target_idc)
    try:
        result = await client.web.send_room_chat(content=content, room_id=int(room_id))
    finally:
        await client.web.close()
    if not isinstance(result, dict):
        return {"result_type": type(result).__name__, "response": "No structured response"}
    return {
        "result_type": type(result).__name__,
        "code": result.get("code"),
        "message": result.get("message"),
        "has_data": result.get("data") is not None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Manually probe TikTok LIVE comment sending")
    parser.add_argument("--mode", choices=("direct", "euler"), required=True)
    parser.add_argument(
        "--send",
        action="store_true",
        help="Actually send the configured test comment to the live room",
    )
    args = parser.parse_args()
    if not args.send:
        parser.error("No request sent. Add --send to explicitly post the test comment.")

    values = dotenv_values(TEST_ENV)
    try:
        result = asyncio.run(run_direct(values) if args.mode == "direct" else run_euler(values))
    except (ProbeError, httpx.HTTPError, UserOfflineError, ValueError, asyncio.TimeoutError) as ex:
        print(f"Probe failed: {type(ex).__name__}: {ex}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    print("An HTTP 200 response, especially an empty response, does not prove the comment appeared.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
