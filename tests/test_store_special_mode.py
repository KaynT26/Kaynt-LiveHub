from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import store


class SpecialModeStoreTests(unittest.TestCase):
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

    def test_special_rooms_are_normalized_and_removed_with_room(self) -> None:
        store.set_special_rooms([" Creator ", "creator", "second"])
        self.assertEqual(store.get()["special_rooms"], ["creator", "second"])

        store.forget_room("CREATOR")

        self.assertEqual(store.get()["special_rooms"], ["second"])

    def test_trusted_user_and_block_status_are_persisted(self) -> None:
        store.save_trusted_user({
            "id": "12345", "nickname": "Person", "unique_id": "@person",
            "category": "staff", "note": "Support",
        })
        store.record_block("12345", "creator")
        store.record_block("12345", "creator")

        saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["trusted_users"], [{
            "id": "12345", "nickname": "Person", "unique_id": "person",
            "category": "family", "note": "Support",
        }])
        self.assertEqual(saved["blocked_users"], {"12345": ["creator"]})

    def test_trusted_user_requires_numeric_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "phải là số"):
            store.save_trusted_user({"id": "not-an-id"})


if __name__ == "__main__":
    unittest.main()
