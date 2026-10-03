"""Connect to the configured TikTok LIVE using TikTokLiveClient."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values
from TikTokLive.client.client import TikTokLiveClient
from TikTokLive.client.errors import UserOfflineError
from TikTokLive.client.logger import LogLevel
from TikTokLive.events import ConnectEvent


TEST_ENV = Path(__file__).resolve().parents[1] / "test.env"
config = dotenv_values(TEST_ENV)

username = str(config.get("TIKTOK_USERNAME") or "").strip().lstrip("@")
session_id = str(config.get("TIKTOK_SESSIONID") or "").strip()
target_idc = str(config.get("TIKTOK_TARGET_IDC") or "").strip()

if not username:
    raise SystemExit(f"Fill TIKTOK_USERNAME in {TEST_ENV.name}")
if not session_id or not target_idc:
    raise SystemExit(f"Fill TIKTOK_SESSIONID and TIKTOK_TARGET_IDC in {TEST_ENV.name}")

client: TikTokLiveClient = TikTokLiveClient(unique_id=username,fetch_room_info=True)


@client.on(ConnectEvent)
async def on_connect(event: ConnectEvent) -> None:
    client.logger.info(f"Connected to @{event.unique_id}!")
    client.logger.info(f"Room ID: {client.room_info}")


if __name__ == "__main__":
    client.logger.setLevel(LogLevel.INFO.value)
    client.web.set_session(session_id, target_idc)
    os.environ["WHITELIST_AUTHENTICATED_SESSION_ID_HOST"] = "api.eulerstream.com"
    try:
        client.run()
    except UserOfflineError:
        raise SystemExit(f"@{username} is not live right now.")
