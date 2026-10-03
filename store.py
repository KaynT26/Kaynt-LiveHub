"""
Lưu cấu hình nhập từ giao diện vào data/settings.json (chỉ nằm trên máy này, đã có trong .gitignore):
  - danh sách phòng đã thêm (để mở lại app là tự kết nối)
  - sessionid / tt-target-idc / chế độ dùng / đồng ý gửi tới máy chủ ký
  - API key Euler Stream, mật khẩu truy cập qua WiFi
  - tự kết nối khi mở app

Giá trị nhập trên giao diện được ưu tiên hơn file .env; ô nào để trống thì dùng .env.
"""
from __future__ import annotations

import copy
import json
import os
import threading
from typing import Any, Callable, Dict, List

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PATH = os.path.join(DATA_DIR, "settings.json")
SIGN_HOST = "api.eulerstream.com"

DEFAULTS: Dict[str, Any] = {
    "version": 1,
    "autostart": True,          # mở app là tự kết nối các phòng đã lưu
    "rooms": [],                # [{"unique_id", "auto_reconnect", "auto_record", "room_id"}]
    "session": {"sessionid": "", "target_idc": "", "mode": "auto", "consent": False},
    "sign_api_key": "",
    "access_password": "",
}

_lock = threading.RLock()
_data: Dict[str, Any] = {}


def _merge(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> Dict[str, Any]:
    global _data
    with _lock:
        raw: Dict[str, Any] = {}
        try:
            with open(PATH, encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError:
            pass
        except Exception:
            # file hỏng: giữ bản sao để không mất dữ liệu, dùng mặc định
            try:
                os.replace(PATH, PATH + ".broken")
            except Exception:
                pass
        _data = _merge(DEFAULTS, raw)
        return copy.deepcopy(_data)


def get() -> Dict[str, Any]:
    with _lock:
        if not _data:
            load()
        return copy.deepcopy(_data)


def update(fn: Callable[[Dict[str, Any]], None]) -> Dict[str, Any]:
    """Sửa cấu hình trong lock rồi ghi file (ghi file tạm rồi đổi tên để không hỏng file khi mất điện)."""
    with _lock:
        if not _data:
            load()
        fn(_data)
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PATH)
        return copy.deepcopy(_data)


# ----------------------------------------------------------------- phòng
def rooms() -> List[Dict[str, Any]]:
    return get()["rooms"]


def save_room(uid: str, auto_reconnect: bool, auto_record: bool) -> None:
    def fn(d: Dict[str, Any]) -> None:
        for r in d["rooms"]:
            if r["unique_id"] == uid:
                r.update(auto_reconnect=auto_reconnect, auto_record=auto_record)
                return
        d["rooms"].append({"unique_id": uid, "auto_reconnect": auto_reconnect, "auto_record": auto_record})
    update(fn)


def save_room_id(uid: str, room_id: str | int) -> None:
    """Persist TikTok's authoritative room ID after a successful connection."""
    resolved_room_id = str(room_id).strip()
    if not resolved_room_id.isdigit():
        raise ValueError("TikTok room_id must contain digits only")

    def fn(d: Dict[str, Any]) -> None:
        for room in d["rooms"]:
            if str(room.get("unique_id", "")).lower() == uid.lower():
                room["room_id"] = resolved_room_id
                return
        d["rooms"].append({
            "unique_id": uid,
            "auto_reconnect": True,
            "auto_record": False,
            "room_id": resolved_room_id,
        })

    update(fn)


def forget_room(uid: str) -> None:
    update(lambda d: d.__setitem__("rooms", [r for r in d["rooms"] if r["unique_id"] != uid]))


# ----------------------------------------------------------------- giá trị hiệu lực (giao diện > .env)
# Giá trị gốc từ .env (chụp lại lần đầu) để khi xoá ô trên giao diện thì quay về .env
_ENV_KEYS = ("TIKTOK_SESSIONID", "TIKTOK_TARGET_IDC", "TIKTOK_SESSION_MODE",
             "WHITELIST_AUTHENTICATED_SESSION_ID_HOST", "SIGN_API_KEY", "ACCESS_PASSWORD")
_env_orig: Dict[str, str] = {}


def snapshot_env() -> None:
    """Gọi sau khi load_dotenv (lúc khởi động hoặc khi đọc lại .env)."""
    _env_orig.clear()
    for k in _ENV_KEYS:
        _env_orig[k] = os.environ.get(k, "").strip()


def _env(k: str) -> str:
    if not _env_orig:
        snapshot_env()
    return _env_orig.get(k, "")


def effective_session() -> Dict[str, Any]:
    s = get()["session"]
    ui_sid = (s.get("sessionid") or "").strip()
    sid = ui_sid or _env("TIKTOK_SESSIONID")
    idc = (s.get("target_idc") or "").strip() or _env("TIKTOK_TARGET_IDC")
    mode = (s.get("mode") if ui_sid else (_env("TIKTOK_SESSION_MODE") or s.get("mode"))) or "auto"
    consent = bool(s.get("consent")) or _env("WHITELIST_AUTHENTICATED_SESSION_ID_HOST") == SIGN_HOST
    return {"sid": sid, "idc": idc, "mode": str(mode).strip().lower(), "consent": consent, "from_ui": bool(ui_sid)}


def effective_sign_key() -> str:
    return (get().get("sign_api_key") or "").strip() or _env("SIGN_API_KEY")


def effective_password() -> str:
    return (get().get("access_password") or "").strip() or _env("ACCESS_PASSWORD")


def _set_env(k: str, v: str) -> None:
    if v:
        os.environ[k] = v
    else:
        os.environ.pop(k, None)


def apply_env() -> None:
    """TikTokLive đọc SIGN_API_KEY và WHITELIST_... từ biến môi trường -> đồng bộ theo cấu hình hiện tại."""
    _set_env("SIGN_API_KEY", effective_sign_key())
    _set_env("WHITELIST_AUTHENTICATED_SESSION_ID_HOST", SIGN_HOST if effective_session()["consent"] else "")


# ----------------------------------------------------------------- dùng chung cho app.py và cửa sổ launcher
def mask(v: str) -> str:
    v = v or ""
    return (v[:4] + "…" + v[-4:]) if len(v) > 10 else ("***" if v else "")


def apply_patch(b: Dict[str, Any]) -> Dict[str, Any]:
    """Lưu thay đổi cài đặt. Ô bí mật để trống = giữ nguyên; muốn xoá thì gửi clear_*."""
    def fn(d: Dict[str, Any]) -> None:
        if "autostart" in b:
            d["autostart"] = bool(b["autostart"])
        sess = b.get("session") or {}
        ds = d["session"]
        if sess.get("clear_sessionid"):
            ds["sessionid"] = ""
        elif (sess.get("sessionid") or "").strip():
            ds["sessionid"] = sess["sessionid"].strip().strip('"').strip("'")
        if "target_idc" in sess:
            ds["target_idc"] = str(sess.get("target_idc") or "").strip()
        if sess.get("mode") in ("auto", "always", "off"):
            ds["mode"] = sess["mode"]
        if "consent" in sess:
            ds["consent"] = bool(sess["consent"])
        if b.get("clear_sign_api_key"):
            d["sign_api_key"] = ""
        elif (b.get("sign_api_key") or "").strip():
            d["sign_api_key"] = b["sign_api_key"].strip()
        if b.get("clear_access_password"):
            d["access_password"] = ""
        elif (b.get("access_password") or "").strip():
            d["access_password"] = b["access_password"].strip()
    return update(fn)


def public_view() -> Dict[str, Any]:
    """Cài đặt đã che bí mật (để hiển thị)."""
    d = get()
    s = d["session"]
    e = effective_session()
    problem = ""
    if e["sid"] and not e["idc"]:
        problem = "Thiếu tt-target-idc"
    elif e["sid"] and not e["consent"]:
        problem = "Chưa tick đồng ý gửi sessionid tới máy chủ ký"
    key = effective_sign_key()
    pw = effective_password()
    return {
        "autostart": bool(d.get("autostart")),
        "rooms": d["rooms"],
        "session": {"configured": bool(e["sid"]), "masked": mask(e["sid"]), "ui_set": bool((s.get("sessionid") or "").strip()),
                    "target_idc": e["idc"], "mode": s.get("mode") or "auto", "consent": bool(s.get("consent")),
                    "problem": problem, "source": "ui" if e["from_ui"] else ("env" if e["sid"] else "")},
        "sign": {"configured": bool(key), "masked": mask(key), "ui_set": bool((d.get("sign_api_key") or "").strip())},
        "access_password": {"set": bool(pw), "ui_set": bool((d.get("access_password") or "").strip())},
    }
