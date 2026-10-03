"""
LiveHub: theo dõi NHIỀU phiên TikTok LIVE cùng lúc.

- Mỗi phòng là một LiveSession: TikTokLiveClient riêng, thống kê riêng, log riêng, ghi hình riêng.
- Tất cả chạy chung một asyncio loop ở thread nền.
- Sự kiện của mọi phòng được broadcast qua một kênh (SSE), gắn khóa "room" = username.
"""
from __future__ import annotations

import asyncio
import json
import os
import queue
import re
import threading
import time
from collections import Counter, deque
from datetime import datetime
from typing import Any, Dict, List, Optional

import store
from TikTokLive import TikTokLiveClient
from TikTokLive.client.errors import (
    AgeRestrictedError,
    AuthenticatedWebSocketConnectionError,
    SignAPIError,
    SignatureRateLimitError,
    UserNotFoundError,
    UserOfflineError,
)
from TikTokLive.events import (
    BarrageEvent,
    CommentEvent,
    ConnectEvent,
    DisconnectEvent,
    FollowEvent,
    GiftEvent,
    JoinEvent,
    LikeEvent,
    LiveEndEvent,
    LivePauseEvent,
    LiveUnpauseEvent,
    RoomUserSeqEvent,
    ShareEvent,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")

SAMPLE_EVERY = 10          # giây / 1 điểm trên biểu đồ
MAX_SAMPLES = 360          # 1 giờ
MAX_RECENT = 300           # số sự kiện giữ lại cho người mở trang sau
MAX_ROOMS = int(os.environ.get("MAX_ROOMS", "8"))
START_STAGGER = float(os.environ.get("START_STAGGER", "2"))   # giây giữa 2 phòng khi Bắt đầu tất cả
MAX_TRACKED_USERS = 50000
# BarrageEvent.msg_type -> loại thông báo nổi bật (chỉ lấy loại gắn với 1 người dùng)
BARRAGE_KINDS = {9: "entrance", 11: "fan_entrance", 15: "enigma_entrance",
                 8: "level_up", 10: "fan_level_up", 4: "subscribe"}   # số người tối đa giữ thống kê / phòng / phiên
USER_RECENT = 30            # số hoạt động gần nhất giữ cho mỗi người
QUALITY_ORDER = ["origin", "uhd", "hd", "sd", "ld", "full_hd1", "hd1", "sd1", "sd2", "default"]
ACTIVE = ("connecting", "connected", "reconnecting")
USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,64}$")

VIDEO_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"),
    "Referer": "https://www.tiktok.com/",
    "Origin": "https://www.tiktok.com",
}




# ----------------------------------------------------------------- sessionid (đăng nhập TikTok)
SIGN_HOST = "api.eulerstream.com"


def session_config() -> Dict[str, Any]:
    """Cấu hình sessionid hiện hành (giao diện > .env). Đọc lại mỗi lần kết nối."""
    e = store.effective_session()
    sid, idc, mode = e["sid"], e["idc"], e["mode"]
    if mode not in ("auto", "always", "off"):
        mode = "auto"
    problem = ""
    if sid and not idc:
        problem = "Thiếu tt-target-idc (nhập trong Cài đặt)"
    elif sid and not e["consent"]:
        problem = "Chưa tick đồng ý gửi sessionid tới máy chủ ký Euler Stream (trong Cài đặt)"
    if sid and e["consent"]:
        os.environ["WHITELIST_AUTHENTICATED_SESSION_ID_HOST"] = SIGN_HOST
    return {
        "configured": bool(sid),
        "ready": bool(sid) and not problem and mode != "off",
        "mode": mode,
        "problem": problem,
        "masked": _mask(sid),
        "source": "ui" if e["from_ui"] else ("env" if sid else ""),
        "_sid": sid,
        "_idc": idc,
    }


def _mask(v: str) -> str:
    return (v[:4] + "…" + v[-4:]) if len(v) > 10 else ("***" if v else "")


def sign_public() -> Dict[str, Any]:
    """Trạng thái API key Euler Stream (TikTokLive tự đọc SIGN_API_KEY mỗi khi tạo client mới)."""
    key = store.effective_sign_key()
    return {"configured": bool(key), "masked": _mask(key),
            "url": os.environ.get("SIGN_API_URL", "").strip() or f"https://{SIGN_HOST}"}


def session_public() -> Dict[str, Any]:
    return {k: v for k, v in session_config().items() if not k.startswith("_")}


# ----------------------------------------------------------------- helpers
def _img(image: Any) -> Optional[str]:
    try:
        urls = getattr(image, "url_list", None) or []
        return urls[0] if urls else None
    except Exception:
        return None


# ----------------------------------------------------------------- badge / level người dùng
_SCENE_NAMES = {1: "ADMIN", 2: "FIRST_RECHARGE", 3: "FRIENDS", 4: "SUBSCRIBER", 5: "ACTIVITY",
                6: "RANK_LIST", 7: "NEW_SUBSCRIBER", 8: "USER_GRADE", 9: "STATE_CONTROLLED_MEDIA",
                10: "FANS", 11: "LIVE_PRO", 12: "ANCHOR", 13: "CLASS_RANK", 14: "ENIGMA"}
BADGE_SAMPLE_MAX = int(os.environ.get("BADGE_SAMPLE_MAX", "40"))
# Nhận diện badge theo uri icon (giống utils/badges.py của sensor) – ổn định hơn scene_type
GIFT_BADGE_MARKER = "grade_badge_icon_lite_lv"
TEAM_BADGE_MARKER = "fans_badge_icon_lv"
_badge_samples = 0
_badge_sample_lock = threading.Lock()


def _int(v: Any) -> Optional[int]:
    try:
        n = int(str(v).strip())
        return n
    except (TypeError, ValueError):
        return None


def _scene_name(v: Any) -> str:
    try:
        return _SCENE_NAMES.get(int(v), getattr(v, "name", str(v)))
    except (TypeError, ValueError):
        return str(getattr(v, "name", v))


def _badge_label(b: Any) -> str:
    """Chữ hiển thị trên badge (vd. '33', 'ROAR', 'No.1')."""
    comb = getattr(b, "combine", None)
    for cand in (getattr(comb, "str", None),
                 getattr(getattr(b, "str", None), "str", None)):
        if cand:
            return str(cand)
    for bt in (getattr(comb, "text", None), getattr(b, "text", None)):
        if bt is None:
            continue
        pat = getattr(bt, "default_pattern", "") or ""
        pieces = [str(p) for p in (getattr(bt, "pieces", None) or [])]
        if pat:
            try:  # pattern kiểu "{0:string}" / "{0}"
                return re.sub(r"\{(\d+)(:[^}]*)?\}",
                              lambda m: pieces[int(m.group(1))] if int(m.group(1)) < len(pieces) else "", pat)
            except Exception:
                return pat
        if pieces:
            return " ".join(pieces)
    return ""


def _badges(u: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for b in getattr(u, "badges", None) or getattr(u, "badge_list", None) or []:
        try:
            scene = _scene_name(getattr(b, "scene_type", 0))
            lvl = _int(getattr(getattr(b, "privilege_log_extra", None), "level", None)
                       or getattr(getattr(b, "log_extra", None), "level", None))
            comb = getattr(b, "combine", None)
            uri = str(getattr(getattr(comb, "icon", None), "uri", "") or "")
            if GIFT_BADGE_MARKER in uri:
                scene = "USER_GRADE"
            elif TEAM_BADGE_MARKER in uri:
                scene = "FANS"
            icon = _img(getattr(comb, "icon", None)) or _img(getattr(getattr(b, "image", None), "image", None))
            label = _badge_label(b)
            key = (scene, label, lvl)
            if key in seen or (not label and lvl is None and not icon):
                continue
            seen.add(key)
            bg = getattr(getattr(comb, "background", None), "background_color_code", "") or ""
            out.append({"scene": scene, "level": lvl, "label": label, "icon": icon, "bg": bg})
        except Exception:
            continue
    return out[:8]


def _sample_badges(u: Any, info: Dict[str, Any]) -> None:
    """Ghi vài mẫu badge thô ra logs/_badges_sample.jsonl để kiểm tra/chỉnh cách hiển thị."""
    global _badge_samples
    if _badge_samples >= BADGE_SAMPLE_MAX or not getattr(u, "badge_list", None):
        return
    with _badge_sample_lock:
        if _badge_samples >= BADGE_SAMPLE_MAX:
            return
        _badge_samples += 1
    try:
        raw = {
            "nickname": info.get("nickname"), "parsed": info,
            "badge_list": [b.to_dict() for b in u.badge_list],
            "fans_club": u.fans_club.to_dict() if getattr(u, "fans_club", None) else None,
            "pay_grade_level": getattr(getattr(u, "pay_grade", None), "level", None),
        }
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, "_badges_sample.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(raw, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _levels(u: Any, badges: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Level quà (gifter), fan club (tên + level), hạng trong phòng, mod, subscriber.
    Nhiều badge cùng loại -> lấy badge có level CAO NHẤT (giống utils/badges.py)."""
    by: Dict[str, Dict[str, Any]] = {}
    for b in badges:
        old = by.get(b["scene"])
        if old is None or (b["level"] or 0) > (old["level"] or 0):
            by[b["scene"]] = b
    gift_level = (by.get("USER_GRADE") or {}).get("level")
    if not gift_level:
        gift_level = _int(getattr(getattr(u, "pay_grade", None), "level", None)) or None
    fan = None
    data = getattr(getattr(u, "fans_club", None), "data", None)
    fb = by.get("FANS")
    badge_fan_lv = (fb or {}).get("level") or 0
    if data is not None and (getattr(data, "club_name", "") or _int(getattr(data, "level", 0))):
        fan = {"name": getattr(data, "club_name", "") or "",
               "level": max(_int(getattr(data, "level", 0)) or 0, badge_fan_lv)}
    elif fb:
        fan = {"name": fb["label"] if not str(fb["label"]).isdigit() else "", "level": badge_fan_lv or _int(fb["label"]) or 0}
    if fan is not None and "FANS" in by:
        fan["icon"] = by["FANS"].get("icon")
    # TikTok thường gửi 2 badge RANK_LIST (1 ảnh trống + 1 có chữ "No. 1") -> lấy cái có số
    rank, rank_icon, rank_bg = None, None, ""
    for b in badges:
        if b["scene"] != "RANK_LIST":
            continue
        m = re.search(r"\d+", b["label"] or "")
        if m and rank is None:
            rank = _int(m.group(0))
        rank_icon = rank_icon or b["icon"]
        rank_bg = rank_bg or b["bg"]
    if fan is not None and fb:
        fan["bg"] = fb.get("bg", "")
    return {
        "gift_level": gift_level or None,
        "gift_icon": (by.get("USER_GRADE") or {}).get("icon"),
        "gift_bg": (by.get("USER_GRADE") or {}).get("bg", ""),
        "fan": fan,
        "rank": rank,
        "rank_icon": rank_icon if rank else None,
        "rank_bg": rank_bg if rank else "",
        "mod": "ADMIN" in by,
        "sub": "SUBSCRIBER" in by or "NEW_SUBSCRIBER" in by,
    }


def _user(u: Any) -> Dict[str, Any]:
    if u is None:
        return {"id": "", "unique_id": "", "nickname": "Ẩn danh", "avatar": None}
    uid = getattr(u, "display_id", None) or getattr(u, "unique_id", None) or ""
    info: Dict[str, Any] = {
        "id": str(getattr(u, "id", "") or uid),
        "unique_id": uid,
        "nickname": getattr(u, "nickname", None) or uid or "Ẩn danh",
        "avatar": _img(getattr(u, "avatar_thumb", None)),
    }
    try:
        badges = _badges(u)
        info.update(_levels(u, badges))
        info["badges"] = badges
        fi = getattr(u, "follow_info", None)
        info["followers"] = _int(getattr(fi, "follower_count", None)) or 0
        info["following"] = _int(getattr(fi, "following_count", None)) or 0
        _sample_badges(u, info)
    except Exception:
        pass
    return info


def extract_streams(room_info: Optional[dict]) -> Dict[str, Dict[str, Optional[str]]]:
    """Lấy các link FLV/HLS theo chất lượng từ room_info."""
    out: Dict[str, Dict[str, Optional[str]]] = {}
    if not room_info:
        return out
    su = room_info.get("stream_url") or {}
    try:
        raw = su["live_core_sdk_data"]["pull_data"]["stream_data"]
        data = json.loads(raw).get("data", {})
        for q, v in data.items():
            main = (v or {}).get("main") or {}
            if main.get("flv") or main.get("hls"):
                out[q.lower()] = {"flv": main.get("flv"), "hls": main.get("hls")}
    except Exception:
        pass
    for q, url in (su.get("flv_pull_url") or {}).items():
        out.setdefault(q.lower(), {}).setdefault("flv", url)
    if su.get("hls_pull_url"):
        out.setdefault("default", {}).setdefault("hls", su.get("hls_pull_url"))
    ordered = sorted(out.items(), key=lambda kv: QUALITY_ORDER.index(kv[0]) if kv[0] in QUALITY_ORDER else 99)
    return dict(ordered)


def _room_summary(room_info: Optional[dict], unique_id: str) -> Dict[str, Any]:
    if not room_info:
        return {"unique_id": unique_id}
    owner = room_info.get("owner") or {}

    def first_url(obj: Any) -> Optional[str]:
        try:
            return ((obj or {}).get("url_list") or [None])[0]
        except Exception:
            return None

    return {
        "unique_id": owner.get("display_id") or unique_id,
        "nickname": owner.get("nickname") or unique_id,
        "avatar": first_url(owner.get("avatar_thumb")),
        "cover": first_url(room_info.get("cover")),
        "title": room_info.get("title") or "",
        "room_id": str(room_info.get("id_str") or room_info.get("id") or ""),
        "owner_id": str(owner.get("id_str") or owner.get("id") or ""),
        "create_time": room_info.get("create_time"),
    }


def parse_username(text: str) -> str:
    """Nhận '@user', 'user' hoặc link 'https://www.tiktok.com/@user/live'. Trả về username chữ thường."""
    text = (text or "").strip()
    m = re.search(r"@([A-Za-z0-9._]+)", text)
    name = m.group(1) if m else text.strip("/").split("/")[-1].lstrip("@")
    name = name.strip().lower()
    if not USERNAME_RE.match(name):
        raise ValueError(f"Username không hợp lệ: {text!r}")
    return name


def _fresh_stats() -> Dict[str, Any]:
    return {
        "viewers": 0,
        "viewers_peak": 0,
        "likes_total": 0,      # tổng tim của cả phiên live (TikTok báo)
        "likes": 0,            # tim nhận được từ lúc mình kết nối
        "diamonds": 0,
        "gifts": 0,
        "comments": 0,
        "joins": 0,
        "vip_joins": 0,       # "bay vào" (BarrageEvent: level cao / fan club vào phòng)
        "follows": 0,
        "shares": 0,
        "connected_at": None,
    }


# ----------------------------------------------------------------- một phòng live
class LiveSession:
    def __init__(self, hub: "LiveHub", unique_id: str, auto_reconnect: bool = True,
                 auto_record: bool = False) -> None:
        self.hub = hub
        self.unique_id = unique_id
        self.auto_reconnect = auto_reconnect
        self._lock = threading.RLock()

        self.client: Optional[TikTokLiveClient] = None
        self._runner: Optional[asyncio.Future] = None
        self._stop_requested = False
        self._log_fp = None
        self.using_session = False
        self._reset("idle")

    # -------------------------------------------------- state
    def _reset(self, status: str) -> None:
        with self._lock:
            self.status = status
            self.message = ""
            self.room: Dict[str, Any] = {"unique_id": self.unique_id}
            self.streams: Dict[str, Dict[str, Optional[str]]] = {}
            self.stats = _fresh_stats()
            self.top_gifters: Counter = Counter()
            self.top_commenters: Counter = Counter()
            self.live_rank: List[Dict[str, Any]] = []   # bảng xếp hạng hiện tại của TikTok (RoomUserSeq.ranks)
            self.user_cache: Dict[str, Dict[str, Any]] = {}
            self.user_stats: Dict[str, Dict[str, Any]] = {}   # thống kê từng người trong phiên này
            self.recent: deque = deque(maxlen=MAX_RECENT)
            self.samples: deque = deque(maxlen=MAX_SAMPLES)
            self._last = {"comments": 0, "likes": 0, "diamonds": 0, "joins": 0}

    def meta(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "unique_id": self.unique_id,
                "status": self.status,
                "message": self.message,
                "room": self.room,
                "qualities": list(self.streams.keys()),
                "auto_reconnect": self.auto_reconnect,
                "using_session": self.using_session,
            }

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                **self.meta(),
                "stats": dict(self.stats),
                "top_gifters": self._top(self.top_gifters),
                "live_rank": list(self.live_rank),
                "recent": list(self.recent),
                "samples": list(self.samples),
            }

    def _track_user(self, u: Dict[str, Any], ev: Dict[str, Any]) -> None:
        """Cộng dồn thống kê của 1 người trong phiên (gọi trong lock)."""
        uid = u["id"]
        st = self.user_stats.get(uid)
        if st is None:
            if len(self.user_stats) >= MAX_TRACKED_USERS:
                return
            st = self.user_stats[uid] = {"first": ev["ts"], "comments": 0, "diamonds": 0, "gifts": 0,
                                         "likes": 0, "joins": 0, "shares": 0, "followed": False,
                                         "recent": deque(maxlen=USER_RECENT)}
        st["last"] = ev["ts"]
        self.user_cache[uid] = u
        k = ev["kind"]
        if k == "comment":
            st["comments"] += 1
            st["recent"].append({"kind": k, "ts": ev["ts"], "text": ev.get("text", "")})
        elif k == "gift" and not ev.get("streaking"):
            st["gifts"] += ev.get("count", 1)
            st["diamonds"] += ev.get("diamonds", 0) * ev.get("count", 1)
            st["recent"].append({"kind": k, "ts": ev["ts"], "gift": ev.get("gift"), "count": ev.get("count"),
                                 "diamonds": ev.get("diamonds", 0), "gift_img": ev.get("gift_img")})
        elif k == "like":
            st["likes"] += ev.get("count", 0)
        elif k == "join":
            st["joins"] += 1
        elif k == "barrage":
            if ev.get("sub") in ("entrance", "fan_entrance", "enigma_entrance"):
                st["joins"] += 1
            st["recent"].append({"kind": k, "ts": ev["ts"], "sub": ev.get("sub"), "grade": ev.get("grade", 0)})
        elif k == "follow":
            st["followed"] = True
            st["recent"].append({"kind": k, "ts": ev["ts"]})
        elif k == "share":
            st["shares"] += 1
            st["recent"].append({"kind": k, "ts": ev["ts"]})

    def user_detail(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            st = self.user_stats.get(user_id)
            u = self.user_cache.get(user_id)
            if st is None and u is None:
                return None
            out = {"user": u, "stats": None, "rank_gift": None, "rank_comment": None}
            if st is not None:
                out["stats"] = {k: (list(v) if k == "recent" else v) for k, v in st.items()}
            for key, counter in (("rank_gift", self.top_gifters), ("rank_comment", self.top_commenters)):
                if user_id in counter:
                    out[key] = 1 + sum(1 for v in counter.values() if v > counter[user_id])
            return out

    def _top(self, counter: Counter, n: int = 15) -> List[Dict[str, Any]]:
        out = []
        for k, v in counter.most_common(n):
            u = {kk: vv for kk, vv in self.user_cache.get(k, {"id": k, "nickname": k}).items() if kk != "badges"}
            out.append({**u, "value": v})
        return out

    def stream_url(self, quality: str, kind: str = "flv") -> Optional[str]:
        with self._lock:
            q = self.streams.get(quality) or (next(iter(self.streams.values()), None))
            return (q or {}).get(kind)

    # -------------------------------------------------- broadcast
    def _publish(self, kind: str, data: Any) -> None:
        self.hub.publish(kind, self.unique_id, data)

    def _set_status(self, status: str, message: str = "") -> None:
        with self._lock:
            self.status = status
            self.message = message
        self._publish("status", self.meta())
        self._push("system", None, {"text": message or status})

    def _push(self, kind: str, user: Any, extra: Dict[str, Any]) -> Dict[str, Any]:
        u = user if isinstance(user, dict) or user is None else _user(user)
        ev = {"kind": kind, "ts": time.time(), "user": u, **extra}
        with self._lock:
            self.recent.append(ev)
            if u and u.get("id"):
                self._track_user(u, ev)
        self._publish("event", ev)
        if self._log_fp:
            try:
                self._log_fp.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
            except Exception:
                pass
        return ev

    # -------------------------------------------------- lifecycle (chạy trong loop)
    async def start(self) -> None:
        await self.stop(silent=True)
        self._reset("connecting")
        self._stop_requested = False
        os.makedirs(LOG_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_fp = open(os.path.join(LOG_DIR, f"{self.unique_id}_{stamp}.jsonl"), "a",
                            encoding="utf-8", buffering=1)
        self._set_status("connecting", f"Đang kết nối @{self.unique_id}…")
        self._runner = asyncio.ensure_future(self._run())

    async def stop(self, silent: bool = False) -> None:
        self._stop_requested = True
        client = self.client
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass
            try:
                await client.web.close()
            except Exception:
                pass
        if self._runner and not self._runner.done():
            self._runner.cancel()
            try:
                await self._runner
            except BaseException:
                pass
        self._runner = None
        self.client = None
        if not silent and self.status not in ("idle", "ended", "stopped"):
            self._set_status("stopped", "Đã ngắt kết nối")
        if self._log_fp:
            self._log_fp.close()
            self._log_fp = None

    async def _run(self) -> None:
        uid = self.unique_id
        attempts = 0
        cfg = session_config()
        # auto: chỉ dùng sessionid khi phòng giới hạn độ tuổi · always: luôn dùng · off: không dùng
        self.using_session = cfg["mode"] == "always" and cfg["configured"]
        while not self._stop_requested:
            client = TikTokLiveClient(unique_id=uid)
            if self.using_session:
                client.web.set_session(cfg["_sid"], cfg["_idc"] or None)
            self.client = client
            self._bind(client)
            try:
                task = await client.start(fetch_room_info=True)
                attempts = 0
                await task
            except asyncio.CancelledError:
                raise
            except UserOfflineError:
                self._set_status("offline", f"@{uid} hiện không live")
                return
            except UserNotFoundError:
                self._set_status("error", f"Không tìm thấy @{uid} (hoặc TikTok đang chặn/captcha)")
                return
            except AgeRestrictedError:
                if not self.using_session and cfg["mode"] != "off" and cfg["configured"]:
                    if cfg["problem"]:
                        self._set_status("error", f"Phiên live giới hạn độ tuổi – sessionid chưa dùng được: {cfg['problem']}")
                        return
                    self.using_session = True
                    self._push("system", None, {"text": "Phiên live giới hạn độ tuổi → thử lại bằng sessionid 🔐"})
                    try:
                        await client.web.close()
                    except Exception:
                        pass
                    continue
                if self.using_session:
                    self._set_status("error", "Vẫn bị giới hạn độ tuổi dù dùng sessionid – sessionid hết hạn, "
                                              "sai tt-target-idc, hoặc tài khoản chưa đủ 18 tuổi")
                elif cfg["mode"] == "off" and cfg["configured"]:
                    self._set_status("error", "Phiên live giới hạn độ tuổi – sessionid đang để chế độ Tắt (xem Cài đặt)")
                else:
                    self._set_status("error", "Phiên live giới hạn độ tuổi – cần nhập sessionid trong Cài đặt để xem")
                return
            except AuthenticatedWebSocketConnectionError:
                self._set_status("error", "TikTokLive chặn gửi sessionid: cần tick ô đồng ý trong Cài đặt")
                return
            except SignatureRateLimitError as ex:
                has_key = bool(os.environ.get("SIGN_API_KEY", "").strip())
                self.message = ("Máy chủ ký Euler Stream báo vượt giới hạn"
                                + (" của API key" if has_key else " (chưa có SIGN_API_KEY)")
                                + f": {str(ex)[:120]}")
                if not has_key:
                    self._set_status("error", self.message + " – nhập API key trong Cài đặt rồi Kết nối lại")
                    return
            except SignAPIError as ex:
                has_key = bool(os.environ.get("SIGN_API_KEY", "").strip())
                hint = ("Kiểm tra API key trong Cài đặt (sai hoặc hết hạn?)" if has_key
                        else "Thử nhập API key Euler Stream trong Cài đặt")
                self._set_status("error", f"Lỗi máy chủ ký (sign API): {str(ex)[:200]}. {hint}")
                return
            except ValueError as ex:  # vd. có sessionid nhưng thiếu tt-target-idc
                if self.using_session:
                    self._set_status("error", f"Cấu hình sessionid lỗi: {ex}")
                    return
                self.message = f"{type(ex).__name__}: {ex}"
            except Exception as ex:  # lỗi mạng, websocket…
                self.message = f"{type(ex).__name__}: {ex}"

            if self._stop_requested or self.status == "ended":
                return
            if not self.auto_reconnect or attempts >= 5:
                self._set_status("disconnected", self.message or "Mất kết nối")
                return
            attempts += 1
            wait = min(5 * attempts, 30)
            why = f" ({self.message[:160]})" if self.message and not self.message.startswith("Mất kết nối") else ""
            self._set_status("reconnecting", f"Mất kết nối{why} – thử lại lần {attempts}/5 sau {wait}s")
            try:
                await client.web.close()
            except Exception:
                pass
            await asyncio.sleep(wait)

    # -------------------------------------------------- event handlers
    def _bind(self, client: TikTokLiveClient) -> None:
        m = self

        @client.on(ConnectEvent)
        async def _on_connect(event: ConnectEvent):
            room_id = str(event.room_id)
            with m._lock:
                m.room = _room_summary(client.room_info, event.unique_id)
                m.room["room_id"] = room_id
                m.streams = extract_streams(client.room_info)
                if not m.stats["connected_at"]:
                    m.stats["connected_at"] = time.time()
                uc = (client.room_info or {}).get("user_count")
                if uc:
                    m.stats["viewers"] = int(uc)
                    m.stats["viewers_peak"] = max(m.stats["viewers_peak"], int(uc))
            status_message = (f"Đã vào phòng live của @{event.unique_id} id={room_id}"
                              + (" (đăng nhập bằng sessionid 🔐)" if m.using_session else ""))
            try:
                store.save_room_id(m.unique_id, room_id)
            except OSError:
                client.logger.exception("Không lưu được room_id TikTok cho @%s", m.unique_id)
                status_message += " (không lưu được room_id vào cấu hình)"
            m._set_status("connected", status_message)
        @client.on(LiveEndEvent)
        async def _on_end(_: LiveEndEvent):
            m._set_status("ended", "Phiên live đã kết thúc")

        @client.on(LivePauseEvent)
        async def _on_pause(_: LivePauseEvent):
            m._push("system", None, {"text": "Chủ phòng tạm dừng live"})

        @client.on(LiveUnpauseEvent)
        async def _on_unpause(_: LiveUnpauseEvent):
            m._push("system", None, {"text": "Live tiếp tục"})

        @client.on(CommentEvent)
        async def _on_comment(event: CommentEvent):
            u = _user(event.user)
            with m._lock:
                m.stats["comments"] += 1
                m.user_cache[u["id"]] = u
                m.top_commenters[u["id"]] += 1
            m._push("comment", u, {"text": event.comment})

        @client.on(GiftEvent)
        async def _on_gift(event: GiftEvent):
            gift = event.gift
            name = getattr(gift, "name", None) or f"Gift #{event.gift_id}"
            diamonds_each = int(getattr(gift, "diamond_count", 0) or 0)
            count = int(event.repeat_count or 1)
            streaking = bool(event.streaking)
            u = _user(event.user)
            if not streaking:
                with m._lock:
                    total = diamonds_each * count
                    m.stats["diamonds"] += total
                    m.stats["gifts"] += count
                    m.user_cache[u["id"]] = u
                    m.top_gifters[u["id"]] += total
            m._push("gift", u, {
                "gift": name,
                "gift_img": _img(getattr(gift, "image", None)) or _img(getattr(gift, "icon", None)),
                "count": count,
                "diamonds": diamonds_each,
                "streaking": streaking,
                "key": f"{u['id']}-{event.gift_id}-{event.group_id}",
            })

        @client.on(LikeEvent)
        async def _on_like(event: LikeEvent):
            with m._lock:
                m.stats["likes"] += int(event.count or 0)
                if event.total:
                    m.stats["likes_total"] = max(m.stats["likes_total"], int(event.total))
            m._push("like", event.user, {"count": int(event.count or 0)})

        @client.on(BarrageEvent)
        async def _on_barrage(event: BarrageEvent):
            """Thông báo nổi bật: người level cao / fan club 'bay vào' phòng, lên level, đăng ký thành viên…"""
            try:
                mt = int(getattr(event, "msg_type", 0) or 0)
            except (TypeError, ValueError):
                mt = 0
            sub = BARRAGE_KINDS.get(mt)
            if not sub:
                return
            ug = getattr(event, "user_grade_param", None)
            fl = getattr(event, "fans_level_param", None)
            u = None
            for cand in (getattr(event, "user", None), getattr(ug, "user", None), getattr(fl, "user", None)):
                if cand is not None and (getattr(cand, "id", 0) or getattr(cand, "display_id", "")):
                    u = cand
                    break
            if u is None:
                return
            grade = int(getattr(ug, "current_grade", 0) or 0) or int(getattr(fl, "current_grade", 0) or 0)
            if sub in ("entrance", "fan_entrance", "enigma_entrance"):
                with m._lock:
                    m.stats["vip_joins"] = m.stats.get("vip_joins", 0) + 1
            m._push("barrage", u, {"sub": sub, "grade": grade})

        @client.on(JoinEvent)
        async def _on_join(event: JoinEvent):
            with m._lock:
                m.stats["joins"] += 1
            m._push("join", event.user, {})

        @client.on(FollowEvent)
        async def _on_follow(event: FollowEvent):
            with m._lock:
                m.stats["follows"] += 1
            m._push("follow", event.user, {})

        @client.on(ShareEvent)
        async def _on_share(event: ShareEvent):
            with m._lock:
                m.stats["shares"] += 1
            m._push("share", event.user, {})

        @client.on(RoomUserSeqEvent)
        async def _on_viewers(event: RoomUserSeqEvent):
            total = int(event.total or 0)
            rank = []
            for c in (getattr(event, "ranks", None) or []):
                cu = getattr(c, "user", None)
                if cu is None:
                    continue
                u = _user(cu)
                if not u.get("id"):
                    continue
                u.pop("badges", None)   # gọn payload (level/fan vẫn giữ)
                rank.append({"rank": int(getattr(c, "rank", 0) or 0), "score": int(getattr(c, "score", 0) or 0),
                             "delta": int(getattr(c, "delta", 0) or 0), "user": u})
            rank.sort(key=lambda x: (x["rank"] or 999, -x["score"]))
            with m._lock:
                if total:
                    m.stats["viewers"] = total
                    m.stats["viewers_peak"] = max(m.stats["viewers_peak"], total)
                if rank:
                    m.live_rank = rank[:20]
                    for x in rank:
                        m.user_cache.setdefault(x["user"]["id"], x["user"])

    # -------------------------------------------------- sampler
    def tick(self, tick: int) -> None:
        with self._lock:
            stats = dict(self.stats)
            tops = {"top_gifters": self._top(self.top_gifters), "live_rank": list(self.live_rank)}
        self._publish("stats", {"stats": stats, **tops})
        if tick % SAMPLE_EVERY == 0:
            with self._lock:
                s = self.stats
                sample = {
                    "t": time.time(),
                    "viewers": s["viewers"],
                    "comments": s["comments"] - self._last["comments"],
                    "likes": s["likes"] - self._last["likes"],
                    "diamonds": s["diamonds"] - self._last["diamonds"],
                    "joins": s["joins"] - self._last["joins"],
                }
                self._last = {k: s[k] for k in self._last}
                self.samples.append(sample)
            self._publish("sample", sample)


# ----------------------------------------------------------------- hub (nhiều phòng)
class LiveHub:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subs: List[queue.Queue] = []
        self.sessions: Dict[str, LiveSession] = {}

        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self.loop.run_forever, name="tiktok-loop", daemon=True)
        self._thread.start()
        asyncio.run_coroutine_threadsafe(self._sampler(), self.loop)
        self._starting_all = False
        self._restore()

    # -------------------------------------------------- phòng đã lưu
    def _restore(self) -> None:
        """Nạp lại các phòng đã lưu (data/settings.json). Tự kết nối nếu bật 'autostart'."""
        cfg = store.get()
        for r in cfg["rooms"][:MAX_ROOMS]:
            try:
                uid = parse_username(r.get("unique_id", ""))
            except ValueError:
                continue
            self.sessions[uid] = LiveSession(self, uid, bool(r.get("auto_reconnect", True)))
        if cfg.get("autostart") and self.sessions:
            self.start_all()

    # -------------------------------------------------- broadcast
    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=5000)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def publish(self, kind: str, room: Optional[str], data: Any) -> None:
        msg = json.dumps({"type": kind, "room": room, "data": data}, ensure_ascii=False, default=str)
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass

    # -------------------------------------------------- helpers
    def _call(self, coro, timeout: float = 30):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=timeout)

    def _get(self, uid: str) -> LiveSession:
        with self._lock:
            s = self.sessions.get((uid or "").lower())
        if s is None:
            raise KeyError(f"Không có phòng @{uid}")
        return s

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            sessions = list(self.sessions.values())
        return {"rooms": [s.snapshot() for s in sessions],
                "autostart": bool(store.get().get("autostart")), "starting_all": self._starting_all,
                "max_rooms": MAX_ROOMS, "session": session_public(), "sign": sign_public()}

    def stream_url(self, uid: str, quality: str) -> Optional[str]:
        with self._lock:
            s = self.sessions.get((uid or "").lower())
        return s.stream_url(quality) if s else None

    # -------------------------------------------------- public API (gọi từ Flask thread)
    def add(self, text: str, auto_reconnect: bool = True) -> str:
        uid = parse_username(text)
        uid = self._call(self._add(uid, auto_reconnect))
        store.save_room(uid, auto_reconnect, False)
        return uid

    def remove(self, uid: str) -> None:
        s = self._get(uid)
        self._call(self._remove(s))
        store.forget_room(s.unique_id)

    def start_all(self) -> int:
        """Kết nối mọi phòng chưa chạy, lần lượt cách nhau vài giây (tránh bị máy chủ ký giới hạn)."""
        with self._lock:
            todo = [s for s in self.sessions.values() if s.status not in ACTIVE]
        if todo and not self._starting_all:
            self._starting_all = True
            asyncio.run_coroutine_threadsafe(self._start_many(todo), self.loop)
        return len(todo)

    def stop_all(self) -> int:
        with self._lock:
            todo = [s for s in self.sessions.values() if s.status in ACTIVE]
        if todo:
            self._call(self._stop_many(todo), 60)
        return len(todo)

    async def _stop_many(self, todo: List["LiveSession"], silent: bool = False) -> None:
        await asyncio.gather(*(s.stop(silent=silent) for s in todo), return_exceptions=True)

    async def _start_many(self, todo: List["LiveSession"]) -> None:
        try:
            for i, s in enumerate(todo):
                if s.unique_id not in self.sessions or s.status in ACTIVE:
                    continue
                if i:
                    await asyncio.sleep(START_STAGGER)
                try:
                    await s.start()
                except Exception:
                    pass
        finally:
            self._starting_all = False

    def reconnect(self, uid: str) -> None:
        self._call(self._get(uid).start())

    def disconnect(self, uid: str) -> None:
        self._call(self._get(uid).stop())

    def user_detail(self, uid: str, user_id: str) -> Optional[Dict[str, Any]]:
        return self._get(uid).user_detail(user_id)

    def room_ids(self, uid: str) -> Dict[str, str]:
        """room_id + owner_id của phiên đang xem (cần cho quản trị phòng)."""
        r = self._get(uid).room or {}
        return {"room_id": str(r.get("room_id") or ""), "owner_id": str(r.get("owner_id") or "")}

    def shutdown(self) -> None:
        """Ngắt hết phòng gọn gàng (gọi khi tắt app)."""
        with self._lock:
            sessions = list(self.sessions.values())
        if not sessions:
            return
        try:
            self._call(self._stop_many(sessions, silent=True), 30)
        except Exception:
            pass

    # -------------------------------------------------- loop side
    async def _add(self, uid: str, auto_reconnect: bool) -> str:
        with self._lock:
            s = self.sessions.get(uid)
            if s is None:
                if len(self.sessions) >= MAX_ROOMS:
                    raise RuntimeError(f"Tối đa {MAX_ROOMS} phòng cùng lúc (đổi bằng biến MAX_ROOMS)")
                s = LiveSession(self, uid, auto_reconnect)
                self.sessions[uid] = s
                created = True
            else:
                s.auto_reconnect = auto_reconnect
                created = False
        if created:
            self.publish("added", uid, s.snapshot())
        elif s.status in ACTIVE:
            self.publish("status", uid, s.meta())
            return uid
        await s.start()
        return uid

    async def _remove(self, s: LiveSession) -> None:
        await s.stop(silent=True)
        with self._lock:
            self.sessions.pop(s.unique_id, None)
        self.publish("removed", s.unique_id, None)

    async def _sampler(self) -> None:
        tick = 0
        while True:
            await asyncio.sleep(1)
            tick += 1
            with self._lock:
                sessions = list(self.sessions.values())
            for s in sessions:
                try:
                    if s.status in ("connected", "reconnecting"):
                        s.tick(tick)
                except Exception:
                    pass
