# Kaynt – Live Observer

Web app (Flask + TikTokLive) để theo dõi **nhiều phiên TikTok LIVE cùng lúc** theo thời gian thực:

- **Nhiều phòng**: mỗi phòng một tab (xem chi tiết), tab **Tất cả** hiện lưới video nhỏ + số liệu + bình luận mới nhất của mọi phòng. Mặc định tối đa 12 phòng (`MAX_ROOMS`).
- **Video live** phát ngay trên trang (FLV qua mpegts.js, Flask chuyển tiếp luồng để tránh lỗi CORS/Referer), chọn chất lượng HD/SD/LD…
- **Hoạt động trực tiếp**: bình luận, quà (gộp combo đang chạy vào 1 dòng), theo dõi, chia sẻ, vào phòng, thả tim – có bộ lọc và ô tìm kiếm.
- **Thống kê**: người xem (và đỉnh), bình luận, kim cương/quà, lượt thích, vào phòng, theo dõi/chia sẻ, thời gian đã theo dõi.
- **Biểu đồ diễn biến** (mỗi 10 giây một điểm, giữ 1 giờ): người xem, bình luận, tim, kim cương.
- **Top tặng quà / Top bình luận**.
- **Tự kết nối lại** khi rớt mạng (tối đa 5 lần, giãn cách 5→30 s); dừng hẳn khi live kết thúc.
- Mọi sự kiện được ghi vào `logs/<username>_<thời gian>.jsonl` để phân tích sau.

## Chạy trên Windows

**Cách dễ nhất:** double-click **`LiveHub.bat`** → cửa sổ *Kaynt LiveHub* (PySide6) hiện ra:

- Tab **Điều khiển**: bấm **▶ Bắt đầu** để chạy app (tự mở trình duyệt), **■ Dừng** để tắt gọn (ngắt các phòng). Có nhật ký, nút mở thư mục log, tạo lối tắt Desktop.
- Tab **Phòng**: thêm / xoá phòng, *Kết nối / Dừng tất cả*. Danh sách phòng được **ghi nhớ** (`data/settings.json`); khi TikTok phát `ConnectEvent`, room ID server trả về cũng được lưu vào cấu hình phòng đó.
- Tab **Cài đặt**: **sessionid** (+ tt-target-idc, chế độ dùng, ô đồng ý), **API key Euler Stream**, **mật khẩu truy cập qua WiFi**, tuỳ chọn khởi động (tự kết nối phòng đã lưu, tự mở trình duyệt, tự bắt đầu khi mở cửa sổ). Giá trị ở đây được ưu tiên hơn `.env`.
- Đóng cửa sổ khi app đang chạy → thu xuống **khay hệ thống**; chuột phải biểu tượng → *Thoát* để tắt hẳn.

Lần đầu `LiveHub.bat` tự tạo `.venv` (Python 3.11) và cài thư viện (PySide6 ~200 MB nên hơi lâu).

Chạy kiểu cũ (cửa sổ đen, không có cửa sổ điều khiển):

```bat
LiveHub.bat console
```

Hoặc chạy tay:

```bash
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

## Chạy trên Linux (không giao diện)

Không cần cửa sổ điều khiển, không cần bấm Bắt đầu: chạy là tự bật server web **và tự kết nối mọi phòng đã lưu**.
Cần Python ≥ 3.11. Cài thư viện 1 lần (không cần PySide6):

```bash
pip install "TikTokLive==7.0.1" "Flask>=3.0" "flask-sock>=0.7" "httpx>=0.27" "python-dotenv>=1.0"
```

```bash
python3 headless.py                                # chạy, tự kết nối phòng đã lưu
python3 headless.py --room fm.psycho,eclipse.fm2   # thêm phòng (lưu vào data/settings.json cho lần sau)
python3 headless.py --list                         # xem phòng đã lưu
python3 headless.py --remove fm.spacex             # xoá phòng
python3 headless.py --port 8080 --host 127.0.0.1   # đổi cổng / chỉ cho máy này truy cập
python3 headless.py --no-connect                   # chỉ bật server, kết nối phòng sau trên web
```

Dừng bằng **Ctrl+C** hoặc `kill` – các phòng được ngắt gọn.
Mỗi 5 phút in tình trạng các phòng ra màn hình (`--status-every 60` để đổi, `0` để tắt).
sessionid / API key / mật khẩu lấy từ `.env` và `data/settings.json` như bản Windows (có thể copy nguyên `data/settings.json` từ máy Windows sang).
Mở cho máy khác vào (`HOST=0.0.0.0`) thì **phải đặt `ACCESS_PASSWORD`** trong `.env`; người dùng sẽ thấy trang đăng nhập Kaynt LiveHub thay cho hộp thoại Basic Auth của trình duyệt. Đặt thêm `SECRET_KEY` ổn định để giữ phiên qua lần khởi động lại; đặt `SESSION_COOKIE_SECURE=true` khi chạy sau HTTPS.

**Chạy nền, tự bật khi khởi động máy** (systemd): sửa `User` và đường dẫn trong `livehub.service`, rồi

```bash
sudo cp livehub.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now livehub
journalctl -u livehub -f                  # xem log
```

## Cấu hình

Cấu hình thường dùng (sessionid, API key, mật khẩu WiFi, danh sách phòng) nhập trong **tab Cài đặt / Phòng** của cửa sổ Kaynt LiveHub. File **`.env`** (mẫu: `.env.example`) vẫn dùng được cho các tuỳ chọn nâng cao bên dưới; ô nào trên giao diện để trống thì lấy từ `.env`.

### Xem qua WiFi (điện thoại / máy khác)

Mặc định `HOST=0.0.0.0`: khi chạy, cửa sổ đen in ra link dạng `http://192.168.x.x:5000`, trên web có nút **📶** để copy link.

1. **Đặt `ACCESS_PASSWORD`** trong `.env`. Khi mở link, tất cả thiết bị (kể cả trình duyệt chạy trên máy chủ) đăng nhập qua trang Kaynt LiveHub.
2. Lần đầu Windows hỏi quyền mạng cho Python → chọn **Private networks**. Nếu lỡ bấm Cancel hoặc máy khác không vào được: bấm **Mở tường lửa cho WiFi** trong cửa sổ Kaynt LiveHub (tự xin quyền Admin, mở cổng cho mạng Private) và đảm bảo WiFi đang để **Private network**.
3. Chỉ muốn dùng trên máy này: đặt `HOST=127.0.0.1`.

Ghi chú: mọi người xem chung một bộ phòng (ai thêm/đóng phòng thì người khác cũng thấy). Mỗi thiết bị xem video = một luồng tải thêm qua máy chạy app. iPhone (Safari) hiện chưa phát được video FLV – bình luận, quà, thống kê vẫn xem bình thường; Android / iPad / máy tính xem được cả video.

### API key Euler Stream (`SIGN_API_KEY`)

TikTokLive cần máy chủ ký Euler Stream để kết nối. Không có key thì dùng gói miễn phí, dễ bị giới hạn khi theo dõi nhiều phòng.
Tạo key tại https://www.eulerstream.com → dán vào `SIGN_API_KEY=` trong `.env` → bấm nút **🔑 API key** trên thanh trên cùng để tải lại (không cần tắt app) → **Kết nối lại** các phòng.

### sessionid – xem live giới hạn độ tuổi

1. Mở Chrome đã đăng nhập tiktok.com → F12 → **Application → Cookies → https://www.tiktok.com**.
2. Copy `sessionid` → `TIKTOK_SESSIONID`, `tt-target-idc` → `TIKTOK_TARGET_IDC`.
3. Bỏ `#` ở dòng `WHITELIST_AUTHENTICATED_SESSION_ID_HOST=api.eulerstream.com` (bắt buộc – xem cảnh báo bên dưới).
4. Bấm nút **sessionid** trên thanh trên cùng để tải lại cấu hình (không cần tắt app), rồi **Kết nối lại** phòng cần xem.

`TIKTOK_SESSION_MODE`: `auto` (mặc định – chỉ dùng khi phòng bị giới hạn độ tuổi), `always`, `off`. Phòng đang dùng sessionid có biểu tượng 🔐 trên tab.

> ⚠ TikTokLive gửi sessionid tới máy chủ ký **Euler Stream** để ký kết nối. sessionid cho toàn quyền truy cập tài khoản → nên dùng **tài khoản phụ**, không commit `.env`, và nhớ đặt `ACCESS_PASSWORD` khi mở app qua WiFi. sessionid hết hạn khi đăng xuất khỏi trình duyệt.

### Biến khác

| Biến | Ý nghĩa |
|---|---|
| `PORT` / `HOST` | Cổng / địa chỉ web (mặc định `5000` / `0.0.0.0` = mở cho WiFi). |
| `TIKTOK_PROXY` | Proxy đi ra cho kết nối HTTP/WebSocket TikTok, tải video và yêu cầu quản trị; hỗ trợ `http://`, `https://`, `socks5://`. Để trống để kết nối trực tiếp. |
| `SECRET_KEY` | Khoá bí mật ký cookie đăng nhập; tạo bằng `python -c "import secrets; print(secrets.token_hex(32))"` và giữ kín, ổn định trên VPS. |
| `SESSION_COOKIE_SECURE` | Đặt `true` nếu truy cập qua HTTPS để cookie chỉ được gửi trên kết nối bảo mật. |
| `MAX_ROOMS` | Số phòng tối đa theo dõi cùng lúc (mặc định `12`). |
| `RESUME_AUTO_MINUTES` | Kết nối lại khi phòng mới ngừng hoạt động ≤ số phút này → tự nối tiếp phiên cũ (mặc định `60`). |
| `RESUME_ASK_MINUTES` | Lâu hơn mốc trên → hiện hộp thoại hỏi có đồng bộ phiên cũ không. `0` (mặc định) = luôn hỏi; đặt số phút để quá mốc đó tự tạo phiên mới. |

## Cấu trúc

```
app.py            Flask: trang web, REST API, SSE /api/events, proxy video /video/<q>.flv
live_manager.py   Chạy TikTokLiveClient trong asyncio loop riêng, gom sự kiện + thống kê
templates/        index.html
static/           app.js, style.css, vendor/mpegts.js
```

API:
- `GET /api/state` – tất cả phòng · `GET /api/events` – SSE, mỗi tin có `room`
- `POST /api/rooms {unique_id, auto_reconnect}` – thêm phòng · `DELETE /api/rooms/<uid>` – đóng phòng
- `POST /api/rooms/<uid>/reconnect` · `/disconnect` · `POST /api/start_all` · `POST /api/stop_all`
- `GET /video/<uid>/<quality>.flv` – proxy video · `WS /ws/video/<uid>/<quality>` – video qua WebSocket

### Thử nghiệm kết nối trực tiếp TikTok LIVE

Probe dùng `TikTokLiveClient`, đặt session ID và IDC từ `test.env`, rồi chờ
`ConnectEvent`. Không gửi comment hay thực hiện hành động khác trong phòng.
`test.env` được Git bỏ qua; không chia sẻ hoặc commit cookie. Có thể đặt `TIKTOK_PROXY` trong file này để probe kết nối cũng đi qua proxy.

```bat
.venv\Scripts\python.exe tests\test_tiktok_direct_connection_probe.py
```

Để WebSocket đã đăng nhập hoạt động, script cho phép TikTokLive gửi sessionID
tới `api.eulerstream.com` để ký. Không gửi comment hay thực hiện hành động khác.

Chạy unit test (không gửi request):

```bat
.venv\Scripts\python.exe -m unittest discover -s tests
```

Probe gửi bình luận thủ công (riêng biệt với probe kết nối) vẫn có các chế độ
direct và Euler. Chỉ khi chủ live chủ động muốn gửi comment thử, chạy một trong
hai lệnh sau:

```bat
.venv\Scripts\python.exe tests\live_comment_probe.py --mode direct --send
.venv\Scripts\python.exe tests\live_comment_probe.py --mode euler --send
```

`direct` kết nối live qua TikTokLive, xác nhận room ID, đợi 2 giây rồi POST
trực tiếp tới TikTok bằng cookie `sessionid` và `tt-target-idc`; phần gửi comment không
đi qua Euler. Quá trình kết nối TikTokLive có thể cần sign server cho websocket.
`euler` dùng route TikTokLive/Euler để so sánh và yêu cầu đặt
`ALLOW_EULER_SESSION=I_UNDERSTAND` cùng API key. HTTP 200 với response rỗng
không xác nhận comment đã xuất hiện trên live.

## Lưu ý

- Khi triển khai VPS, đặt `HOST=127.0.0.1` nếu dùng Nginx/Caddy làm reverse proxy, cấu hình HTTPS ở reverse proxy, đặt `SESSION_COOKIE_SECURE=true`, và đặt `ACCESS_PASSWORD` cùng `SECRET_KEY` mạnh trong `.env`. Không mở trực tiếp cổng Flask ra Internet nếu không cần.
- Proxy TikTok có thể khai báo trong `.env` bằng `TIKTOK_PROXY`; mọi kết nối mới sẽ dùng proxy này cho HTTP, WebSocket và luồng video. Ví dụ có xác thực: `http://user:password@host:port` (mã hoá ký tự đặc biệt trong username/password theo URL).

- Mỗi ô video trong lưới là một luồng tải riêng từ CDN → nhiều phòng thì tốn mạng. Để chất lượng lưới ở **Thấp**, hoặc tắt "Phát video trong lưới" (vẫn nhận bình luận/quà/thống kê bình thường). Khi mở tab một phòng, video trong lưới tự tắt.
- Tất cả phòng dùng chung máy chủ ký Euler Stream (miễn phí có giới hạn): thêm nhiều phòng cùng lúc có thể bị rate-limit → đặt `SIGN_API_KEY`.
- Video dùng H.264 → cần Chrome/Edge/Firefox bản thường (có codec).
