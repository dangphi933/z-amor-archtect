"""
HƯỚNG DẪN TÍCH HỢP VÀO Z-ARMOR-CLOUD
======================================
Thực hiện 4 bước sau:

BƯỚC 1 — Chạy Migration SQL
───────────────────────────
psql -U postgres
\c zarmor_db
\i migration_radar.sql
\q

BƯỚC 2 — Copy module
──────────────────────
Tạo folder: Z-ARMOR-CLOUD\radar\
Copy vào:   radar\__init__.py
            radar\engine.py
            radar\schemas.py
            radar\router.py

BƯỚC 3 — Patch main.py (thêm 2 dòng)
──────────────────────────────────────
Tìm dòng:   from webhook_retry import ...
Thêm sau:   from radar.router import router as radar_router

Tìm dòng:   app.include_router(auth_router ...)
Thêm sau:   app.include_router(radar_router, prefix="/radar")

BƯỚC 4 — Append vào email_service.py
──────────────────────────────────────
Mở email_service.py, paste toàn bộ nội dung
email_service_radar_addon.py vào cuối file.

BƯỚC 5 — Embed widget vào salemain.html
─────────────────────────────────────────
Copy nội dung radar_widget.html vào salemain.html
trước thẻ </body>

BƯỚC 6 — Restart
─────────────────
python ZARMOR_START.py

TEST:
curl -X POST http://localhost:8000/radar/scan ^
  -H "Content-Type: application/json" ^
  -d "{\"asset\":\"GOLD\",\"timeframe\":\"H1\"}"

Expected: JSON với scan_id, score (0-100 integer), regime, breakdown...
"""

# ════════════════════════════════════════════════════════
# ĐOẠN CODE THÊM VÀO main.py
# ════════════════════════════════════════════════════════

# Thêm vào phần IMPORTS (sau webhook_retry):
"""
from radar.router import router as radar_router
"""

# Thêm vào phần ROUTERS (sau auth_router hoặc cuối cùng):
"""
app.include_router(radar_router, prefix="/radar")
"""
