# Z·ARMOR — Deploy Guide: `zone_control.html`

## Tổng quan

`zone_control.html` là file HTML đơn — **không cần build, không cần npm, không cần framework**.  
Deploy = copy 1 file lên server + mở bằng browser.

---

## Yêu cầu

| Mục | Yêu cầu |
|-----|---------|
| Server | Windows với pm2 đang chạy FastAPI tại `http://47.129.243.206:8000` |
| Admin Token | Token đã set trong FastAPI (`X-Admin-Token` header) |
| Browser | Chrome / Edge / Firefox (bất kỳ modern browser) |
| Network | Máy tính có thể reach `47.129.243.206:8000` |

---

## Phương án 1 — Serve qua FastAPI (khuyến nghị)

### Bước 1: Copy file lên server

```powershell
# Từ máy local — dùng SCP hoặc WinSCP
scp zone_control.html user@47.129.243.206:C:\zarmor\static\zone_control.html
```

Hoặc dùng **WinSCP**: kéo thả file vào thư mục `C:\zarmor\static\`

### Bước 2: Kiểm tra FastAPI có mount static files không

Mở `main.py`, tìm đoạn:

```python
from fastapi.staticfiles import StaticFiles
app.mount("/static", StaticFiles(directory="static"), name="static")
```

Nếu **chưa có**, thêm vào sau dòng `app = FastAPI(...)`:

```python
import os
from fastapi.staticfiles import StaticFiles

static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")
```

### Bước 3: Tạo thư mục static nếu chưa có

```powershell
# Trên server Windows
mkdir C:\zarmor\static
```

### Bước 4: Restart pm2

```powershell
pm2 restart zarmor
pm2 logs zarmor --lines 20
```

### Bước 5: Mở trên browser

```
http://47.129.243.206:8000/static/zone_control.html
```

Nhập **Admin Token** khi được hỏi → dashboard load.

---

## Phương án 2 — Mở trực tiếp từ file (local admin)

> Dùng khi chỉ admin dùng, không cần public access.

1. Copy `zone_control.html` về máy admin
2. Mở bằng Chrome: `Ctrl+O` → chọn file  
   hoặc double-click file
3. **Vấn đề CORS**: Browser mở từ `file://` sẽ bị CORS block khi gọi API

**Fix CORS cho Phương án 2** — Mở Chrome với flag:

```powershell
# Windows — tạo shortcut Chrome với flag
"C:\Program Files\Google\Chrome\Application\chrome.exe" --disable-web-security --user-data-dir="C:\ChromeDev"
```

Sau đó mở file từ Chrome này → API calls sẽ hoạt động.

---

## Phương án 3 — Nginx reverse proxy (production)

Nếu server có Nginx:

```nginx
server {
    listen 80;
    server_name admin.yourdomain.com;

    # Basic auth bảo vệ admin
    auth_basic "Z-ARMOR Admin";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        root /var/www/zarmor-admin;
        index zone_control.html;
        try_files $uri $uri/ =404;
    }

    location /api/ {
        proxy_pass http://47.129.243.206:8000;
        proxy_set_header Host $host;
    }
}
```

---

## Cấu hình sau khi mở

### 1. Nhập Admin Token

- Lần đầu mở: browser hỏi token
- Token được lưu vào `localStorage` → không cần nhập lại
- Xóa token: mở DevTools → Application → Local Storage → xóa `zc_tok`

### 2. Reset nếu có lỗi Zone cũ

File tự động detect nếu bạn có zone config cũ (Trial/Standard/Pro từ version trước) và reset sang 3 gói mới:

- **Radar Trial** — Free, 7 ngày
- **Radar Pro** — $49/tháng  
- **Strategic Partner** — Application only

Toast vàng sẽ hiện: *"Zone config migrated → new 3-tier pricing"*

### 3. Kiểm tra kết nối server

Topbar góc phải:
- 🟢 **LIVE** = server `47.129.243.206:8000` đang chạy
- 🔴 **OFFLINE** = kiểm tra pm2 trên server

```powershell
# Kiểm tra server
pm2 list
pm2 logs zarmor --lines 30
```

---

## Cấu trúc các Views

| Tab | Chức năng |
|-----|-----------|
| **Command Overview** | KPIs tổng hợp: licenses, MRR, leads, gateways |
| **Zone Control** | Bật/tắt 3 gói bán hàng · Quota · Pool keys |
| **Payment Gateways** | Stripe / PayOS / Crypto toggle |
| **Key Inventory** | License key table · Issue · Revoke · Bulk generate |
| **Transactions** | Payment history · Refunds |
| **Radar Funnel** | ← **MỚI** — Lead captures từ scan.html · Conversion funnel |
| **Audit Log** | Mọi thao tác admin được log |

---

## API Endpoints cần có trên server

Zone Control gọi các endpoints này. Nếu chưa có → data sẽ hiện `—` (không crash).

### Đã có (từ các session trước):
```
GET  /health
GET  /admin/stats
GET  /admin/licenses
POST /admin/licenses
POST /admin/licenses/{key}/revoke
POST /admin/licenses/{key}/activate
POST /admin/licenses/bulk-generate
GET  /admin/transactions
POST /admin/transactions/{id}/refund
GET  /radar/feed
```

### Cần thêm (cho Radar Funnel):
```
GET  /api/email-captures?limit=200    → leads từ scan.html
GET  /api/track-share?limit=50        → share events
GET  /admin/stats/scans               → tổng scan count
GET  /admin/stats/assets              → top assets by volume
POST /admin/zones/sync                → sync zone config
POST /admin/zones/master              → master switch
POST /admin/zones/save-all            → save all zones
```

> **Nếu chưa build các Funnel endpoints**: Tab Radar Funnel sẽ hiện `—` cho các KPIs, không ảnh hưởng các tab khác.

---

## Bảo mật

| Việc cần làm | Trạng thái |
|--------------|------------|
| Đổi `EA_HMAC_SALT` sang secret thật | ⬜ PENDING |
| Đặt Admin Token mạnh (không dùng `admin123`) | ⬜ Check ngay |
| Không expose `zone_control.html` ra public URL | ⬜ Dùng basic auth hoặc IP whitelist |
| HTTPS cho production | ⬜ Sau khi có domain |

---

## Quy trình deploy đầy đủ (checklist)

```
□ 1. Copy zone_control.html → server C:\zarmor\static\
□ 2. Đảm bảo FastAPI mount /static (xem main.py)
□ 3. pm2 restart zarmor
□ 4. Mở http://47.129.243.206:8000/static/zone_control.html
□ 5. Nhập Admin Token
□ 6. Kiểm tra server LED → LIVE (xanh)
□ 7. Vào Zone Control → xác nhận 3 gói mới hiện đúng
□ 8. Master Sales Switch → bật ON
□ 9. Kiểm tra Radar Trial, Radar Pro, Strategic Partner đều LIVE
□ 10. Vào Radar Funnel → leads từ scan.html sẽ hiện khi có data
```

---

## Troubleshooting

| Triệu chứng | Nguyên nhân | Fix |
|-------------|-------------|-----|
| Blank page | JS error | Mở DevTools (F12) → Console |
| Server LED đỏ | FastAPI offline | `pm2 restart zarmor` |
| Token không hoạt động | Sai token | Xóa localStorage → nhập lại |
| Zone hiện 3 gói cũ | localStorage cũ | Xóa `zc_zones` trong DevTools → reload |
| API calls 403 | Token không match | Kiểm tra `X-Admin-Token` trong FastAPI |
| CORS error (file://) | Browser security | Dùng Phương án 1 (serve qua FastAPI) |
