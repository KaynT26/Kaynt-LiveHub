from __future__ import annotations

import unittest
from unittest.mock import patch

import moderation


class FakeResponse:
    def __init__(self, status_code: int, data: dict[str, object], text: str = "") -> None:
        self.status_code = status_code
        self.data = data
        self.text = text

    def json(self) -> dict[str, object]:
        return self.data


class FakeClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.request = None

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        if len(_args) != 3:
            raise AssertionError("Unexpected async context manager exit arguments")
        return None

    async def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.request = (url, kwargs)
        return self.response


class BlockUserTests(unittest.IsolatedAsyncioTestCase):
    @patch("moderation.store.effective_session", return_value={"sid": "sid", "idc": "alisg"})
    async def test_posts_event_user_to_the_connected_room(self, session: object) -> None:
        client = FakeClient(FakeResponse(200, {"status_code": 0}))
        with patch("moderation.httpx.AsyncClient", return_value=client):
            await moderation.block_user("connected-room-id", "event-user-id")
        session.assert_called_once_with()

        url, kwargs = client.request
        self.assertEqual(url, "https://webcast.tiktok.com/webcast/room/kick/user/")
        self.assertEqual(kwargs["params"], {"aid": "1988"})
        self.assertEqual(kwargs["cookies"], {"sessionid": "sid", "store-idc": "alisg"})
        self.assertEqual(kwargs["json"], {"room_id": "connected-room-id", "kick_uid": "event-user-id"})

    @patch("moderation.store.effective_session", return_value={"sid": "sid", "idc": "alisg"})
    async def test_reports_permission_error_even_with_http_200(self, session: object) -> None:
        client = FakeClient(FakeResponse(200, {"status_code": 4, "status_msg": "no permission"}))
        with patch("moderation.httpx.AsyncClient", return_value=client):
            with self.assertRaisesRegex(moderation.ModError, "no permission"):
                await moderation.block_user("connected-room-id", "event-user-id")
        session.assert_called_once_with()

    @patch("moderation.store.effective_session", return_value={"sid": "sid", "idc": "alisg"})
    async def test_reports_http_failure(self, session: object) -> None:
        client = FakeClient(FakeResponse(403, {}, "no permission"))
        with patch("moderation.httpx.AsyncClient", return_value=client):
            with self.assertRaisesRegex(moderation.ModError, "403.*no permission"):
                await moderation.block_user("connected-room-id", "event-user-id")
        session.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
