#!/bin/bash
# backup.sh — Z-ARMOR CLOUD
# ==========================
# 4.3 / R-09: PostgreSQL backup tự động hàng ngày
# Không cần Docker, không cần managed DB.
#
# Setup (chạy 1 lần):
#   chmod +x backup.sh
#   crontab -e
#   # Thêm dòng sau để backup lúc 3:00 AM mỗi ngày:
#   0 3 * * * /path/to/Z-ARMOR-CLOUD/backup.sh >> /var/log/zarmor-backup.log 2>&1
#
# Restore từ backup:
#   gunzip -c /backup/zarmor/zarmor_db_2026-03-07.sql.gz | psql -U zarmor zarmor_db

set -euo pipefail

# ── CONFIG ──────────────────────────────────────────────────────
BACKUP_DIR="${BACKUP_DIR:-/backup/zarmor}"
DB_NAME="${DB_NAME:-zarmor_db}"
DB_USER="${DB_USER:-zarmor}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
KEEP_DAYS="${KEEP_DAYS:-30}"          # Giữ backup bao nhiêu ngày
TIMESTAMP=$(date +"%Y-%m-%d_%H%M%S")
BACKUP_FILE="$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.sql.gz"

# ── CHẠY ────────────────────────────────────────────────────────
echo "[BACKUP] $(date '+%Y-%m-%d %H:%M:%S') — Bắt đầu backup $DB_NAME"

mkdir -p "$BACKUP_DIR"

# Dump và compress trong 1 bước — không tạo file tạm lớn
PGPASSWORD="${PGPASSWORD:-}" \
    pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" \
    | gzip -9 > "$BACKUP_FILE"

SIZE=$(du -sh "$BACKUP_FILE" | cut -f1)
echo "[BACKUP] ✅ Thành công: $BACKUP_FILE ($SIZE)"

# ── CLEANUP — xóa backup cũ hơn KEEP_DAYS ngày ─────────────────
DELETED=$(find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -mtime +${KEEP_DAYS} -print -delete | wc -l)
if [ "$DELETED" -gt 0 ]; then
    echo "[BACKUP] 🗑️  Đã xóa $DELETED backup cũ hơn ${KEEP_DAYS} ngày"
fi

# ── KIỂM TRA DUNG LƯỢNG ─────────────────────────────────────────
TOTAL=$(du -sh "$BACKUP_DIR" | cut -f1)
COUNT=$(ls "$BACKUP_DIR"/*.sql.gz 2>/dev/null | wc -l)
echo "[BACKUP] 📦 Tổng: $COUNT files, $TOTAL disk"

# ── GỬI TELEGRAM NOTIFICATION (tuỳ chọn) ───────────────────────
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d chat_id="${TELEGRAM_CHAT_ID}" \
        -d parse_mode="HTML" \
        -d text="<b>[Z-ARMOR] Backup OK</b>
📅 $(date '+%Y-%m-%d %H:%M')
📁 $BACKUP_FILE
📦 Size: $SIZE
🗄️ Total: $COUNT files, $TOTAL" \
        > /dev/null
    echo "[BACKUP] 📨 Telegram notification gửi OK"
fi

echo "[BACKUP] ✅ Hoàn tất"
