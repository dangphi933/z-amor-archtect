# Z-ARMOR CLOUD — PART 1 DEPLOY GUIDE
## Cleanup · Alembic Migrations · CI/CD

> **Nguyên tắc Part 1:** KHÔNG thay đổi business logic — chỉ refactor cấu trúc.
> EA clients live KHÔNG bị gián đoạn trong suốt quá trình.

---

## NHÓM A — Cleanup Monolith (Tuần 1, Ngày 1-4)

### Bước 1: Upload files mới lên server

```powershell
# Từ máy local, copy lên server
scp main.py Administrator@47.129.243.206:C:\Users\Administrator\Desktop\Z-ARMOR-CLOUD\
scp scripts/cleanup_hotfixes.py Administrator@47.129.243.206:C:\Users\Administrator\Desktop\Z-ARMOR-CLOUD\scripts\
scp .env.example Administrator@47.129.243.206:C:\Users\Administrator\Desktop\Z-ARMOR-CLOUD\
scp .gitignore Administrator@47.129.243.206:C:\Users\Administrator\Desktop\Z-ARMOR-CLOUD\
```

### Bước 2: Dry-run cleanup (xem trước, không xóa)

```bash
cd C:\Users\Administrator\Desktop\Z-ARMOR-CLOUD
python3 scripts/cleanup_hotfixes.py --dry-run
```

Đọc output, xác nhận không có gì bất ngờ.

### Bước 3: Inspect các INSPECT files thủ công

```bash
# 3 files cần inspect trước khi xóa:
python3 -c "import ast; print(ast.dump(ast.parse(open('fix_final.py').read())))"
python3 -c "import ast; print(ast.dump(ast.parse(open('fix_lark_payload.py').read())))"
python3 -c "import ast; print(ast.dump(ast.parse(open('fix_webhook_tg.py').read())))"

# Check logic đã có trong source chưa:
grep -n "lark_payload\|send_lark\|lark_service" api/*.py
grep -n "webhook_retry\|tg_send" api/*.py
```

### Bước 4: Apply cleanup

```bash
python3 scripts/cleanup_hotfixes.py --apply
```

### Bước 5: Xóa SQLite remnant (A.6)

```bash
# Kiểm tra không còn code nào dùng SQLite
grep -rn "Z-Armor.db\|sqlite\|SQLite" . --include="*.py" | grep -v .git

# Thêm vào .gitignore (đã có trong file mới)
# Xóa file nếu tồn tại
git rm --cached Z-Armor.db 2>/dev/null || true
git rm --cached logs/Z-Armor.db 2>/dev/null || true
```

### Bước 6: Deploy main.py mới và restart

```bash
# main.py đã fix: IP hardcode → env var, /health endpoint nâng cấp
pm2 restart zarmor
sleep 5
curl http://localhost:8000/health
# Expected: {"status": "healthy", "checks": {"database": "ok", "redis": "ok"}, ...}
```

### Checklist A:
- [ ] `git ls-files | grep "fix_\|hotfix\|patch_main"` → 0 files
- [ ] `git ls-files | grep "\.bak\|\.backup"` → 0 files
- [ ] `grep -rn "47\.129\." web/ *.html *.js main.py` → 0 matches
- [ ] `curl localhost:8000/health` → HTTP 200 với `"database": "ok"`
- [ ] `python3 -c "from main import app"` → no errors

---

## NHÓM B — Alembic Migrations (Tuần 1, Ngày 3-5)

### Bước 1: Upload Alembic files

```powershell
scp alembic.ini Administrator@47.129.243.206:...
scp -r migrations/ Administrator@47.129.243.206:.../migrations/
```

### Bước 2: Cài Alembic

```bash
pip install alembic==1.13.3 python-dotenv
```

### Bước 3: Verify env.py load đúng DB

```bash
# Test kết nối DB
python3 -c "
from migrations.env import SYNC_URL
print('SYNC_URL:', SYNC_URL[:50] + '...')
"
```

### Bước 4: Stamp production DB (ĐÃ có schema → không chạy upgrade)

```bash
# Production DB đã có schema từ storage_v83_full.sql + các migration SQL cũ
# Chỉ cần đánh dấu "đã ở version này"
alembic stamp head

# Verify:
alembic current
# Expected: 009_partition_trade (head)
```

### Bước 5: Test trên fresh DB (staging hoặc DB test)

```bash
# Tạo DB test
psql -U postgres -c "CREATE DATABASE zarmor_test OWNER zarmor;"

# Chạy toàn bộ migrations từ đầu
DATABASE_URL="postgresql+psycopg2://zarmor:Zarmor%402025@127.0.0.1:5432/zarmor_test" \
  alembic upgrade head

# Kiểm tra kết quả
alembic history --verbose
alembic check  # không báo pending migrations
```

### Bước 6: Test downgrade cycle

```bash
# Test rollback hoạt động
alembic downgrade -1
alembic upgrade head
echo "✅ Downgrade cycle passed"
```

### Bước 7: Setup auto-create partition (cron)

```bash
# Thêm vào Windows Task Scheduler hoặc cron:
# 0 0 1 * * python3 /opt/zarmor/scripts/create_partition.py

# Test thủ công:
python3 scripts/create_partition.py
```

### Checklist B:
- [ ] `alembic current` → không báo lỗi
- [ ] `alembic history --verbose` → 9 migrations theo thứ tự
- [ ] `alembic upgrade head` trên fresh DB → thành công < 60s
- [ ] `alembic downgrade -1 && alembic upgrade head` → thành công
- [ ] `alembic check` → không báo pending migrations
- [ ] 9 file SQL cũ move vào `docs/legacy_sql/` (giữ để reference)
- [ ] `\d+ trade_history` trong psql → "Partitioned table"

---

## NHÓM C — CI/CD Pipeline (Tuần 2, Ngày 1-5)

### Bước 1: Upload GitHub Actions files

```bash
git add .github/workflows/pr.yml
git add .github/workflows/deploy.yml
git add pyproject.toml
git add .pre-commit-config.yaml
git add tests/
git commit -m "ci: add GitHub Actions PR + deploy pipelines — Part 1 Group C"
git push origin main
```

### Bước 2: Cấu hình GitHub Secrets

Vào: GitHub repo → Settings → Secrets → Actions → New repository secret

| Secret | Giá trị |
|--------|---------|
| `STAGING_SSH_KEY` | Private key SSH (xem mục tạo SSH key bên dưới) |
| `STAGING_HOST` | `47.129.243.206` |
| `STAGING_USER` | `Administrator` (hoặc user có quyền) |
| `TELEGRAM_BOT_TOKEN` | Token Telegram bot |
| `TELEGRAM_ADMIN_CHAT_ID` | Chat ID admin |

**Tạo SSH key pair (1 lần):**
```bash
# Trên máy local hoặc server khác
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/zarmor_deploy

# Thêm public key vào server:
cat ~/.ssh/zarmor_deploy.pub >> ~/.ssh/authorized_keys  # trên staging server

# Copy private key vào GitHub Secrets:
cat ~/.ssh/zarmor_deploy  # → dán vào STAGING_SSH_KEY
```

### Bước 3: Setup staging server

```bash
# Trên staging server:
mkdir -p /opt/zarmor
cd /opt/zarmor
git clone https://github.com/YOUR_ORG/Z-ARMOR-CLOUD.git .

# Install PM2 process name
pm2 start "uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4" --name z-armor-core
pm2 save
pm2 startup
```

### Bước 4: Cài pre-commit hooks (mỗi developer)

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files  # test lần đầu
```

### Bước 5: Setup Branch Protection (GitHub UI)

Vào: GitHub repo → Settings → Branches → Add rule → Branch: `main`

- ✅ Require status checks: `lint`, `test`, `migration-check`, `security`
- ✅ Require branches to be up to date
- ✅ Require pull request reviews (1 approval)
- ✅ Do not allow bypassing
- ✅ Restrict force pushes

### Checklist C:
- [ ] Tạo test PR → GitHub Actions chạy tự động
- [ ] All 4 jobs green: lint, test, migration-check, security
- [ ] Merge vào main → deploy pipeline tự chạy
- [ ] `curl staging_server/health` → HTTP 200
- [ ] Telegram notification nhận được
- [ ] Branch protection block merge khi CI fail
- [ ] `pre-commit run --all-files` pass trên máy local

---

## DEFINITION OF DONE — PART 1

Chạy script verify:
```bash
python3 scripts/verify_dod.py
```

Hoặc check thủ công:

```bash
# 1. Không còn fix files
git ls-files | grep -E 'fix_|hotfix|patch_main' | wc -l  # → 0

# 2. Import app sạch
python3 -c "from main import app; print('✅ app imports OK')"

# 3. Alembic clean
alembic upgrade head && alembic check

# 4. Tests pass
pytest tests/ -v --cov=. --cov-fail-under=60

# 5. Health OK
curl -s localhost:8000/health | python3 -m json.tool

# 6. No hardcoded IPs
grep -rn "47\.129\." --include="*.py" . | grep -v .git | wc -l  # → 0
```

---

## NOTES

- Part 1 không thay đổi bất kỳ business logic nào
- EA clients đang live KHÔNG bị ảnh hưởng
- Staging và Production là 2 server riêng biệt
- Part 2 (tách microservices) chỉ bắt đầu sau khi Part 1 DoD verified
