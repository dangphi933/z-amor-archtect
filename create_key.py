from database import SessionLocal, License
import uuid

db = SessionLocal()
key = "ZARMOR-" + uuid.uuid4().hex[:5].upper() + "-" + uuid.uuid4().hex[:5].upper()
lic = License(
    license_key  = key,
    tier         = "standard",
    status       = "ACTIVE",
    buyer_email  = "admin@zarmor.com",
    bound_mt5_id = None,
    expires_at   = None,
    max_machines = 3,
)
db.add(lic)
db.commit()
print("KEY: " + key)
db.close()
input("Nhan Enter de thoat...")
```

**Bước 3** — Lưu file: `Ctrl+S` → OK

**Bước 4** — Quay lại cmd, gõ:
