from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

import app as web
import store


class SpecialModeRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path_patch = patch.object(store, "PATH", str(Path(self.temp_dir.name) / "settings.json"))
        self.path_patch.start()
        self.old_data = store._data
        store._data = {}
        self.client = web.app.test_client()

    def tearDown(self) -> None:
        store._data = self.old_data
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def test_block_sync_targets_only_selected_rooms_and_reports_partial_failure(self) -> None:
        store.set_special_rooms(["alpha", "beta", "gamma"])
        room_ids = {"alpha": "room-a", "beta": "room-b", "gamma": "room-c"}

        def run_block(request: tuple[str, str], _timeout: int) -> None:
            if request[0] == "room-b":
                raise web.moderation.ModError("Room unavailable")

        with (
            patch.object(web, "_block_allowed", return_value=True),
            patch.object(web.hub, "room_ids", side_effect=lambda uid: {"room_id": room_ids[uid]}) as get_room,
            patch.object(web.hub, "_call", side_effect=run_block) as run_call,
            patch.object(web.moderation, "block_user", new=lambda room_id, user_id: (room_id, user_id)),
        ):
            response = self.client.post("/api/special-mode/block-user", json={"user_id": "98765"})

        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual([item["room"] for item in result["statuses"]], ["alpha", "beta", "gamma"])
        self.assertEqual([item["ok"] for item in result["statuses"]], [True, False, True])
        self.assertEqual(get_room.call_args_list, [call("alpha"), call("beta"), call("gamma")])
        self.assertEqual(run_call.call_count, 3)
        self.assertEqual(store.get()["blocked_users"], {"98765": ["alpha", "gamma"]})

    def test_room_selection_rejects_rooms_not_in_livehub(self) -> None:
        with patch.object(web.hub, "snapshot", return_value={"rooms": [{"unique_id": "alpha"}]}):
            response = self.client.post("/api/special-mode", json={"rooms": ["alpha", "unknown"]})

        self.assertEqual(response.status_code, 400)
        self.assertIn("unknown", response.get_json()["error"])
        self.assertEqual(store.get()["special_rooms"], [])


if __name__ == "__main__":
    unittest.main()
