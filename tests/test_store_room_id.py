from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import store


class SaveRoomIdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.temp_dir.name) / "settings.json"
        self.patch_path = patch.object(store, "PATH", str(self.settings_path))
        self.patch_path.start()
        self.old_data = store._data
        store._data = {}

    def tearDown(self) -> None:
        store._data = self.old_data
        self.patch_path.stop()
        self.temp_dir.cleanup()

    def test_persists_server_room_id_on_existing_room(self) -> None:
        store.save_room("creator", auto_reconnect=False, auto_record=True)

        store.save_room_id("creator", 7692014932523600641)

        saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
        room = saved["rooms"][0]
        self.assertEqual(room["room_id"], "7692014932523600641")
        self.assertFalse(room["auto_reconnect"])
        self.assertTrue(room["auto_record"])

    def test_upserts_room_id_if_room_was_not_saved_yet(self) -> None:
        store.save_room_id("creator", "7692014932523600641")

        room = json.loads(self.settings_path.read_text(encoding="utf-8"))["rooms"][0]
        self.assertEqual(room["unique_id"], "creator")
        self.assertEqual(room["room_id"], "7692014932523600641")

    def test_rejects_non_numeric_room_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "digits only"):
            store.save_room_id("creator", "not-a-room-id")


if __name__ == "__main__":
    unittest.main()
