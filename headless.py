#!/usr/bin/env python3
"""
Kaynt LiveHub – chạy KHÔNG giao diện (Linux server / VPS / Raspberry Pi…).

Chạy là tự bật server web + tự kết nối mọi phòng đã lưu, không cần bấm "Bắt đầu".
Tắt bằng Ctrl+C hoặc `kill` / `systemctl stop` (ngắt các phòng gọn gàng).

Cài thư viện (1 lần, không cần PySide6):
  pip install "TikTokLive==7.0.1" "Flask>=3.0" "flask-sock>=0.7" "httpx>=0.27" "python-dotenv>=1.0"

Ví dụ:
  python3 headless.py                                # dùng phòng đã lưu trong data/settings.json
  python3 headless.py --room fm.psycho,eclipse.fm2   # thêm phòng (được lưu lại cho lần sau)
  python3 headless.py --port 8080 --host 127.0.0.1
  python3 headless.py --list                         # xem phòng đã lưu rồi thoát
  python3 headless.py --remove fm.spacex             # xoá phòng khỏi danh sách rồi thoát

Cấu hình (sessionid, SIGN_API_KEY, ACCESS_PASSWORD, MAX_ROOMS…) lấy từ .env và data/settings.json
giống bản Windows.
"""
from __future__ import annotations

import argparse
import os
import re
import signal
import sys
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
sys.path.insert(0, BASE)
for _s in (sys.stdout, sys.stderr):   # in log ngay (systemd / chuyển hướng ra file), giữ được tiếng Việt
    try:
        _s.reconfigure(encoding="utf-8", line_buffering=True)
    except Exception:
        pass

PIP_HINT = ('pip install "TikTokLive==7.0.1" "Flask>=3.0" "flask-sock>=0.7" "httpx>=0.27" "python-dotenv>=1.0"')

USERNAME_RE = re.compile(r"@([A-Za-z0-9._]+)")


def parse_username(text: str) -> str:
    text = (text or "").strip()
    m = USERNAME_RE.search(text)
    name = (m.group(1) if m else text.strip("/").split("/")[-1].lstrip("@")).strip().lower()
    if not re.fullmatch(r"[a-z0-9._]{1,64}", name):
        raise ValueError(f"Username không hợp lệ: {text}")
    return name


def split_rooms(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for v in values or []:
        for part in re.split(r"[\s,;]+", v):
            if part.strip():
                uid = parse_username(part)
                if uid not in out:
                    out.append(uid)
    return out


def log(msg: str) -> None:
    print(time.strftime("[%Y-%m-%d %H:%M:%S] ") + msg, flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Kaynt LiveHub – chạy không giao diện, tự kết nối phòng đã lưu.")
    ap.add_argument("--room", "-r", action="append", metavar="USER",
                    help="thêm phòng (@username hoặc link live, nhiều phòng cách nhau bằng dấu phẩy). Được lưu lại.")
    ap.add_argument("--remove", action="append", metavar="USER", help="xoá phòng khỏi danh sách đã lưu rồi thoát")
    ap.add_argument("--list", action="store_true", help="in danh sách phòng đã lưu rồi thoát")
    ap.add_argument("--host", help="địa chỉ lắng nghe (mặc định HOST trong .env hoặc 0.0.0.0)")
    ap.add_argument("--port", "-p", type=int, help="cổng web (mặc định PORT trong .env hoặc 5000)")
    ap.add_argument("--no-connect", action="store_true",
                    help="chỉ bật server, KHÔNG tự kết nối phòng (kết nối sau trên web)")
    ap.add_argument("--status-every", type=int, default=300, metavar="GIÂY",
                    help="in tình trạng các phòng mỗi N giây (0 = tắt, mặc định 300)")
    args = ap.parse_args()

    # Giá trị dòng lệnh ưu tiên hơn .env (load_dotenv không ghi đè biến đã có)
    if args.host:
        os.environ["HOST"] = args.host
    if args.port:
        os.environ["PORT"] = str(args.port)
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(BASE, ".env"))
    except Exception:
        pass

    import store
    store.load()

    try:
        add = split_rooms(args.room)
        remove = split_rooms(args.remove)
    except ValueError as ex:
        sys.exit(f"Lỗi: {ex}")

    saved = {r["unique_id"] for r in store.get()["rooms"]}
    for uid in add:
        if uid not in saved:
            store.save_room(uid, True, False)
            log(f"Đã lưu phòng mới @{uid}")
    for uid in remove:
        store.forget_room(uid)
        log(f"Đã xoá @{uid}")
    if args.list:
        rooms = store.get()["rooms"]
        print(f"{len(rooms)} phòng đã lưu:" if rooms else "Chưa có phòng nào. Thêm bằng: --room @username")
        for r in rooms:
            print(f"  @{r['unique_id']}" + (f"  (room_id {r['room_id']})" if r.get("room_id") else ""))
    if remove or args.list:
        return

    # Kill / systemctl stop (SIGTERM) và đóng terminal (SIGHUP) -> thoát như Ctrl+C để ngắt phòng gọn gàng
    def _stop(signum, _frame):
        raise KeyboardInterrupt
    for sig in ("SIGTERM", "SIGHUP"):
        if hasattr(signal, sig):
            signal.signal(getattr(signal, sig), _stop)

    if sys.version_info < (3, 11):
        sys.exit(f"Cần Python 3.11 trở lên (đang dùng {sys.version.split()[0]}).")
    log("Đang khởi động Kaynt LiveHub (không giao diện)…")
    try:
        import app as web   # tạo LiveHub, nạp phòng đã lưu (tự kết nối nếu autostart bật trong cài đặt)
    except ModuleNotFoundError as ex:
        sys.exit(f"Thiếu thư viện '{ex.name}'. Cài bằng lệnh:\n  {PIP_HINT}")
    hub = web.hub

    n = len(hub.sessions)
    if args.no_connect:
        log(f"{n} phòng đã lưu – không tự kết nối (--no-connect).")
    elif n:
        hub.start_all()   # luôn kết nối, kể cả khi autostart đang tắt trong cài đặt
        log(f"Đang kết nối {n} phòng: " + ", ".join("@" + u for u in hub.sessions))
    else:
        log("Chưa có phòng nào. Thêm bằng --room @username hoặc trên giao diện web.")

    print(f"\n  • Trên máy này : http://127.0.0.1:{web.PORT}")
    for u in web.lan_urls():
        print(f"  • Qua mạng LAN : {u}")
    if web.HOST not in web.LOCAL_ADDRS and not web._password():
        print("  ⚠ CHƯA ĐẶT MẬT KHẨU TRUY CẬP: ai vào được cổng này cũng xem & điều khiển được app!"
              "\n    Đặt ACCESS_PASSWORD trong .env, hoặc chạy với --host 127.0.0.1")
    print("  • Dừng: Ctrl+C\n", flush=True)

    if args.status_every > 0:
        def report() -> None:
            while True:
                time.sleep(args.status_every)
                with hub._lock:
                    sessions = list(hub.sessions.values())
                parts = []
                for s in sessions:
                    v = s.stats.get("viewers", 0)
                    parts.append(f"@{s.unique_id}={s.status}" + (f"({v})" if s.status == "connected" and v else ""))
                log("Tình trạng: " + (", ".join(parts) or "không có phòng"))
        threading.Thread(target=report, name="status", daemon=True).start()

    try:
        web.app.run(host=web.HOST, port=web.PORT, threaded=True, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        log("Đang ngắt các phòng…")
        hub.shutdown()
        log("Đã dừng.")


if __name__ == "__main__":
    main()
