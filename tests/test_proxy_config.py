from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import httpx

from proxy_config import tiktok_proxy


class TikTokProxyTests(unittest.TestCase):
    def test_proxy_is_optional(self) -> None:
        with patch.dict(os.environ, {"TIKTOK_PROXY": ""}):
            self.assertIsNone(tiktok_proxy())

    def test_authenticated_http_proxy_is_parsed(self) -> None:
        with patch.dict(os.environ, {"TIKTOK_PROXY": "http://proxy-user:proxy-pass@proxy.example:8080"}):
            proxy = tiktok_proxy()

        self.assertIsInstance(proxy, httpx.Proxy)
        self.assertEqual(proxy.auth, ("proxy-user", "proxy-pass"))

    def test_invalid_proxy_has_safe_error(self) -> None:
        with patch.dict(os.environ, {"TIKTOK_PROXY": "ftp://secret:password@proxy.example:21"}):
            with self.assertRaisesRegex(ValueError, "TIKTOK_PROXY không hợp lệ") as raised:
                tiktok_proxy()

        self.assertNotIn("secret", str(raised.exception))
        self.assertNotIn("password", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
