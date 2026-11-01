from __future__ import annotations

import unittest

from TikTokLiveProto.v3.webcast.model import Hashtag
from TikTokLiveProto.v3.webcast.model.data import HashtagNamespace


class TikTokProtoForwardReferenceTests(unittest.TestCase):
    def test_parsing_hashtag_resolves_namespace_enum(self) -> None:
        hashtag = Hashtag.parse(bytes((0x20, HashtagNamespace.GAMING.value)))

        self.assertEqual(hashtag.namespace, HashtagNamespace.GAMING)


if __name__ == "__main__":
    unittest.main()
