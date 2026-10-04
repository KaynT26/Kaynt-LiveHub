from __future__ import annotations

import inspect
from functools import wraps


def _patch_tiktok_live_client() -> None:
    """Support legacy TikTokLiveClient(fetch_room_info=True) across library versions."""
    try:
        from TikTokLive.client.client import TikTokLiveClient
    except Exception:
        return

    if "fetch_room_info" in inspect.signature(TikTokLiveClient.__init__).parameters:
        return

    original_init = TikTokLiveClient.__init__

    @wraps(original_init)
    def compat_init(self, *args, fetch_room_info=None, **kwargs):
        return original_init(self, *args, **kwargs)

    TikTokLiveClient.__init__ = compat_init


_patch_tiktok_live_client()
