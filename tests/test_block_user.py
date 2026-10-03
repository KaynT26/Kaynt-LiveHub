import asyncio
import httpx


URL = "https://webcast.tiktok.com/webcast/room/kick/user/?aid=1988"

ROOM_ID = "7691966945242958600"
KICK_UID = "7107466545018799106"

COOKIE = "sessionid=7e3aa239946b7c95ba9b6b992fbc5544;store-idc=alisg;"


async def kick_user():
    headers = {
        "Content-Type": "application/json",
        "Cookie": COOKIE,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
    }

    payload = {
        "room_id": ROOM_ID,
        "kick_uid": KICK_UID,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            URL,
            headers=headers,
            json=payload,
        )

    print("Status:", response.status_code)
    print("Response:", response.text)


if __name__ == "__main__":
    asyncio.run(kick_user())