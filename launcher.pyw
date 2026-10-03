"""
Kaynt LiveHub – cửa sổ điều khiển (PySide6)

  Tab "Điều khiển" : Bắt đầu / Dừng server, mở trình duyệt, nhật ký
  Tab "Phòng"      : danh sách phòng đã lưu (thêm / xoá), kết nối / dừng tất cả
  Tab "Cài đặt"    : sessionid, API key Euler Stream, mật khẩu WiFi, tuỳ chọn khởi động

Cấu hình lưu ở data/settings.json (dùng chung với server). Khi server đang chạy, cửa sổ này
gửi thay đổi qua API của server; khi đã dừng thì ghi thẳng vào file.
Đóng cửa sổ khi app đang chạy -> thu nhỏ xuống khay hệ thống.

Chạy:  .venv\\Scripts\\pythonw.exe launcher.pyw   (hoặc double-click LiveHub.bat)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QAction, QBrush, QColor, QDesktopServices, QFont, QIcon, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap, QTextCharFormat)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit,
                               QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QSystemTrayIcon, QTabWidget, QVBoxLayout, QWidget)

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
try:  # đọc .env để hiển thị đúng giá trị dự phòng (ô trống trên giao diện -> dùng .env)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE, ".env"))
except Exception:
    pass
import store  # noqa: E402

PREFS = os.path.join(BASE, "data", "launcher.json")
IS_WIN = os.name == "nt"
USERNAME_RE = re.compile(r"@([A-Za-z0-9._]+)")

C = dict(bg="#0a0b10", surface="#13151d", surface2="#191c26", surface3="#212533", border="#262b38",
         text="#eef0f6", text2="#a9b0c2", text3="#7c8499", green="#10b981", green2="#34d399",
         red="#f43f5e", red2="#fb7185", brand="#fe2c55", violet="#7b61ff", cyan="#25f4ee", warn="#fbbf24")

QSS = f"""
QWidget#root, QWidget#page, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {C['bg']}; }}
QLabel {{ color: {C['text']}; }}
QLabel#title {{ font-size: 17pt; font-weight: 700; }}
QLabel#sub, QLabel#detail, QLabel#help, QLabel#section {{ color: {C['text3']}; }}
QLabel#section {{ font-size: 8pt; font-weight: 700; letter-spacing: 1px; }}
QLabel#status {{ font-size: 12pt; font-weight: 700; }}
QLabel#h {{ font-size: 11pt; font-weight: 700; }}
QLabel#ok {{ color: {C['green2']}; }}
QLabel#bad {{ color: {C['red2']}; }}
QLabel#muted {{ color: {C['text3']}; }}
QFrame#card {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 14px; }}
QPushButton {{
  background: {C['surface2']}; color: {C['text']}; border: 1px solid {C['border']}; border-radius: 10px;
  padding: 8px 14px; font-weight: 600;
}}
QPushButton:hover {{ background: {C['surface3']}; border-color: #3a4152; }}
QPushButton:disabled {{ color: {C['text3']}; background: {C['surface']}; }}
QPushButton#main {{ font-size: 12pt; font-weight: 700; padding: 10px; border: 0; border-radius: 12px; color: white; background: {C['green']}; }}
QPushButton#main:hover {{ background: {C['green2']}; }}
QPushButton#main[mode="stop"] {{ background: {C['red']}; }}
QPushButton#main[mode="stop"]:hover {{ background: {C['red2']}; }}
QPushButton#main:disabled {{ background: {C['surface3']}; color: {C['text3']}; }}
QPushButton#primary {{ background: {C['brand']}; border: 0; color: white; }}
QPushButton#primary:hover {{ background: #ff4468; }}
QPushButton#ghost {{ background: transparent; border: 0; color: {C['text3']}; padding: 4px 6px; font-weight: 500; }}
QPushButton#ghost:hover {{ color: {C['red2']}; }}
QPushButton#link {{ background: transparent; border: 0; color: {C['cyan']}; padding: 2px 0; font-weight: 500; text-align: left; }}
QPushButton#link:hover {{ color: white; text-decoration: underline; }}
QPushButton#x {{ background: transparent; border: 0; color: {C['text3']}; font-size: 13pt; padding: 0 6px; }}
QPushButton#x:hover {{ color: {C['red2']}; }}
QLineEdit, QComboBox {{
  background: {C['surface2']}; color: {C['text']}; border: 1px solid {C['border']}; border-radius: 9px;
  padding: 7px 10px; selection-background-color: #5b2333;
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {C['cyan']}; }}
QLineEdit:disabled {{ color: {C['text3']}; }}
QComboBox QAbstractItemView {{ background: {C['surface2']}; color: {C['text']}; selection-background-color: {C['surface3']}; border: 1px solid {C['border']}; }}
QCheckBox {{ color: {C['text2']}; spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid #3a4152; background: {C['surface2']}; }}
QCheckBox::indicator:checked {{ background: {C['brand']}; border-color: {C['brand']}; }}
QCheckBox#consent {{ color: {C['text2']}; background: rgba(251,191,36,20); border: 1px solid rgba(251,191,36,60); border-radius: 10px; padding: 8px; }}
QPlainTextEdit {{
  background: {C['surface']}; color: {C['text2']}; border: 1px solid {C['border']}; border-radius: 12px;
  padding: 6px; selection-background-color: #5b2333;
}}
QListWidget {{ background: {C['surface']}; border: 1px solid {C['border']}; border-radius: 12px; padding: 4px; outline: 0; }}
QListWidget::item {{ border-bottom: 1px solid {C['border']}; }}
QListWidget::item:selected {{ background: {C['surface2']}; }}
QTabWidget::pane {{ border: 0; }}
QTabBar::tab {{
  background: transparent; color: {C['text3']}; padding: 9px 16px; margin-right: 4px; font-weight: 600;
  border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{ color: {C['text']}; border-bottom: 2px solid {C['brand']}; }}
QTabBar::tab:hover {{ color: {C['text']}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px; }}
QScrollBar::handle:vertical {{ background: #2b3040; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QMenu {{ background: {C['surface2']}; color: {C['text']}; border: 1px solid {C['border']}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {C['surface3']}; }}
QToolTip {{ background: {C['surface3']}; color: {C['text']}; border: 1px solid {C['border']}; }}
"""

STATUS_TEXT = {"idle": "Chưa kết nối", "connecting": "Đang kết nối…", "connected": "Đang theo dõi",
               "reconnecting": "Đang kết nối lại…", "disconnected": "Mất kết nối", "offline": "Không live",
               "ended": "Live đã kết thúc", "stopped": "Đã ngắt", "error": "Lỗi", "saved": "Đã lưu"}
STATUS_COLOR = {"connected": C["green2"], "connecting": C["warn"], "reconnecting": C["warn"],
                "error": C["red2"], "disconnected": C["red2"]}


# ------------------------------------------------------------------ tiện ích
def read_port() -> int:
    try:
        return int(os.environ.get("PORT", "5000"))
    except ValueError:
        return 5000


def python_exe() -> str:
    """python.exe (không phải pythonw) để đọc được log của server."""
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        cand = exe[:-len("pythonw.exe")] + "python.exe"
        if os.path.exists(cand):
            return cand
    venv = os.path.join(BASE, ".venv", "Scripts" if IS_WIN else "bin", "python.exe" if IS_WIN else "python")
    return venv if os.path.exists(venv) else exe


_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # localhost: bỏ qua proxy


def http(method: str, url: str, body: dict | None = None, timeout: float = 3.0):
    """Gọi API server. Trả dict (kể cả khi lỗi 4xx có JSON) hoặc None nếu không kết nối được."""
    try:
        data = json.dumps(body if body is not None else {}).encode() if method in ("POST", "DELETE") else None
        req = urllib.request.Request(url, method=method, data=data, headers={"Content-Type": "application/json"})
        with _opener.open(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read() or b"{}")
        except Exception:
            return {"ok": False, "error": f"HTTP {e.code}"}
    except Exception:
        return None


def parse_username(text: str) -> str:
    text = (text or "").strip()
    m = USERNAME_RE.search(text)
    name = (m.group(1) if m else text.strip("/").split("/")[-1].lstrip("@")).strip().lower()
    if not re.fullmatch(r"[a-z0-9._]{1,64}", name):
        raise ValueError(f"Username không hợp lệ: {text}")
    return name


def load_prefs() -> dict:
    d = {"open_browser": True, "start_on_open": False, "tray_notice": True}
    try:
        with open(PREFS, encoding="utf-8") as f:
            d.update(json.load(f))
    except Exception:
        pass
    return d


def save_prefs(p: dict) -> None:
    try:
        os.makedirs(os.path.dirname(PREFS), exist_ok=True)
        with open(PREFS, "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def make_icon(size: int = 256, dot: str | None = None) -> QIcon:
    """Logo vẽ bằng code (ô vuông bo góc gradient + sóng live)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor(C["brand"]))
    g.setColorAt(0.5, QColor("#ff5f7e"))
    g.setColorAt(1, QColor(C["violet"]))
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), size * 0.26, size * 0.26)
    p.fillPath(path, QBrush(g))
    p.setPen(QPen(QColor("white"), size * 0.07, Qt.SolidLine, Qt.RoundCap))
    c = size / 2
    for r in (size * 0.18, size * 0.31):
        rect = QRectF(c - r, c - r, 2 * r, 2 * r)
        p.drawArc(rect, 135 * 16, 90 * 16)
        p.drawArc(rect, -45 * 16, 90 * 16)
    p.setBrush(QColor("white"))
    p.setPen(Qt.NoPen)
    p.drawEllipse(QPointF(c, c), size * 0.07, size * 0.07)
    if dot:
        p.setBrush(QColor(dot))
        p.setPen(QPen(QColor(C["bg"]), size * 0.05))
        p.drawEllipse(QPointF(size * 0.8, size * 0.8), size * 0.17, size * 0.17)
    p.end()
    return QIcon(pm)


def label(text: str = "", name: str = "", wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    return lb


def card() -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 16)
    lay.setSpacing(10)
    return f, lay


def secret_edit(placeholder: str) -> QLineEdit:
    e = QLineEdit()
    e.setEchoMode(QLineEdit.Password)
    e.setPlaceholderText(placeholder)
    act = e.addAction(make_eye_icon(), QLineEdit.TrailingPosition)
    act.setToolTip("Hiện / ẩn")
    act.triggered.connect(lambda: e.setEchoMode(QLineEdit.Normal if e.echoMode() == QLineEdit.Password else QLineEdit.Password))
    return e


def make_eye_icon() -> QIcon:
    pm = QPixmap(32, 32)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(C["text3"]), 2.4))
    path = QPainterPath()
    path.moveTo(3, 16)
    path.quadTo(16, 3, 29, 16)
    path.quadTo(16, 29, 3, 16)
    p.drawPath(path)
    p.drawEllipse(QPointF(16, 16), 4.5, 4.5)
    p.end()
    return QIcon(pm)


class Bridge(QObject):
    """Chuyển việc từ thread nền về luồng giao diện."""
    log = Signal(str, str)
    state = Signal(str, str)
    call = Signal(object)


# ------------------------------------------------------------------ dòng phòng trong danh sách
class RoomRow(QWidget):
    def __init__(self, owner: "Launcher", r: dict) -> None:
        super().__init__()
        self.uid = r["unique_id"]
        self.owner = owner
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 6, 6)
        lay.setSpacing(10)
        self.dot = QLabel("●")
        lay.addWidget(self.dot)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.name = label()
        self.name.setStyleSheet("font-weight: 600;")
        self.sub = label(name="muted")
        col.addWidget(self.name)
        col.addWidget(self.sub)
        lay.addLayout(col, 1)
        x = QPushButton("✕")
        x.setObjectName("x")
        x.setCursor(Qt.PointingHandCursor)
        x.setToolTip("Xoá phòng khỏi danh sách")
        x.clicked.connect(lambda: owner.remove_room(self.uid))
        lay.addWidget(x)
        self.update_data(r)

    def update_data(self, r: dict) -> None:
        st = r.get("status", "saved")
        self.dot.setStyleSheet(f"color: {STATUS_COLOR.get(st, C['text3'])}; font-size: 11pt;")
        nick = r.get("nickname")
        self.name.setText(f"{nick} · @{self.uid}" if nick else f"@{self.uid}")
        sub = STATUS_TEXT.get(st, st)
        if st == "connected" and r.get("viewers"):
            sub += f" · {r['viewers']:,} người xem".replace(",", ".")
        if st == "error" and r.get("message"):
            sub = r["message"][:90]
        self.sub.setText(sub)


# ------------------------------------------------------------------ cửa sổ chính
class Launcher(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("root")
        self.port = read_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen | None = None
        self.state = "stopped"          # stopped | starting | running | stopping | external
        self.lan_url = ""
        self.quitting = False
        self.prefs = load_prefs()
        self.clear_flags: dict = {}
        self.bus = Bridge()
        self.bus.log.connect(self.append_log)
        self.bus.state.connect(self.set_state)
        self.bus.call.connect(lambda fn: fn())

        self.setWindowTitle("Kaynt LiveHub")
        self.setWindowIcon(make_icon())
        self.resize(600, 720)
        self.setMinimumSize(500, 560)
        self._build()
        self._build_tray()
        self.set_state("stopped", "Bấm Bắt đầu để chạy app")
        self.load_settings()
        self.refresh_rooms()
        self.poll = QTimer(self)
        self.poll.timeout.connect(self._poll_rooms)
        self.poll.start(3000)
        threading.Thread(target=self._detect_existing, daemon=True).start()

    @property
    def live(self) -> bool:
        return self.state in ("running", "external")

    def bg(self, work, done=None) -> None:
        """Chạy work() ở thread nền, rồi done(kết_quả) trên luồng giao diện."""
        def run() -> None:
            res = work()
            if done:
                self.bus.call.emit(lambda: done(res))
        threading.Thread(target=run, daemon=True).start()

    # ============================================================ dựng giao diện
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)
        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(make_icon(96).pixmap(42, 42))
        head.addWidget(logo)
        tt = QVBoxLayout()
        tt.setSpacing(0)
        tt.addWidget(label("Kaynt LiveHub", "title"))
        tt.addWidget(label("Theo dõi nhiều phiên TikTok LIVE", "sub"))
        head.addLayout(tt)
        head.addStretch(1)
        self.head_dot = label("●")
        self.head_state = label(name="muted")
        head.addWidget(self.head_dot)
        head.addWidget(self.head_state)
        root.addLayout(head)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_control(), "Điều khiển")
        self.tabs.addTab(self._tab_rooms(), "Phòng")
        self.tabs.addTab(self._tab_settings(), "Cài đặt")
        self.tabs.currentChanged.connect(self._on_tab)
        root.addWidget(self.tabs, 1)

    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        w.setObjectName("page")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(12)
        return w, lay

    # ---------------- tab Điều khiển
    def _tab_control(self) -> QWidget:
        w, lay = self._page()
        f, cl = card()
        row = QHBoxLayout()
        self.dot = label("●")
        self.status = label(name="status")
        row.addWidget(self.dot)
        row.addWidget(self.status)
        row.addStretch(1)
        cl.addLayout(row)
        self.detail = label(name="detail", wrap=True)
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        cl.addWidget(self.detail)
        self.btn_main = QPushButton()
        self.btn_main.setObjectName("main")
        self.btn_main.setCursor(Qt.PointingHandCursor)
        self.btn_main.setMinimumHeight(46)
        self.btn_main.clicked.connect(self.toggle)
        cl.addWidget(self.btn_main)
        r2 = QHBoxLayout()
        r2.setSpacing(10)
        self.btn_open = QPushButton("Mở trình duyệt")
        self.btn_open.clicked.connect(self.open_browser)
        self.btn_lan = QPushButton("Copy link WiFi")
        self.btn_lan.clicked.connect(self.copy_lan)
        for b in (self.btn_open, self.btn_lan):
            b.setCursor(Qt.PointingHandCursor)
            r2.addWidget(b)
        cl.addLayout(r2)
        lay.addWidget(f)

        links = QHBoxLayout()
        links.setSpacing(18)
        items = [("Mở thư mục log", lambda: self.open_folder("logs"))]
        if IS_WIN:
            items.insert(0, ("Tạo lối tắt ngoài Desktop", self.make_shortcut))
            items.append(("Mở tường lửa cho WiFi", self.open_firewall))
        for text, fn in items:
            b = QPushButton(text)
            b.setObjectName("link")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(fn)
            links.addWidget(b)
        links.addStretch(1)
        lay.addLayout(links)

        lay.addWidget(label("NHẬT KÝ", "section"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1500)
        self.log.setFont(QFont("Consolas" if IS_WIN else "Monospace", 9))
        lay.addWidget(self.log, 1)
        return w

    # ---------------- tab Phòng
    def _tab_rooms(self) -> QWidget:
        w, lay = self._page()
        f, cl = card()
        cl.addWidget(label("Thêm phòng", "h"))
        row = QHBoxLayout()
        self.room_in = QLineEdit()
        self.room_in.setPlaceholderText("@username hoặc link live – nhiều phòng cách nhau bằng dấu phẩy")
        self.room_in.returnPressed.connect(self.add_rooms)
        add = QPushButton("Thêm")
        add.setObjectName("primary")
        add.setCursor(Qt.PointingHandCursor)
        add.clicked.connect(self.add_rooms)
        row.addWidget(self.room_in, 1)
        row.addWidget(add)
        cl.addLayout(row)
        self.room_hint = label("", "help", wrap=True)
        cl.addWidget(self.room_hint)
        lay.addWidget(f)

        hr = QHBoxLayout()
        self.rooms_title = label("Phòng đã lưu", "h")
        hr.addWidget(self.rooms_title)
        hr.addStretch(1)
        self.btn_conn_all = QPushButton("▶  Kết nối tất cả")
        self.btn_conn_all.clicked.connect(lambda: self._room_api("POST", "/api/start_all", "Đang kết nối các phòng…"))
        self.btn_stop_all = QPushButton("■  Dừng tất cả")
        self.btn_stop_all.clicked.connect(lambda: self._confirm_stop_all())
        for b in (self.btn_conn_all, self.btn_stop_all):
            b.setCursor(Qt.PointingHandCursor)
            hr.addWidget(b)
        lay.addLayout(hr)
        self.room_list = QListWidget()
        self.room_list.setSelectionMode(QListWidget.NoSelection)
        self.room_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        lay.addWidget(self.room_list, 1)
        self.room_empty = label("Chưa có phòng nào. Nhập @username ở trên rồi bấm Thêm.", "muted", wrap=True)
        self.room_empty.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.room_empty)
        self.rows: dict[str, tuple[QListWidgetItem, RoomRow]] = {}
        return w

    # ---------------- tab Cài đặt
    def _tab_settings(self) -> QWidget:
        outer, olay = self._page()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner.setObjectName("page")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(12)
        lay.setSizeConstraint(QLayout.SetMinAndMaxSize)   # không cho vùng cuộn ép dẹp nội dung
        scroll.setWidget(inner)
        olay.addWidget(scroll, 1)

        # Khởi động
        f, cl = card()
        cl.addWidget(label("Khởi động", "h"))
        self.cb_autostart = QCheckBox("Bắt đầu là tự kết nối tất cả phòng đã lưu")
        self.cb_open = QCheckBox("Tự mở trình duyệt khi bắt đầu")
        self.cb_open.setChecked(self.prefs.get("open_browser", True))
        self.cb_auto = QCheckBox("Tự bấm Bắt đầu ngay khi mở cửa sổ này")
        self.cb_auto.setChecked(self.prefs.get("start_on_open", False))
        for cb in (self.cb_open, self.cb_auto):
            cb.toggled.connect(self._save_prefs)
        for cb in (self.cb_autostart, self.cb_open, self.cb_auto):
            cl.addWidget(cb)
        lay.addWidget(f)

        # sessionid
        f, cl = card()
        cl.addWidget(label("Đăng nhập TikTok (sessionid)", "h"))
        cl.addWidget(label("Dùng để xem live giới hạn độ tuổi. Lấy trong Chrome đã đăng nhập tiktok.com: F12 → Application → "
                           "Cookies → https://www.tiktok.com → sessionid và tt-target-idc.", "help", wrap=True))
        self.sess_status = label(wrap=True)
        cl.addWidget(self.sess_status)
        cl.addWidget(label("sessionid", "muted"))
        self.in_sid = secret_edit("Dán sessionid mới (để trống = giữ nguyên)")
        cl.addWidget(self.in_sid)
        row = QHBoxLayout()
        c1, c2 = QVBoxLayout(), QVBoxLayout()
        c1.addWidget(label("tt-target-idc", "muted"))
        self.in_idc = QLineEdit()
        self.in_idc.setPlaceholderText("vd: alisg, useast2a")
        c1.addWidget(self.in_idc)
        c2.addWidget(label("Khi nào dùng", "muted"))
        self.in_mode = QComboBox()
        for v, t in (("auto", "Tự động – chỉ khi phòng giới hạn tuổi"), ("always", "Luôn dùng cho mọi phòng"), ("off", "Tắt")):
            self.in_mode.addItem(t, v)
        c2.addWidget(self.in_mode)
        row.addLayout(c1, 1)
        row.addLayout(c2, 1)
        cl.addLayout(row)
        self.in_consent = QCheckBox("Tôi hiểu TikTokLive sẽ gửi sessionid tới máy chủ ký Euler Stream để kết nối, và sessionid "
                                    "cho toàn quyền vào tài khoản TikTok. Tôi đồng ý (nên dùng tài khoản phụ).")
        self.in_consent.setObjectName("consent")
        self._wrap_checkbox(self.in_consent)
        cl.addWidget(self.in_consent)
        self.btn_clear_sid = self._clear_btn("Xoá sessionid đã lưu", "clear_sessionid", self.sess_status)
        cl.addWidget(self.btn_clear_sid, 0, Qt.AlignLeft)
        lay.addWidget(f)

        # API key
        f, cl = card()
        cl.addWidget(label("API key Euler Stream", "h"))
        cl.addWidget(label("Không bắt buộc. Có key thì ít bị giới hạn khi theo dõi nhiều phòng. Tạo tại eulerstream.com → "
                           "Dashboard → API Keys.", "help", wrap=True))
        self.sign_status = label(wrap=True)
        cl.addWidget(self.sign_status)
        self.in_key = secret_edit("Dán API key mới (để trống = giữ nguyên)")
        cl.addWidget(self.in_key)
        self.btn_clear_key = self._clear_btn("Xoá API key đã lưu", "clear_sign_api_key", self.sign_status)
        cl.addWidget(self.btn_clear_key, 0, Qt.AlignLeft)
        lay.addWidget(f)

        # mật khẩu WiFi
        f, cl = card()
        cl.addWidget(label("Mật khẩu truy cập qua WiFi", "h"))
        cl.addWidget(label("Điện thoại / máy khác cùng WiFi phải nhập mật khẩu này (tên đăng nhập gõ gì cũng được). "
                           "Máy chạy app không cần nhập.", "help", wrap=True))
        self.pw_status = label(wrap=True)
        cl.addWidget(self.pw_status)
        self.in_pw = secret_edit("Đặt mật khẩu mới (để trống = giữ nguyên)")
        cl.addWidget(self.in_pw)
        self.btn_clear_pw = self._clear_btn("Bỏ mật khẩu", "clear_access_password", self.pw_status)
        cl.addWidget(self.btn_clear_pw, 0, Qt.AlignLeft)
        lay.addWidget(f)
        lay.addStretch(1)

        bar = QHBoxLayout()
        self.set_note = label("", "help", wrap=True)
        bar.addWidget(self.set_note, 1)
        undo = QPushButton("Hoàn tác")
        undo.clicked.connect(self.load_settings)
        save = QPushButton("Lưu cài đặt")
        save.setObjectName("primary")
        save.setCursor(Qt.PointingHandCursor)
        save.clicked.connect(self.save_settings)
        bar.addWidget(undo)
        bar.addWidget(save)
        olay.addLayout(bar)
        return outer

    def _wrap_checkbox(self, cb: QCheckBox) -> None:
        # QCheckBox không tự xuống dòng -> giới hạn chiều rộng chữ bằng cách chèn xuống dòng mềm
        txt = cb.text()
        words, lines, cur = txt.split(), [], ""
        for w in words:
            if len(cur) + len(w) > 70:
                lines.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        lines.append(cur)
        cb.setText("\n".join(lines))

    def _clear_btn(self, text: str, flag: str, status: QLabel) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("ghost")
        b.setCursor(Qt.PointingHandCursor)

        def click() -> None:
            self.clear_flags[flag] = True
            status.setObjectName("bad")
            status.setText("Sẽ xoá khi bấm Lưu cài đặt")
            status.style().unpolish(status)
            status.style().polish(status)
            b.hide()
        b.clicked.connect(click)
        return b

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(make_icon(64), self)
        menu = QMenu()
        self.act_show = QAction("Mở cửa sổ", self, triggered=self.show_window)
        self.act_web = QAction("Mở trình duyệt", self, triggered=self.open_browser)
        self.act_toggle = QAction("Bắt đầu", self, triggered=self.toggle)
        self.act_quit = QAction("Thoát", self, triggered=self.quit_app)
        for a in (self.act_show, self.act_web, self.act_toggle):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(self.act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.show_window() if r in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def _save_prefs(self) -> None:
        self.prefs.update(open_browser=self.cb_open.isChecked(), start_on_open=self.cb_auto.isChecked())
        save_prefs(self.prefs)

    def _on_tab(self, i: int) -> None:
        if i == 1:
            self.refresh_rooms()
        elif i == 2:
            self.load_settings()

    # ============================================================ nhật ký / trạng thái
    def append_log(self, line: str, tag: str = "") -> None:
        low = line.lower()
        if not tag:
            tag = "err" if ("traceback" in low or "error" in low or "lỗi" in low) else ("warn" if "⚠" in line else "")
        color = {"err": C["red2"], "warn": C["warn"], "ok": C["green2"], "me": C["cyan"]}.get(tag, C["text2"])
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cur = self.log.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        if not self.log.document().isEmpty():
            cur.insertBlock()
        cur.insertText(line.rstrip(), fmt)
        self.log.setTextCursor(cur)
        self.log.ensureCursorVisible()

    def set_state(self, state: str, detail: str = "") -> None:
        prev = self.state
        self.state = state
        color = {"stopped": C["text3"], "starting": C["warn"], "running": C["green2"],
                 "stopping": C["warn"], "external": C["green2"]}[state]
        text = {"stopped": "Đang dừng", "starting": "Đang khởi động…", "running": "Đang chạy",
                "stopping": "Đang dừng lại…", "external": "Đang chạy (mở từ nơi khác)"}[state]
        for d in (self.dot, self.head_dot):
            d.setStyleSheet(f"color: {color}; font-size: 13pt;")
        self.status.setText(text)
        self.head_state.setText(text)
        self.detail.setText(detail)
        live = self.live
        self.btn_main.setProperty("mode", "stop" if live else "start")
        self.btn_main.setText("■   Dừng" if live else ("▶   Bắt đầu" if state == "stopped" else text))
        self.btn_main.setEnabled(state in ("stopped", "running", "external"))
        self.btn_main.style().unpolish(self.btn_main)
        self.btn_main.style().polish(self.btn_main)
        self.btn_open.setEnabled(live)
        self.btn_lan.setEnabled(live and bool(self.lan_url))
        self.btn_lan.setToolTip(self.lan_url or "Chưa có link WiFi (HOST=127.0.0.1 hoặc máy chưa vào mạng)")
        self.btn_conn_all.setVisible(live)
        self.btn_stop_all.setVisible(live)
        self.room_hint.setText("App đang chạy: thêm / xoá phòng có hiệu lực ngay." if live else
                               "App đang dừng: phòng được lưu lại, bấm Bắt đầu (tab Điều khiển) để kết nối.")
        self.set_note.setText("App đang chạy: sessionid / API key mới áp dụng cho lần kết nối sau (Kết nối lại phòng trên web)."
                              if live else "Cài đặt lưu trên máy này (data/settings.json).")
        self.act_toggle.setText("Dừng" if live else "Bắt đầu")
        self.act_toggle.setEnabled(state in ("stopped", "running", "external"))
        self.act_web.setEnabled(live)
        self.tray.setIcon(make_icon(64, color if state != "stopped" else None))
        self.tray.setToolTip(f"Kaynt LiveHub – {text}")
        if prev != state and state in ("stopped", "running", "external"):
            if state == "stopped":
                store.load()   # server có thể đã ghi file -> đọc lại
            self.refresh_rooms()
            self.load_settings()

    # ============================================================ phòng
    def refresh_rooms(self) -> None:
        if self.live:
            self.bg(lambda: http("GET", self.base_url + "/api/rooms", timeout=2),
                    lambda j: self._show_rooms(j["rooms"]) if j and j.get("ok") else None)
        else:
            self._show_rooms([{**r, "status": "saved"} for r in store.load()["rooms"]])

    def _poll_rooms(self) -> None:
        if self.live and self.tabs.currentIndex() == 1 and self.isVisible():
            self.refresh_rooms()

    def _show_rooms(self, rooms: list) -> None:
        seen = set()
        for r in rooms:
            uid = r["unique_id"]
            seen.add(uid)
            if uid in self.rows:
                self.rows[uid][1].update_data(r)
            else:
                item = QListWidgetItem()
                row = RoomRow(self, r)
                item.setSizeHint(QSize(0, 56))
                self.room_list.addItem(item)
                self.room_list.setItemWidget(item, row)
                self.rows[uid] = (item, row)
        for uid in list(self.rows):
            if uid not in seen:
                item, _ = self.rows.pop(uid)
                self.room_list.takeItem(self.room_list.row(item))
        n = len(self.rows)
        self.rooms_title.setText(f"Phòng đã lưu ({n})")
        self.room_empty.setVisible(n == 0)
        self.room_list.setVisible(n > 0)

    def add_rooms(self) -> None:
        names = [x for x in re.split(r"[\s,;]+", self.room_in.text()) if x.strip()]
        if not names:
            return
        uids, bad = [], []
        for n in names:
            try:
                uids.append(parse_username(n))
            except ValueError:
                bad.append(n)
        if bad:
            QMessageBox.warning(self, "Kaynt LiveHub", "Username không hợp lệ:\n" + "\n".join(bad))
        if not uids:
            return
        self.room_in.clear()
        if self.live:
            def work():
                errs = []
                for u in uids:
                    j = http("POST", self.base_url + "/api/rooms", {"unique_id": u}, timeout=30)
                    if not j or not j.get("ok"):
                        errs.append(f"@{u}: {(j or {}).get('error', 'không gọi được server')}")
                return errs

            def done(errs):
                if errs:
                    QMessageBox.warning(self, "Kaynt LiveHub", "\n".join(errs))
                self.append_log(f"Đã thêm {len(uids) - len(errs)} phòng.", "ok")
                self.refresh_rooms()
            self.bg(work, done)
        else:
            for u in uids:
                store.save_room(u, True, False)
            self.append_log(f"Đã lưu {len(uids)} phòng: " + ", ".join("@" + u for u in uids), "ok")
            self.refresh_rooms()

    def remove_room(self, uid: str) -> None:
        if QMessageBox.question(self, "Kaynt LiveHub", f"Xoá @{uid} khỏi danh sách?"
                                + ("\nPhòng đang chạy sẽ bị ngắt." if self.live else "")) != QMessageBox.Yes:
            return
        if self.live:
            self.bg(lambda: http("DELETE", self.base_url + "/api/rooms/" + urllib.parse.quote(uid), timeout=30),
                    lambda j: (self.append_log(f"Đã xoá @{uid}", "ok") if j and j.get("ok") else
                               QMessageBox.warning(self, "Kaynt LiveHub", (j or {}).get("error", "Không gọi được server")),
                               self.refresh_rooms()))
        else:
            store.forget_room(uid)
            self.refresh_rooms()

    def _confirm_stop_all(self) -> None:
        if QMessageBox.question(self, "Kaynt LiveHub", "Dừng kết nối tất cả phòng đang chạy?\n"
                                "Các phòng vẫn được lưu, bấm Kết nối tất cả để chạy lại.") != QMessageBox.Yes:
            return
        self._room_api("POST", "/api/stop_all", "Đã dừng tất cả phòng (vẫn giữ trong danh sách).")

    def _room_api(self, method: str, path: str, msg: str) -> None:
        self.bg(lambda: http(method, self.base_url + path, timeout=60),
                lambda j: (self.append_log(msg if j and j.get("ok") else f"Lỗi: {(j or {}).get('error', 'không gọi được server')}",
                                           "ok" if j and j.get("ok") else "err"), self.refresh_rooms()))

    # ============================================================ cài đặt
    def load_settings(self) -> None:
        self.clear_flags = {}
        store.load()
        v = store.public_view()
        self.cb_autostart.setChecked(v["autostart"])
        s = v["session"]
        self._status(self.sess_status, "" if not s["configured"] else ("bad" if s["problem"] else "ok"),
                     "Chưa có sessionid" if not s["configured"] else
                     (s["problem"] or f"Đang dùng {s['masked']}") + (" (lấy từ .env)" if s["source"] == "env" else ""))
        self.in_sid.clear()
        self.in_idc.setText(s["target_idc"])
        i = self.in_mode.findData(s["mode"])
        self.in_mode.setCurrentIndex(max(0, i))
        self.in_consent.setChecked(s["consent"])
        self.btn_clear_sid.setVisible(s["ui_set"])
        g = v["sign"]
        self._status(self.sign_status, "ok" if g["configured"] else "",
                     (f"Đang dùng {g['masked']}" + ("" if g["ui_set"] else " (lấy từ .env)")) if g["configured"] else "Chưa có – đang dùng gói miễn phí")
        self.in_key.clear()
        self.btn_clear_key.setVisible(g["ui_set"])
        p = v["access_password"]
        self._status(self.pw_status, "ok" if p["set"] else "bad",
                     ("Đã đặt" + ("" if p["ui_set"] else " (lấy từ .env)")) if p["set"] else "Chưa đặt – ai cùng WiFi cũng vào được")
        self.in_pw.clear()
        self.btn_clear_pw.setVisible(p["ui_set"])

    def _status(self, lb: QLabel, kind: str, text: str) -> None:
        lb.setObjectName({"ok": "ok", "bad": "bad"}.get(kind, "muted"))
        lb.setText("● " + text)
        lb.style().unpolish(lb)
        lb.style().polish(lb)

    def save_settings(self) -> None:
        sid = self.in_sid.text().strip()
        if sid and not self.in_consent.isChecked():
            QMessageBox.warning(self, "Kaynt LiveHub", "Cần tick ô đồng ý gửi sessionid tới máy chủ ký thì sessionid mới dùng được.")
            return
        if sid and not self.in_idc.text().strip():
            QMessageBox.warning(self, "Kaynt LiveHub", "Nhập thêm tt-target-idc (cookie tt-target-idc cùng chỗ với sessionid).")
            self.in_idc.setFocus()
            return
        body = {
            "autostart": self.cb_autostart.isChecked(),
            "session": {"sessionid": sid, "target_idc": self.in_idc.text().strip(), "mode": self.in_mode.currentData(),
                        "consent": self.in_consent.isChecked(), "clear_sessionid": bool(self.clear_flags.get("clear_sessionid"))},
            "sign_api_key": self.in_key.text().strip(), "clear_sign_api_key": bool(self.clear_flags.get("clear_sign_api_key")),
            "access_password": self.in_pw.text(), "clear_access_password": bool(self.clear_flags.get("clear_access_password")),
        }
        if self.live:
            def done(j):
                if j and j.get("ok"):
                    self.append_log("Đã lưu cài đặt (áp dụng cho lần kết nối sau).", "ok")
                    self.load_settings()
                    self.set_note.setText("✓ Đã lưu. Phòng đang chạy cần Kết nối lại để dùng sessionid / API key mới.")
                else:
                    QMessageBox.warning(self, "Kaynt LiveHub", (j or {}).get("error", "Không gọi được server"))
            self.bg(lambda: http("POST", self.base_url + "/api/settings", body), done)
        else:
            store.apply_patch(body)
            self.load_settings()
            self.set_note.setText("✓ Đã lưu cài đặt.")
            self.append_log("Đã lưu cài đặt.", "ok")

    # ============================================================ server
    def _detect_existing(self) -> None:
        if http("GET", self.base_url + "/api/ping", timeout=1.5):
            self.bus.state.emit("external", f"{self.base_url}  ·  app đã chạy sẵn trước đó")
            self.bus.log.emit("App đang chạy sẵn từ trước. Bấm Dừng để tắt.", "me")
        elif self.cb_auto.isChecked():
            self.bus.call.emit(lambda: QTimer.singleShot(300, self.start))

    def toggle(self) -> None:
        if self.state == "stopped":
            self.start()
        elif self.live:
            self.stop()

    def start(self) -> None:
        if self.state != "stopped":
            return
        app_py = os.path.join(BASE, "app.py")
        if not os.path.exists(app_py):
            QMessageBox.critical(self, "Kaynt LiveHub", "Không tìm thấy app.py cạnh launcher.pyw")
            return
        self.lan_url = ""
        self.set_state("starting", "Đang chuẩn bị…")
        self.append_log("—— Bắt đầu " + time.strftime("%H:%M:%S") + " ——", "me")
        threading.Thread(target=self._prepare_and_run, args=(app_py,), daemon=True).start()

    def _deps_changed(self) -> bool:
        """requirements.txt khác bản đã cài (.venv/.installed) -> cần cài thêm thư viện."""
        req = os.path.join(BASE, "requirements.txt")
        mark = os.path.join(BASE, ".venv", ".installed")
        try:
            with open(req, "rb") as a:
                want = a.read()
        except OSError:
            return False
        try:
            with open(mark, "rb") as b:
                return b.read() != want
        except OSError:
            return True

    def _prepare_and_run(self, app_py: str) -> None:
        flags = subprocess.CREATE_NO_WINDOW if IS_WIN else 0
        if self._deps_changed() and os.path.isdir(os.path.join(BASE, ".venv")):
            self.bus.state.emit("starting", "Đang cài thư viện mới (lần đầu sau khi cập nhật, hơi lâu)…")
            self.bus.log.emit("Có thư viện mới trong requirements.txt – đang cài…", "me")
            try:
                p = subprocess.Popen([python_exe(), "-m", "pip", "install", "--disable-pip-version-check", "-r",
                                      os.path.join(BASE, "requirements.txt")], cwd=BASE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags)
                for raw in iter(p.stdout.readline, b""):  # type: ignore[union-attr]
                    line = raw.decode("utf-8", "replace").rstrip()
                    if line and not line.startswith("Requirement already satisfied"):
                        self.bus.log.emit(line, "")
                if p.wait() == 0:
                    import shutil
                    shutil.copyfile(os.path.join(BASE, "requirements.txt"), os.path.join(BASE, ".venv", ".installed"))
                    self.bus.log.emit("Cài thư viện xong.", "ok")
                else:
                    self.bus.log.emit("Cài thư viện thất bại – thử chạy LiveHub.bat để xem lỗi.", "err")
            except Exception as ex:
                self.bus.log.emit(f"Không cài được thư viện: {ex}", "err")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", "LIVEHUB_LAUNCHER": "1"}
        try:
            self.proc = subprocess.Popen([python_exe(), "-u", app_py], cwd=BASE, env=env, stdin=subprocess.DEVNULL,
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags)
        except Exception as ex:
            self.bus.log.emit(f"Không chạy được app: {ex}", "err")
            self.bus.state.emit("stopped", "Bấm Bắt đầu để chạy app")
            return
        self.bus.state.emit("starting", "Đang mở server…")
        threading.Thread(target=self._read_output, args=(self.proc,), daemon=True).start()
        threading.Thread(target=self._wait_ready, args=(self.proc,), daemon=True).start()

    def _read_output(self, proc: subprocess.Popen) -> None:
        for raw in iter(proc.stdout.readline, b""):  # type: ignore[union-attr]
            line = raw.decode("utf-8", "replace").rstrip()
            if not line:
                continue
            m = re.search(r"Qua WiFi/LAN\s*:\s*(http://\S+)", line)
            if m and not self.lan_url:
                self.lan_url = m.group(1)
            self.bus.log.emit(line, "")
        code = proc.wait()
        if proc is self.proc:
            self.proc = None
            if self.state != "stopping":
                self.bus.log.emit(f"Server đã tắt (mã {code}).", "warn")
                self.bus.state.emit("stopped", "Bấm Bắt đầu để chạy app")

    def _wait_ready(self, proc: subprocess.Popen) -> None:
        t0 = time.time()
        while time.time() - t0 < 60 and proc.poll() is None:
            j = http("GET", self.base_url + "/api/ping", timeout=1.5)
            if j:
                n = j.get("rooms", 0)
                detail = self.base_url + (f"   ·   WiFi: {self.lan_url.replace('http://', '')}" if self.lan_url else "")
                self.bus.state.emit("running", detail)
                auto = " – đang tự kết nối" if (n and j.get("autostart")) else (" – vào tab Phòng bấm Kết nối tất cả" if n else "")
                self.bus.log.emit(f"Sẵn sàng · {n} phòng đã lưu{auto}", "ok")
                if self.cb_open.isChecked():
                    self.bus.call.emit(self.open_browser)
                return
            time.sleep(0.5)
        if proc.poll() is None:
            self.bus.log.emit("Server khởi động quá lâu – xem nhật ký.", "warn")

    def stop(self, then=None) -> None:
        if self.state not in ("running", "external", "starting"):
            if then:
                then()
            return
        self.set_state("stopping", "Đang ngắt các phòng…")
        proc = self.proc

        def work() -> None:
            http("POST", self.base_url + "/api/shutdown")
            if proc is not None:
                try:
                    proc.wait(15)
                except subprocess.TimeoutExpired:
                    proc.terminate()
                    try:
                        proc.wait(5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            else:
                for _ in range(30):
                    if not http("GET", self.base_url + "/api/ping", timeout=1):
                        break
                    time.sleep(0.5)
            self.proc = None
            self.bus.log.emit("Đã dừng.", "me")
            self.bus.state.emit("stopped", "Bấm Bắt đầu để chạy app")
            if then:
                self.bus.call.emit(then)

        threading.Thread(target=work, daemon=True).start()

    # ============================================================ tiện ích
    def open_browser(self) -> None:
        webbrowser.open(self.base_url)

    def copy_lan(self) -> None:
        if self.lan_url:
            QApplication.clipboard().setText(self.lan_url)
            self.append_log(f"Đã copy link WiFi: {self.lan_url}", "ok")

    def open_folder(self, name: str) -> None:
        path = os.path.join(BASE, name)
        os.makedirs(path, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def make_shortcut(self) -> None:
        pyw = os.path.join(BASE, ".venv", "Scripts", "pythonw.exe")
        if not os.path.exists(pyw):
            pyw = sys.executable
        target = os.path.join(BASE, "launcher.pyw")
        ps = ("$d=[Environment]::GetFolderPath('Desktop');"
              "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Kaynt LiveHub.lnk'));"
              f"$s.TargetPath='{pyw}';$s.Arguments='\"{target}\"';$s.WorkingDirectory='{BASE}';"
              "$s.Description='Kaynt LiveHub';$s.Save()")
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, timeout=20,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            self.append_log("Đã tạo lối tắt 'Kaynt LiveHub' ngoài Desktop.", "ok")
        except Exception as ex:
            self.append_log(f"Không tạo được lối tắt: {ex}", "err")

    def open_firewall(self) -> None:
        """Cho phép máy khác cùng WiFi vào app: mở cổng trên Windows Firewall (mạng Private). Cần quyền Admin."""
        if QMessageBox.question(self, "Kaynt LiveHub",
                                f"Mở cổng {self.port} trên Windows Firewall (chỉ mạng Private) để điện thoại / máy khác "
                                "cùng WiFi vào được app?\n\nWindows sẽ hỏi quyền Administrator.") != QMessageBox.Yes:
            return
        rule = "Kaynt LiveHub"
        cmd = (f'/c netsh advfirewall firewall delete rule name="{rule}" >nul 2>&1 & '
               f'netsh advfirewall firewall add rule name="{rule}" dir=in action=allow protocol=TCP '
               f'localport={self.port} profile=private')
        ps = f"Start-Process cmd -Verb RunAs -WindowStyle Hidden -Wait -ArgumentList '{cmd}'"

        def work():
            try:
                r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=120,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
                return r.returncode, (r.stderr or b"").decode("utf-8", "replace").strip()
            except Exception as ex:
                return 1, str(ex)

        def done(res):
            code, err = res
            if code == 0:
                self.append_log(f"Đã mở cổng {self.port} trên tường lửa (mạng Private). Nếu WiFi đang để "
                                "\"Public network\" thì đổi sang \"Private network\" trong Settings → Network & internet.", "ok")
            else:
                self.append_log("Chưa mở được tường lửa (có thể bạn đã bấm Không ở hộp hỏi quyền Admin). " + err[:200], "warn")
        self.append_log("Đang xin quyền Administrator để mở tường lửa…", "me")
        self.bg(work, done)

    # ============================================================ cửa sổ / khay
    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e) -> None:  # noqa: N802
        running = self.state in ("running", "starting") and self.proc is not None
        if self.quitting or not running:
            e.accept()
            QApplication.quit()
            return
        e.ignore()
        if self.tray.isVisible():
            self.hide()
            if self.prefs.get("tray_notice", True):
                self.tray.showMessage("Kaynt LiveHub vẫn đang chạy",
                                      "App đã thu xuống khay hệ thống. Chuột phải vào biểu tượng → Thoát để tắt hẳn.",
                                      QSystemTrayIcon.Information, 5000)
                self.prefs["tray_notice"] = False
                save_prefs(self.prefs)
        elif QMessageBox.question(self, "Kaynt LiveHub", "Đóng cửa sổ sẽ dừng app (ngắt các phòng).\nTiếp tục?") \
                == QMessageBox.Yes:
            self.quit_app()

    def quit_app(self) -> None:
        def done() -> None:
            self.quitting = True
            self.tray.hide()
            QApplication.quit()
        if self.proc is not None and self.state in ("running", "starting"):
            self.show_window()
            self.stop(then=done)
        else:
            done()


def main() -> None:
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Kaynt.LiveHub")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("Kaynt LiveHub")
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont("Segoe UI" if IS_WIN else app.font().family(), 10))
    app.setStyleSheet(QSS)
    w = Launcher()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
