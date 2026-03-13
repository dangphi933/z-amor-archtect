#!/bin/bash
# alembic_setup.sh — Z-ARMOR CLOUD
# ==================================
# 4.3 FIX: Alembic thay cho migrate_db.py thủ công
# Schema version control + rollback an toàn
#
# Chạy lần đầu:
#   chmod +x alembic_setup.sh && ./alembic_setup.sh
#
# Sau đó mỗi lần thay đổi schema:
#   alembic revision --autogenerate -m "add column xyz"
#   alembic upgrade head
#
# Rollback 1 bước:
#   alembic downgrade -1

set -e
echo "[ALEMBIC] Cài đặt Alembic migration framework..."

pip install alembic --quiet

# Khởi tạo thư mục alembic nếu chưa có
if [ ! -d "alembic" ]; then
    alembic init alembic
    echo "[ALEMBIC] ✅ Đã tạo thư mục alembic/"
fi

# Patch alembic.ini — đặt URL từ .env
if grep -q "sqlalchemy.url = driver://user" alembic.ini 2>/dev/null; then
    sed -i "s|sqlalchemy.url = driver://user:pass@localhost/dbname|sqlalchemy.url = |" alembic.ini
    echo "[ALEMBIC] ✅ Đã patch alembic.ini (URL sẽ load từ env.py)"
fi

echo "[ALEMBIC] ✅ Setup xong. Các bước tiếp theo:"
echo "  1. Xem alembic/env.py đã được tạo bởi script Python đi kèm"
echo "  2. alembic revision --autogenerate -m 'phase2_indexes_admin_retry'"
echo "  3. alembic upgrade head"
echo "  4. Kiểm tra: alembic current"
