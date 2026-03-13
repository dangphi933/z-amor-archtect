# =============================================================================
# install_backup_task.ps1 — FIXED VERSION
# Chạy với quyền Administrator
# =============================================================================

$taskName   = "ZArmor-Daily-Backup"
$scriptPath = "C:\Users\Administrator\Desktop\Z-ARMOR-CLOUD\backup.ps1"
$logDir     = "C:\ZArmor-Backups\logs"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

if (-not (Test-Path $scriptPath)) {
    Write-Host "ERROR: Khong tim thay $scriptPath" -ForegroundColor Red
    exit 1
}

# Xoa task cu neu co
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# Action — ghep chuoi de tranh loi nháy don
$psArgs = "-ExecutionPolicy Bypass -NonInteractive -File " + '"' + $scriptPath + '"'
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $psArgs

# Trigger: 2:00 AM moi ngay
$trigger = New-ScheduledTaskTrigger -Daily -At "02:00AM"

# Settings
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable

# Principal: SYSTEM account
$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

# Dang ky task
Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Z-ARMOR V8.3 - Daily PostgreSQL backup 2AM"

Write-Host ""
Write-Host "Task Scheduler da cai thanh cong!" -ForegroundColor Green
Write-Host "Task name : $taskName" -ForegroundColor Cyan
Write-Host "Chay luc  : 2:00 AM moi ngay" -ForegroundColor Cyan
Write-Host ""
Write-Host "Test chay ngay:" -ForegroundColor Yellow
$cmd = "Start-ScheduledTask -TaskName " + $taskName
Write-Host "   $cmd" -ForegroundColor White
