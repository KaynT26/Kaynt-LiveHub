"""
Kaynt - Live Observer
Web app (Flask) để theo dõi NHIỀU phiên TikTok LIVE cùng lúc theo thời gian thực.

Chạy:  python app.py   rồi mở http://127.0.0.1:5000
"""
from __future__ import annotations

import atexit
import hmac
import logging
import os
import queue
import socket
import threading
import time

import httpx
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from flask_sock import Sock

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE_DIR, ".env")
RELOADABLE_KEYS = ("TIKTOK_SESSIONID", "TIKTOK_TARGET_IDC", "TIKTOK_SESSION_MODE",
                   "WHITELIST_AUTHENTICATED_SESSION_ID_HOST", "SIGN_API_KEY", "SIGN_API_URL",
                   "ACCESS_PASSWORD")
load_dotenv(ENV_FILE)  # đọc .env trước khi import live_manager (MAX_ROOMS, SIGN_API_KEY, sessionid…)

import store  # noqa: E402

store.load()
store.snapshot_env()
store.apply_env()   # cấu hình nhập trên giao diện (data/settings.json) được ưu tiên hơn .env

import moderation  # noqa: E402
from live_manager import VIDEO_HEADERS, LiveHub, _mask, session_public, sign_public  # noqa: E402

logging.getLogger("werkzeug").setLevel(logging.WARNING)  # bỏ log từng request cho đỡ rối
app = Flask(__name__)
sock = Sock(app)
hub = LiveHub()
atexit.register(hub.shutdown)

HOST = os.environ.get("HOST", "0.0.0.0").strip() or "0.0.0.0"
PORT = int(os.environ.get("PORT", "5000"))
LOCAL_ADDRS = {"127.0.0.1", "::1", "localhost"}


def lan_ips() -> list:
    """Các địa chỉ IP trong mạng WiFi/LAN của máy này."""
    ips = []
    try:  # IP của card mạng đang ra internet (không gửi gói tin nào thật)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    return [ip for ip in ips if not ip.startswith("127.") and not ip.startswith("169.254.")]


def lan_urls() -> list:
    if HOST in LOCAL_ADDRS:
        return []
    return [f"http://{ip}:{PORT}" for ip in lan_ips()]


def _password() -> str:
    return store.effective_password()


def _is_local() -> bool:
    return request.remote_addr in LOCAL_ADDRS


@app.before_request
def require_password():
    """Máy khác trong WiFi phải nhập mật khẩu (nếu đặt ACCESS_PASSWORD). Chính máy này thì không cần."""
    pw = _password()
    if not pw or request.remote_addr in LOCAL_ADDRS:
        return None
    auth = request.authorization
    given = (auth.password if auth else "") or ""
    if hmac.compare_digest(given.encode(), pw.encode()):
        return None
    return Response("Cần mật khẩu để truy cập Kaynt Live Observer", 401,
                    {"WWW-Authenticate": 'Basic realm="Kaynt Live Observer", charset="UTF-8"'})


def _err(ex: Exception, code: int = 400):
    msg = ex.args[0] if isinstance(ex, KeyError) and ex.args else str(ex)
    return jsonify({"ok": False, "error": msg or type(ex).__name__}), (404 if isinstance(ex, KeyError) else code)


def _body() -> dict:
    return request.get_json(silent=True) or {}


def _choice(b: dict) -> str:
    c = str(b.get("choice") or "auto").lower()
    return c if c in ("auto", "resume", "new") else "auto"


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def api_state():
    return jsonify({**hub.snapshot(),
                    "lan": {"urls": lan_urls(), "password": bool(_password()),
                            "is_local": request.remote_addr in LOCAL_ADDRS}})


@app.post("/api/rooms")
def api_add_room():
    b = _body()
    try:
        res = hub.add(b.get("unique_id", ""), bool(b.get("auto_reconnect", True)), _choice(b))
    except Exception as ex:
        return _err(ex)
    return jsonify({"ok": True, **res})


@app.delete("/api/rooms/<uid>")
def api_remove_room(uid: str):
    try:
        hub.remove(uid)
    except Exception as ex:
        return _err(ex)
    return jsonify({"ok": True})


@app.post("/api/rooms/<uid>/reconnect")
def api_reconnect(uid: str):
    try:
        res = hub.reconnect(uid, _choice(_body()))
    except Exception as ex:
        return _err(ex)
    return jsonify({"ok": True, **res})


@app.get("/api/rooms/<uid>/snapshot")
def api_room_snapshot(uid: str):
    """Toàn bộ dữ liệu hiện tại của 1 phòng (dùng khi phòng vừa nối tiếp phiên cũ)."""
    try:
        return jsonify({"ok": True, **hub.room_snapshot(uid)})
    except Exception as ex:
        return _err(ex)


@app.post("/api/rooms/<uid>/disconnect")
def api_disconnect(uid: str):
    try:
        hub.disconnect(uid)
    except Exception as ex:
        return _err(ex)
    return jsonify({"ok": True})


@app.get("/api/rooms/<uid>/users/<user_id>")
def api_user_detail(uid: str, user_id: str):
    """Thông tin 1 người xem trong phiên hiện tại của phòng (level, badge, thống kê, hoạt động gần đây)."""
    try:
        d = hub.user_detail(uid, user_id)
    except Exception as ex:
        return _err(ex)
    if d is None:
        return jsonify({"ok": False, "error": "Chưa có dữ liệu người này trong phiên"}), 404
    return jsonify({"ok": True, **d})


# ---------------------------------------------------------------- chặn user
def _block_allowed() -> bool:
    """Chỉ máy này, hoặc máy trong WiFi khi đã đặt mật khẩu truy cập, mới được chặn user."""
    return _is_local() or bool(_password())


@app.post("/api/rooms/<uid>/block-user")
def api_block_user(uid: str):
    if not _block_allowed():
        return jsonify({"ok": False, "error": "Chỉ máy chạy app (hoặc máy WiFi khi đã đặt mật khẩu) được quản trị phòng"}), 403
    user_id = str(_body().get("user_id") or "").strip()
    if not user_id.isdigit():
        return jsonify({"ok": False, "error": "Thiếu user_id"}), 400
    try:
        room_id = hub.room_ids(uid)["room_id"]
        if not room_id:
            raise moderation.ModError("Phòng chưa kết nối – chưa có room_id")
        hub._call(moderation.block_user(room_id, user_id), 30)
    except Exception as ex:
        app.logger.warning("Không thể chặn user %s trong phòng @%s: %s", user_id, uid, ex)
        return _err(ex)
    return jsonify({"ok": True})


@app.post("/api/config/reload")
@app.post("/api/session/reload")
def api_config_reload():
    """Đọc lại sessionid + SIGN_API_KEY trong .env (không cần khởi động lại app).
    Áp dụng cho các lần kết nối sau – phòng đang xem thì bấm "Kết nối lại"."""
    for k in RELOADABLE_KEYS:
        os.environ.pop(k, None)
    load_dotenv(ENV_FILE, override=True)
    store.snapshot_env()
    store.apply_env()
    info = {"session": session_public(), "sign": sign_public()}
    hub.publish("config", None, info)
    return jsonify({"ok": True, **info})


# ----------------------------------------------------------------- Bắt đầu / Dừng tất cả
@app.post("/api/start_all")
def api_start_all():
    n = hub.start_all()
    return jsonify({"ok": True, "count": n})


@app.post("/api/stop_all")
def api_stop_all():
    try:
        n = hub.stop_all()
    except Exception as ex:
        return _err(ex)
    return jsonify({"ok": True, "count": n})


# ----------------------------------------------------------------- cài đặt (nhập từ giao diện)
def _settings_public() -> dict:
    cfg = store.get()
    s = cfg["session"]
    sess = session_public()
    return {
        "autostart": bool(cfg.get("autostart")),
        "session": {
            **sess,
            "target_idc": (s.get("target_idc") or "").strip() or ("" if sess.get("source") == "ui" else os.environ.get("TIKTOK_TARGET_IDC", "")),
            "mode_ui": s.get("mode") or "auto",
            "consent": bool(s.get("consent")),
            "ui_set": bool((s.get("sessionid") or "").strip()),
        },
        "sign": {**sign_public(), "ui_set": bool((cfg.get("sign_api_key") or "").strip())},
        "access_password": {"set": bool(_password()), "ui_set": bool((cfg.get("access_password") or "").strip()),
                            "masked": "••••••" if _password() else ""},
        "rooms_saved": len(cfg["rooms"]),
    }


@app.get("/api/settings")
def api_settings_get():
    return jsonify({"ok": True, **_settings_public(), "can_edit": _is_local() or bool(_password())})


@app.post("/api/settings")
def api_settings_post():
    """Lưu cài đặt – chỉ cửa sổ Kaynt LiveHub (chạy trên chính máy này) được gọi."""
    if not _is_local():
        return jsonify({"ok": False, "error": "Cài đặt chỉ sửa được trong cửa sổ Kaynt LiveHub trên máy chạy app"}), 403
    store.apply_patch(_body())
    store.apply_env()
    info = _settings_public()
    hub.publish("config", None, {"session": info["session"], "sign": info["sign"],
                                 "lan_password": info["access_password"]["set"], "autostart": info["autostart"]})
    return jsonify({"ok": True, **info, "can_edit": True})


@app.get("/api/rooms")
def api_rooms_list():
    """Danh sách phòng gọn (cho cửa sổ Kaynt LiveHub)."""
    with hub._lock:
        sessions = list(hub.sessions.values())
    return jsonify({"ok": True, "rooms": [{"unique_id": s.unique_id, "status": s.status, "message": s.message,
                                           "room_id": (s.room or {}).get("room_id", ""),
                                           "auto_reconnect": s.auto_reconnect,
                                           "nickname": (s.room or {}).get("nickname"),
                                           "viewers": s.stats.get("viewers", 0)} for s in sessions]})


@app.post("/api/shutdown")
def api_shutdown():
    """Tắt app gọn gàng (ngắt các phòng). Chỉ gọi được từ chính máy này (cửa sổ app dùng)."""
    if not _is_local():
        return jsonify({"ok": False, "error": "Chỉ tắt được từ máy chạy app"}), 403

    def bye():
        time.sleep(0.3)
        try:
            hub.shutdown()
        finally:
            os._exit(0)

    threading.Thread(target=bye, daemon=True).start()
    return jsonify({"ok": True})


@app.get("/api/ping")
def api_ping():
    return jsonify({"ok": True, "rooms": len(hub.sessions), "autostart": bool(store.get().get("autostart"))})


@app.get("/api/events")
def api_events():
    """Server-Sent Events: đẩy sự kiện của mọi phòng xuống trình duyệt."""
    q = hub.subscribe()

    def gen():
        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    msg = q.get(timeout=15)
                    yield f"data: {msg}\n\n"
                except queue.Empty:
                    yield ": ping\n\n"
        finally:
            hub.unsubscribe(q)

    return Response(stream_with_context(gen()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/video/<uid>/<quality>.flv")
def video_proxy(uid: str, quality: str):
    """Chuyển tiếp luồng FLV từ CDN TikTok về trình duyệt (tránh lỗi CORS/Referer). Không lưu gì."""
    url = hub.stream_url(uid, quality)
    if not url:
        return "Không có luồng video", 404

    client = httpx.Client(headers=VIDEO_HEADERS, timeout=httpx.Timeout(15, read=30), follow_redirects=True)
    try:
        r = client.send(client.build_request("GET", url), stream=True)
    except Exception as ex:
        client.close()
        return f"Không mở được luồng: {ex}", 502
    if r.status_code != 200:
        r.close()
        client.close()
        return f"CDN trả về {r.status_code}", 502

    def gen():
        try:
            for chunk in r.iter_bytes(64 * 1024):
                yield chunk
        finally:
            r.close()
            client.close()

    return Response(stream_with_context(gen()), mimetype="video/x-flv",
                    headers={"Cache-Control": "no-cache"})


@sock.route("/ws/video/<uid>/<quality>")
def video_ws(ws, uid: str, quality: str):
    """Video qua WebSocket: trình duyệt chỉ cho 6 kết nối HTTP / địa chỉ, WebSocket thì không bị giới hạn này
    -> mở được video cho nhiều phòng cùng lúc trong lưới."""
    url = hub.stream_url(uid, quality)
    if not url:
        ws.close(reason=1008, message="Không có luồng video")
        return
    try:
        with httpx.Client(headers=VIDEO_HEADERS, timeout=httpx.Timeout(15, read=30), follow_redirects=True) as c:
            with c.stream("GET", url) as r:
                if r.status_code != 200:
                    ws.close(reason=1011, message=f"CDN trả về {r.status_code}")
                    return
                for chunk in r.iter_bytes(64 * 1024):
                    ws.send(chunk)   # trình duyệt đóng -> ném lỗi -> thoát, đóng kết nối CDN
    except Exception:
        pass


if __name__ == "__main__":
    print("\n  Kaynt Live Observer")
    print(f"  • Trên máy này : http://127.0.0.1:{PORT}")
    urls = lan_urls()
    for u in urls:
        print(f"  • Qua WiFi/LAN : {u}")
    if HOST not in LOCAL_ADDRS and not urls:
        print("  • Qua WiFi/LAN : (không tìm thấy IP mạng – máy đã kết nối WiFi chưa?)")
    if HOST not in LOCAL_ADDRS:
        if _password():
            print("  • Máy khác cần nhập mật khẩu truy cập – tên đăng nhập gõ gì cũng được")
        else:
            print("  ⚠ CHƯA ĐẶT MẬT KHẨU TRUY CẬP: ai cùng WiFi cũng xem & điều khiển được app! (đặt trong Cài đặt)")
            if store.effective_session()["sid"]:
                print("  ⚠ Đang cấu hình sessionid – RẤT NÊN đặt mật khẩu truy cập trong Cài đặt")
        print("  • Máy khác không vào được? Bấm \"Mở tường lửa cho WiFi\" trong cửa sổ Kaynt LiveHub")
    saved = len(store.get()["rooms"])
    if saved:
        print(f"  • Đã nạp {saved} phòng đã lưu" + (" – đang tự kết nối…" if store.get().get("autostart") else ""))
    print(flush=True)
    try:
        app.run(host=HOST, port=PORT, threaded=True, debug=False, use_reloader=False)
    finally:
        hub.shutdown()
