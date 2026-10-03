from __future__ import annotations

import unittest

from live_comment_probe import ProbeError, build_direct_request


def captured_values(**overrides: str) -> dict[str, str]:
    values = {
        "TIKTOK_USERNAME": "sotiredguy",
        "TIKTOK_ROOM_ID": "7692014932523600641",
        "TIKTOK_TEST_COMMENT": "LiveHub probe",
        "TIKTOK_SESSIONID": "session-value",
        "TIKTOK_TARGET_IDC": "useast1a",
    }
    values.update(overrides)
    return values


class BuildDirectRequestTests(unittest.TestCase):
    def test_builds_request_with_sessionid_and_target_idc_cookies(self) -> None:
        url, params, cookies, headers = build_direct_request(captured_values())

        self.assertEqual(url, "https://webcast.tiktok.com/webcast/room/chat/")
        self.assertEqual(params["room_id"], "7692014932523600641")
        self.assertEqual(params["content"], "LiveHub probe")
        self.assertEqual(params["aid"], "1988")
        self.assertEqual(
            cookies,
            {"sessionid": "session-value", "tt-target-idc": "useast1a"},
        )
        self.assertEqual(headers["Origin"], "https://www.tiktok.com")
        self.assertNotIn("Cookie", headers)

    def test_accepts_username_with_at_prefix(self) -> None:
        _, _, _, _ = build_direct_request(captured_values())

    def test_rejects_username_that_is_not_a_handle(self) -> None:
        with self.assertRaisesRegex(ProbeError, "TIKTOK_USERNAME"):
            build_direct_request(captured_values(TIKTOK_USERNAME="https://example.com"))

    def test_rejects_room_mismatch_from_connected_live(self) -> None:
        with self.assertRaisesRegex(ProbeError, "does not match"):
            build_direct_request(captured_values(), room_id="999")

    def test_rejects_non_numeric_room_id(self) -> None:
        with self.assertRaisesRegex(ProbeError, "digits only"):
            build_direct_request(captured_values(TIKTOK_ROOM_ID="room-123"))

    def test_rejects_empty_comment(self) -> None:
        with self.assertRaisesRegex(ProbeError, "TIKTOK_TEST_COMMENT"):
            build_direct_request(captured_values(TIKTOK_TEST_COMMENT=""))

    def test_rejects_cookie_delimiters(self) -> None:
        with self.assertRaisesRegex(ProbeError, "invalid characters"):
            build_direct_request(captured_values(TIKTOK_TARGET_IDC="bad;value"))


if __name__ == "__main__":
    unittest.main()
