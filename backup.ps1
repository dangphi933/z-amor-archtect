# =============================================================================
# Z-ARMOR V8.3 — BACKUP SCRIPT (Windows PowerShell)
# Lưu tại: C:\Users\Administrator\Desktop\Z-ARMOR-CLOUD\backup.ps1
# Cài Task Scheduler để chạy tự động lúc 2:00 AM mỗi ngày
# =============================================================================

param(
    [string]$DbHost     = "localhost",
    [string]$DbPort     = "5432",
    [string]$DbName     = "zarmor",
    [string]$DbUser     = "postgres",
    [string]$DbPassword = "YOUR_POSTGRES_PASSWORD",   # <-- đổi password ở đây
    [string]$BackupDir  = "C:\ZArmor-Backups",
    [int]$KeepDaily     = 7,    # giữ 7 bản daily
    [int]$KeepWeekly    = 4     # giữ 4 bản weekly (4 tuần)
)

# ── Setup ─────────────────────────────────────────────────────────────────────
$env:PGPASSWORD = $DbPassword
$timestamp      = Get-Date -Format "yyyyMMdd_HHmmss"
$dayOfWeek      = (Get-Date).DayOfWeek   # Sunday = 0
$logPrefix      = "[BACKUP $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')]"

# Tạo thư mục nếu chưa có
New-Item -ItemType Directory -Force -Path "$BackupDir\daily"  | Out-Null
New-Item -ItemType Directory -Force -Path "$BackupDir\weekly" | Out-Null
New-Item -ItemType Directory -Force -Path "$BackupDir\logs"   | Out-Null

$logFile = "$BackupDir\logs\backup_$timestamp.log"

function Log($msg) {
    $line = "$logPrefix $msg"
    Write-Host $line
    Add-Content -Path $logFile -Value $line
}

# ── Tìm pg_dump ───────────────────────────────────────────────────────────────
$pgDump = Get-Command pg_dump -ErrorAction SilentlyContinue
if (-not $pgDump) {
    # Tìm trong các thư mục PostgreSQL thường gặp
    $pgPaths = @(
        "C:\Program Files\PostgreSQL\16\bin\pg_dump.exe",
        "C:\Program Files\PostgreSQL\15\bin\pg_dump.exe",
        "C:\Program Files\PostgreSQL\14\bin\pg_dump.exe"
    )
    foreach ($path in $pgPaths) {
        if (Test-Path $path) { $pgDump = $path; break }
    }
}
if (-not $pgDump) {
    Log "ERROR: Không tìm thấy pg_dump. Kiểm tra PostgreSQL đã cài chưa."
    exit 1
}

Log "Starting Z-ARMOR backup..."
Log "pg_dump: $pgDump"

# ── Full dump ─────────────────────────────────────────────────────────────────
$dailyFile = "$BackupDir\daily\zarmor_$timestamp.backup"

& $pgDump `
    -h $DbHost `
    -p $DbPort `
    -U $DbUser `
    -d $DbName `
    --format=custom `
    --compress=9 `
    --file="$dailyFile"

if ($LASTEXITCODE -ne 0) {
    Log "ERROR: pg_dump thất bại (exit code $LASTEXITCODE)"
    exit 1
}

$size = [math]::Round((Get-Item $dailyFile).Length / 1MB, 2)
Log "Daily backup OK: $dailyFile ($size MB)"

# ── Weekly copy (Chủ nhật) ────────────────────────────────────────────────────
if ($dayOfWeek -eq "Sunday") {
    $weeklyFile = "$BackupDir\weekly\zarmor_weekly_$timestamp.backup"
    Copy-Item $dailyFile $weeklyFile
    Log "Weekly backup saved: $weeklyFile"
}

# ── Cleanup cũ ────────────────────────────────────────────────────────────────
$cutoffDaily  = (Get-Date).AddDays(-$KeepDaily)
$cutoffWeekly = (Get-Date).AddDays(-($KeepWeekly * 7))

$deletedDaily = Get-ChildItem "$BackupDir\daily\*.backup" |
    Where-Object { $_.LastWriteTime -lt $cutoffDaily } |
    ForEach-Object { Remove-Item $_.FullName; $_.Name }

$deletedWeekly = Get-ChildItem "$BackupDir\weekly\*.backup" |
    Where-Object { $_.LastWriteTime -lt $cutoffWeekly } |
    ForEach-Object { Remove-Item $_.FullName; $_.Name }

if ($deletedDaily)  { Log "Deleted old daily: $($deletedDaily -join ', ')" }
if ($deletedWeekly) { Log "Deleted old weekly: $($deletedWeekly -join ', ')" }

$remaining = (Get-ChildItem "$BackupDir" -Recurse -Filter "*.backup").Count
Log "Cleanup done. Total backups remaining: $remaining"

# ── DB Cleanup: ea_sessions + audit_log ───────────────────────────────────────
# Chỉ chạy nếu bảng tồn tại (an toàn khi chưa chạy migration)
$psql = ($pgDump -replace "pg_dump.exe", "psql.exe") -replace "pg_dump$", "psql"

$cleanupSQL = @"
DO `$`$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'ea_sessions') THEN
        DELETE FROM ea_sessions
        WHERE status IN ('EXPIRED', 'REVOKED')
          AND last_seen < NOW() - INTERVAL '7 days';
        RAISE NOTICE 'ea_sessions cleanup OK';
    ELSE
        RAISE NOTICE 'ea_sessions: table not yet created (skip)';
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'audit_log') THEN
        DELETE FROM audit_log
        WHERE event_at < NOW() - INTERVAL '90 days';
        RAISE NOTICE 'audit_log cleanup OK';
    ELSE
        RAISE NOTICE 'audit_log: table not yet created (skip)';
    END IF;
END
`$`$;
"@

$cleanupSQL | & $psql -h $DbHost -p $DbPort -U $DbUser -d $DbName 2>&1
Log "DB cleanup done"

Log "Backup complete. ✅"
Log "Log saved: $logFile"
