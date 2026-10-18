from __future__ import annotations

import re
import unittest
from unittest.mock import patch

import app as web


class LoginRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = web.app.test_client()
        self.remote = {"REMOTE_ADDR": "203.0.113.10"}

    def _csrf_token(self, response) -> str:
        match = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True))
        self.assertIsNotNone(match)
        return match.group(1)

    def test_unauthenticated_remote_request_redirects_to_custom_login(self) -> None:
        with patch.object(web, "_password", return_value="test-password"):
            response = self.client.get("/", environ_overrides=self.remote)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.location)

    def test_loopback_request_still_requires_login_when_password_is_set(self) -> None:
        with patch.object(web, "_password", return_value="test-password"):
            response = self.client.get("/", environ_overrides={"REMOTE_ADDR": "127.0.0.1"})

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.location)

    def test_login_uses_csrf_cookie_session_and_logout(self) -> None:
        with patch.object(web, "_password", return_value="test-password"):
            page = self.client.get("/login", environ_overrides=self.remote)
            token = self._csrf_token(page)
            failed = self.client.post(
                "/login",
                data={"csrf_token": token, "password": "wrong"},
                environ_overrides=self.remote,
            )
            self.assertEqual(failed.status_code, 401)

            token = self._csrf_token(failed)
            success = self.client.post(
                "/login",
                data={"csrf_token": token, "password": "test-password", "next": "/"},
                environ_overrides=self.remote,
            )
            self.assertEqual(success.status_code, 302)
            self.assertEqual(success.location, "/")
            self.assertEqual(self.client.get("/api/ping", environ_overrides=self.remote).status_code, 200)

            dashboard = self.client.get("/", environ_overrides=self.remote)
            token = self._csrf_token(dashboard)
            logout = self.client.post(
                "/logout",
                data={"csrf_token": token},
                environ_overrides=self.remote,
            )

        self.assertEqual(logout.status_code, 302)
        self.assertIn("/login", logout.location)

    def test_external_redirect_target_is_rejected(self) -> None:
        with patch.object(web, "_password", return_value="test-password"):
            page = self.client.get(
                "/login?next=https://attacker.example/",
                environ_overrides=self.remote,
            )
            token = self._csrf_token(page)
            response = self.client.post(
                "/login",
                data={"csrf_token": token, "password": "test-password"},
                environ_overrides=self.remote,
            )

        self.assertEqual(response.location, "/")


if __name__ == "__main__":
    unittest.main()
