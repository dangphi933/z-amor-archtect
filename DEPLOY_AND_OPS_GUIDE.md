# Z-ARMOR CLOUD — Hướng dẫn Deploy & Flow Vận hành License

> Phiên bản: V8.3 (sau Giai đoạn 3 hoàn tất)  
> Cập nhật: 2026-03-07

---

## PHẦN 1 — DANH SÁCH FILE VÀ VỊ TRÍ DEPLOY

### Cấu trúc thư mục đích trên server `47.129.1.31`

```
Z-ARMOR-CLOUD/
├── main.py                      ← Core app (V8.3)
├── database.py                  ← Models + atomic_bind_license
├── license_service.py           ← License engine (dùng Redis)
├── auth_service.py              ← JWT auth (R-01)
├── cache_service.py             ← Redis cache wrapper (R-04)
├── webhook_retry.py             ← Retry queue (R-15/4.3)
├── audit_trail.py               ← Config audit (4.3)
├── monitoring.py                ← Prometheus metrics (R-11/4.3)
│
├── api/
│   ├── ea_router.py             ← (không đổi)
│   ├── dashboard_service.py     ← (không đổi)
│   ├── config_manager.py        ← (không đổi)
│   ├── schemas.py               ← (không đổi)
│   └── ai_guard_logic.py        ← (không đổi)
│
├── alembic/
│   ├── env.py                   ← Copy từ alembic_env.py
│   └── versions/                ← Auto-generated migration files
├── alembic.ini                  ← Auto-generated bởi alembic init
│
├── scripts/
│   ├── backup.sh                ← Daily pg_dump
│   ├── alembic_setup.sh         ← Chạy 1 lần
│   └── partition_trade_history.sql ← Chạy khi > 100k rows
│
└── .env                         ← Secrets (không commit git)
```

---

## PHẦN 2 — THỨ TỰ DEPLOY (QUAN TRỌNG — làm đúng thứ tự)

### BƯỚC 0 — Backup trước khi deploy

```bash
# Backup DB hiện tại trước khi thay đổi bất cứ thứ gì
pg_dump -U zarmor zarmor_db | gzip > /backup/pre_deploy_$(date +%Y%m%d).sql.gz
echo "✅ Backup OK"
```

---

### BƯỚC 1 — Cài dependencies mới

```bash
cd Z-ARMOR-CLOUD
pip install \
  python-jose[cryptography] \
  passlib[bcrypt] \
  redis \
  alembic \
  prometheus-client \
  --quiet

echo "✅ Dependencies OK"
```

---

### BƯỚC 2 — Cài và khởi động Redis

```bash
# Cài Redis (Ubuntu)
sudo apt install redis-server -y
sudo systemctl enable redis-server
sudo systemctl start redis-server

# Test
redis-cli ping   # → PONG
echo "✅ Redis OK"
```

---

### BƯỚC 3 — Cập nhật file `.env`

Thêm các biến mới vào `.env` (không xóa biến cũ):

```bash
# .env — thêm vào cuối file

# JWT Auth (R-01)
JWT_SECRET_KEY=$(openssl rand -hex 32)   # CHẠY LỆNH NÀY để tạo key thật
JWT_ACCESS_TTL_MINUTES=1440
JWT_REFRESH_TTL_DAYS=30
ADMIN_EMAIL=admin@yourcompany.com

# Redis (R-04)
REDIS_URL=redis://127.0.0.1:6379/0
REDIS_PASSWORD=

# Workers (R-10)
UVICORN_WORKERS=4

# Backup (4.3)
BACKUP_DIR=/backup/zarmor
PGPASSWORD=Zarmor@2025
TELEGRAM_BOT_TOKEN=          # tuỳ chọn — để trống nếu không muốn notify
TELEGRAM_CHAT_ID=            # tuỳ chọn
```

> ⚠️ **Quan trọng:** Chạy `openssl rand -hex 32` để tạo JWT_SECRET_KEY thật. Không dùng giá trị mặc định.

---

### BƯỚC 4 — Deploy các file mới lên server

```bash
# Từ máy local, scp lên server
scp main.py \
    database.py \
    license_service.py \
    auth_service.py \
    cache_service.py \
    webhook_retry.py \
    audit_trail.py \
    monitoring.py \
    user@47.129.1.31:~/Z-ARMOR-CLOUD/

# Tạo thư mục scripts nếu chưa có
ssh user@47.129.1.31 "mkdir -p ~/Z-ARMOR-CLOUD/scripts"

scp backup.sh \
    alembic_env.py \
    alembic_setup.sh \
    partition_trade_history.sql \
    user@47.129.1.31:~/Z-ARMOR-CLOUD/scripts/

# Cấp quyền execute
ssh user@47.129.1.31 "chmod +x ~/Z-ARMOR-CLOUD/scripts/*.sh"
```

---

### BƯỚC 5 — Chạy Alembic migration (tạo bảng mới)

```bash
ssh user@47.129.1.31
cd Z-ARMOR-CLOUD

# Setup Alembic (chỉ lần đầu)
chmod +x scripts/alembic_setup.sh
./scripts/alembic_setup.sh

# Copy env.py vào alembic/
cp scripts/alembic_env.py alembic/env.py

# Tạo migration file cho schema V1.1
alembic revision --autogenerate -m "phase2_phase3_schema"

# Xem nội dung migration trước khi apply
cat alembic/versions/*phase2_phase3_schema*.py

# Apply migration (tạo AdminUser, WebhookRetryQueue, ConfigAuditTrail, indexes mới)
alembic upgrade head

# Kiểm tra
alembic current
echo "✅ Migration OK"
```

---

### BƯỚC 6 — Tạo admin user đầu tiên

```bash
# Tạo admin password hash bằng Python
python3 -c "
from passlib.context import CryptContext
pwd = CryptContext(schemes=['bcrypt'], deprecated='auto')
hash = pwd.hash('YOUR_ADMIN_PASSWORD')
print(f'Hash: {hash}')
"

# Insert vào DB
psql -U zarmor -d zarmor_db -c "
INSERT INTO admin_users (email, password_hash, is_active)
VALUES ('admin@yourcompany.com', 'PASTE_HASH_HERE', true)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;
"
echo "✅ Admin user OK"
```

---

### BƯỚC 7 — Restart server

```bash
# Restart với pm2
pm2 restart z-armor-core

# Xem log ngay sau restart
pm2 logs z-armor-core --lines 50

# Verify
curl http://localhost:8000/api/health
# Expected: {"status":"ok","version":"8.3.0","cache":{"backend":"redis","connected":true},"auth":"jwt"}
```

---

### BƯỚC 8 — Setup backup cron

```bash
# Thêm vào crontab — backup 3:00 AM mỗi ngày
crontab -e

# Thêm dòng này:
0 3 * * * /home/user/Z-ARMOR-CLOUD/scripts/backup.sh >> /var/log/zarmor-backup.log 2>&1

# Test chạy thử
./scripts/backup.sh
ls /backup/zarmor/
echo "✅ Backup cron OK"
```

---

### BƯỚC 9 — Kiểm tra toàn bộ sau deploy

```bash
# 1. Health check
curl http://localhost:8000/api/health

# 2. Login admin
curl -X POST http://localhost:8000/admin/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@yourcompany.com","password":"YOUR_ADMIN_PASSWORD"}'
# → {"access_token":"...","token_type":"bearer"}

# 3. Kiểm tra retry queue
curl http://localhost:8000/admin/retry-queue \
  -H "X-Admin-Token: YOUR_ADMIN_TOKEN"

# 4. Kiểm tra Prometheus metrics
curl http://localhost:8000/metrics | grep zarmor_

# 5. Test trader login
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"trader@gmail.com","license_key":"ZARMOR-XXXXX-XXXXX"}'
# → {"access_token":"...","accounts":["413408816"]}
```

---

## PHẦN 3 — FLOW VẬN HÀNH LICENSE SAU GIAI ĐOẠN 3

### 3.1 Toàn cảnh kiến trúc License Engine V8.3

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Z-ARMOR CLOUD V8.3                              │
│                                                                         │
│  ┌──────────┐    HTTPS     ┌──────────────────────────────────────┐    │
│  │  EA/MT5  │ ──────────── │           FastAPI (workers=4)         │    │
│  │ (Trader) │              │                                        │    │
│  └──────────┘              │  ┌────────────┐  ┌─────────────────┐ │    │
│                            │  │auth_service│  │ license_service │ │    │
│  ┌──────────┐    HTTPS     │  │  JWT R-01  │  │  process_hb()   │ │    │
│  │Dashboard │ ──────────── │  │  /auth/*   │  │  auto-bind      │ │    │
│  │   (FE)   │              │  └─────┬──────┘  └────────┬────────┘ │    │
│  └──────────┘              │        │                   │          │    │
│                            │  ┌─────▼───────────────────▼────────┐ │    │
│  ┌──────────┐    HTTPS     │  │         cache_service             │ │    │
│  │  Admin   │ ──────────── │  │  Redis: hb_rate | machines | owner│ │    │
│  │ Panel    │              │  └───────────────────────────────────┘ │    │
│  └──────────┘              └─────────────────┬────────────────────┘    │
│                                              │                          │
│            ┌────────────────────────────────▼────────────────────┐    │
│            │                  PostgreSQL                          │    │
│            │  license_keys | license_activations | trade_history  │    │
│            │  admin_users  | webhook_retry_queue  | config_audit  │    │
│            └─────────────────────────────────────────────────────┘    │
│                                                                         │
│  Background Tasks:                                                      │
│  • _rollover_loop (60s): daily rollover + expire job                   │
│  • start_retry_worker (15s): Lark/Email retry queue                    │
│  • backup.sh (cron 3AM): pg_dump daily                                 │
└─────────────────────────────────────────────────────────────────────────┘
```

---

### 3.2 Flow chi tiết — Checkout & Cấp License

```
Customer nhấn "Dùng thử miễn phí"
         │
         ▼
POST /api/checkout  {method: "TRIAL_FREE", email: "...", tier: "STARTER"}
         │
         ├── [R-18] Kiểm tra TRIAL_MAX_PER_EMAIL (max 1 lần/email)
         │         ↳ Nếu đã dùng: 400 "Trial limit reached"
         │
         ├── [R-15] enqueue(LARK_ORDER) → webhook_retry_queue
         │         ↳ Retry 5 lần nếu Lark API fail (30s→2m→10m→30m→2h)
         │         ↳ KHÔNG block checkout
         │
         ├── Tạo license_key = "ZARMOR-XXXXX-XXXXX"
         │   status=ACTIVE, is_trial=True, expires_at=NOW+7d
         │   bound_mt5_id=NULL  ← chưa bind, chờ EA connect
         │
         ├── [R-15] enqueue(EMAIL_LICENSE) → webhook_retry_queue
         │         ↳ Thử gửi ngay; nếu fail → retry tự động
         │
         └── Response: {"status":"success","license_key":"ZARMOR-...","expires":"..."}
                  ↓
         Customer nhận email chứa license key
```

---

### 3.3 Flow chi tiết — Kích hoạt & Bind

```
Trader mở Dashboard → nhập license key + MT5 account ID → nhấn ACTIVATE
         │
         ▼
POST /api/bind-license  {license_key: "ZARMOR-...", account_id: "413408816"}
         │
         ├── [R-05] atomic_bind_license():
         │    PostgreSQL: UPDATE license_keys
         │                SET bound_mt5_id='413408816', status='ACTIVE'
         │                WHERE license_key='ZARMOR-...' AND bound_mt5_id IS NULL
         │         ↳ rowcount=1 → BOUND_OK (chỉ 1 transaction thắng)
         │         ↳ rowcount=0 → KEY_USED_BY_OTHER (race condition đã xử lý)
         │
         ├── Init unit config (risk_params, neural_profile, telegram_config)
         │
         ├── [R-04] cache.owner_set(account_id, buyer_email) → Redis TTL 1h
         │
         └── Response: {"status":"success","reason":"BOUND_OK"}
                  ↓
         Dashboard hiển thị "License đã kích hoạt. Khởi động EA."
```

---

### 3.4 Flow chi tiết — EA Heartbeat (vòng lặp chính)

```
EA khởi động → gửi GET /heartbeat?license=ZARMOR-...&account=413408816&equity=10000
         │
         ▼
_ea_heartbeat_handler() → process_heartbeat()
         │
         ├── [R-04] cache.hb_is_ratelimited(key)?
         │    ├── YES (< 20s từ lần trước) → {"valid":true,"reason":"OK_CACHED"}  ← ngay lập tức
         │    └── NO → tiếp tục
         │
         ├── DB lookup: SELECT * FROM license_keys WHERE license_key=?
         │
         ├── Status checks:
         │    REVOKED   → {"valid":false,"lock":true,"reason":"LICENSE_REVOKED"}
         │    EXPIRED   → {"valid":false,"lock":true,"reason":"LICENSE_EXPIRED"}
         │    INACTIVE  → {"valid":false,"lock":true,"reason":"LICENSE_INACTIVE"}
         │
         ├── bound_mt5_id IS NULL?
         │    ├── YES + account provided → AUTO-BIND ngay tại đây
         │    │   lic.bound_mt5_id = account, commit
         │    │   cache.owner_set(account, email)
         │    │   ↳ Không còn KEY_NOT_BOUND!
         │    └── NO → tiếp tục
         │
         ├── MT5 ID mismatch?
         │    └── account != bound_mt5_id → {"valid":false,"lock":true,"reason":"MT5_ID_MISMATCH"}
         │
         ├── [R-04] Machine limit: cache.machine_count(key) >= max_machines?
         │    └── YES → {"valid":false,"lock":true,"reason":"MACHINE_LIMIT_REACHED"}
         │
         └── ALL OK → {"valid":true,"reason":"OK","expires_at":"..."}
                  ↓
         EA tiếp tục chạy. Gửi heartbeat lại sau BridgeInterval giây.
```

---

### 3.5 Flow chi tiết — Dashboard Login & Fleet Isolation

```
Trader mở Dashboard → nhập email + license key → Login
         │
         ▼
POST /auth/login  {email: "trader@gmail.com", license_key: "ZARMOR-..."}
         │
         ├── Verify email + license_key trong DB
         ├── Load accounts = [bound_mt5_id] của email này
         ├── Tạo JWT: {sub: email, accounts: ["413408816"], is_admin: false}
         └── Response: {access_token: "eyJ...", accounts: ["413408816"]}
                  ↓
         FE lưu access_token trong memory (không localStorage)
                  ↓
GET /api/init-data?account_id=413408816
Authorization: Bearer eyJ...
         │
         ├── [R-01] Decode JWT → user.accounts = ["413408816"]
         ├── 413408816 in user.accounts? → YES → OK
         └── Response: full dashboard state cho account này
                  ↓
GET /api/my-accounts
Authorization: Bearer eyJ...
         │
         └── filter_units_for_owner(all_units, user.accounts)
             → chỉ trả accounts của user này
             ↳ Không lộ data của trader khác (R-03 fixed)
```

---

### 3.6 Flow chi tiết — Background Jobs

#### Expire Job (mỗi 60 giây)
```
_rollover_loop()
  ├── perform_daily_rollover() → reset daily stats nếu đến giờ
  └── UPDATE license_keys SET status='EXPIRED'
      WHERE status='ACTIVE' AND expires_at < NOW()
      → Không cần chờ heartbeat mới biết hết hạn (R-14 fixed)
```

#### Webhook Retry Worker (mỗi 15 giây)
```
start_retry_worker()
  ├── SELECT top 10 jobs WHERE status='PENDING' AND next_retry_at <= NOW()
  ├── Với mỗi job:
  │    LARK_ORDER     → create_pending_order_in_lark()
  │    LARK_UPDATE    → log_license_to_lark()
  │    EMAIL_LICENSE  → send_license_email_to_customer()
  │    TELEGRAM_ALERT → push_to_telegram()
  │
  ├── SUCCESS → status='SUCCESS', resolved_at=NOW()
  ├── FAIL (attempts < max) → status='PENDING', next_retry = NOW + backoff
  └── FAIL (attempts >= max) → status='DEAD' (admin xem /admin/retry-queue)
```

#### Daily Backup (3:00 AM)
```
backup.sh
  ├── pg_dump zarmor_db | gzip → /backup/zarmor/zarmor_db_YYYY-MM-DD.sql.gz
  ├── Xóa backup > 30 ngày
  └── Notify Telegram (nếu đã config)
```

---

### 3.7 Bảng trạng thái License

| Status | Ý nghĩa | EA heartbeat | Dashboard |
|--------|---------|-------------|-----------|
| `UNUSED` | Vừa tạo, chưa bind | AUTO-BIND khi EA connect lần đầu | Nhập key để kích hoạt |
| `ACTIVE` | Đang hoạt động, đã bind | OK | Xem đầy đủ |
| `EXPIRED` | Hết hạn | Lock EA, trả `LICENSE_EXPIRED` | Nhắc gia hạn |
| `REVOKED` | Admin thu hồi | Lock EA ngay lập tức | Báo lỗi |

---

### 3.8 Bảng endpoint đầy đủ sau V8.3

#### Public (không cần auth)
| Endpoint | Method | Mô tả |
|----------|--------|-------|
| `/auth/login` | POST | Trader đăng nhập, nhận JWT |
| `/auth/refresh` | POST | Làm mới token |
| `/api/checkout` | POST | Mua / dùng thử |
| `/heartbeat` | GET/POST | EA heartbeat |
| `/api/health` | GET | Health check (Redis, version) |

#### Trader (cần JWT Bearer token)
| Endpoint | Method | Mô tả |
|----------|--------|-------|
| `/auth/me` | GET | Thông tin user hiện tại |
| `/api/init-data` | GET | Dashboard state (R-01: check quyền) |
| `/api/my-accounts` | GET | Fleet Overview — chỉ accounts của mình |
| `/api/bind-license` | POST | Kích hoạt license key |
| `/api/update-unit-config` | POST | Sửa risk params (+ ghi audit trail) |
| `/api/panic-kill` | POST | Lock EA |
| `/api/unlock-unit` | POST | Unlock EA |
| `/api/my-audit-trail/{id}` | GET | Lịch sử thay đổi config |

#### Admin (JWT is_admin=true hoặc X-Admin-Token)
| Endpoint | Method | Mô tả |
|----------|--------|-------|
| `/admin/login` | POST | Admin đăng nhập bcrypt (R-02) |
| `/admin/stats` | GET | License stats + online count |
| `/admin/licenses` | GET/POST | CRUD license keys |
| `/admin/licenses/{key}/reset-binding` | POST | Reset binding |
| `/admin/licenses/{key}/reset-machines` | POST | Reset machine list |
| `/admin/retry-queue` | GET | Webhook retry queue status |
| `/admin/retry-queue/flush-dead` | POST | Requeue dead jobs |
| `/admin/audit-trail/{account_id}` | GET | Config audit trail |
| `/metrics` | GET | Prometheus metrics |

---

## PHẦN 4 — KIỂM TRA SỨC KHOẺ HỆ THỐNG

### Checklist hàng ngày (30 giây)

```bash
# 1. Server còn sống không?
curl -s http://47.129.1.31:8000/api/health | python3 -m json.tool

# 2. Redis còn kết nối không? (xem trong response health)
# "cache": {"backend": "redis", "connected": true, "online_now": N}

# 3. Có job DEAD trong retry queue không?
curl -s http://47.129.1.31:8000/admin/retry-queue \
  -H "X-Admin-Token: $ADMIN_TOKEN"
# Nếu có DEAD jobs → /admin/retry-queue/flush-dead để retry lại

# 4. Backup hôm qua có OK không?
ls -lh /backup/zarmor/ | tail -3
```

### Checklist khi có incident

```bash
# EA báo lỗi gì?
pm2 logs z-armor-core --lines 100 | grep "HEARTBEAT\|BIND\|ERROR"

# License key đó đang ở trạng thái gì?
psql -U zarmor -d zarmor_db -c \
  "SELECT license_key, status, bound_mt5_id, expires_at FROM license_keys WHERE license_key='ZARMOR-XXXXX';"

# Reset binding nếu cần
curl -X POST http://47.129.1.31:8000/admin/licenses/ZARMOR-XXXXX/reset-binding \
  -H "X-Admin-Token: $ADMIN_TOKEN"
```

---

## PHẦN 5 — ROLLBACK (nếu có sự cố sau deploy)

```bash
# 1. Rollback code về bản cũ
pm2 stop z-armor-core
cp /backup/pre_deploy_YYYYMMDD_main.py main.py
# ... restore các file khác

# 2. Rollback DB migration 1 bước
alembic downgrade -1
alembic current

# 3. Restart
pm2 start z-armor-core
pm2 logs z-armor-core --lines 20
```

---

*Z-ARMOR CLOUD Architecture Guide — V8.3 — 2026*
