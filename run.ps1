# run.ps1 — PowerShell helper cho Z-Armor Part 1
# Usage:
#   .\run.ps1 cleanup --dry-run
#   .\run.ps1 cleanup --apply
#   .\run.ps1 verify
#   .\run.ps1 health

param(
    [string]$Command = "help",
    [string]$Flag = ""
)

# ─── Detect Python ─────────────────────────────────────────────────────────
$PythonCmd = $null
foreach ($cmd in @("python", "py", "python3")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            $PythonCmd = $cmd
            Write-Host "[INFO] Python: $ver (command: $cmd)" -ForegroundColor Cyan
            break
        }
    } catch {}
}

if (-not $PythonCmd) {
    Write-Host "[ERROR] Python not found!" -ForegroundColor Red
    Write-Host "        Install from: https://python.org"
    Write-Host "        Check 'Add Python to PATH' during install"
    exit 1
}

# ─── Commands ──────────────────────────────────────────────────────────────
switch ($Command) {
    "cleanup" {
        Write-Host "`n=== Cleanup 23 fix/hotfix/patch files ===" -ForegroundColor Yellow
        if ($Flag -eq "--apply") {
            Write-Host "MODE: APPLY (will delete files)" -ForegroundColor Red
            $confirm = Read-Host "Are you sure? (yes/no)"
            if ($confirm -ne "yes") { Write-Host "Cancelled."; exit 0 }
        }
        & $PythonCmd scripts\cleanup_hotfixes.py $Flag
    }

    "verify" {
        Write-Host "`n=== Definition of Done Verification ===" -ForegroundColor Yellow
        & $PythonCmd scripts\verify_dod.py
    }

    "partition" {
        Write-Host "`n=== Create next month partition ===" -ForegroundColor Yellow
        & $PythonCmd scripts\create_partition.py
    }

    "alembic-init" {
        Write-Host "`n=== Alembic: stamp production DB ===" -ForegroundColor Yellow
        Write-Host "NOTE: This marks the DB as already at 'head' without running migrations"
        Write-Host "      Use this on production DB that already has the schema"
        $confirm = Read-Host "Run 'alembic stamp head'? (yes/no)"
        if ($confirm -eq "yes") { alembic stamp head }
    }

    "alembic-upgrade" {
        Write-Host "`n=== Alembic: upgrade to head ===" -ForegroundColor Yellow
        alembic upgrade head
    }

    "alembic-check" {
        Write-Host "`n=== Alembic: status ===" -ForegroundColor Yellow
        alembic current
        Write-Host ""
        alembic history --verbose
    }

    "health" {
        Write-Host "`n=== Health check ===" -ForegroundColor Yellow
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing
            Write-Host "HTTP Status: $($resp.StatusCode)" -ForegroundColor Green
            $resp.Content | ConvertFrom-Json | ConvertTo-Json -Depth 3
        } catch {
            Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
            Write-Host "Is the server running? Try: pm2 status"
        }
    }

    "grep-ip" {
        Write-Host "`n=== Checking hardcoded IPs ===" -ForegroundColor Yellow
        $found = Select-String -Path "*.py", "*.js", "*.html" -Pattern "47\.129\." -Recurse -ErrorAction SilentlyContinue |
                 Where-Object { $_.Filename -notmatch "test_|\.bak" }
        if ($found) {
            Write-Host "FOUND hardcoded IPs:" -ForegroundColor Red
            $found | ForEach-Object { Write-Host "  $($_.Filename):$($_.LineNumber) — $($_.Line.Trim())" }
        } else {
            Write-Host "✅ No hardcoded IPs found" -ForegroundColor Green
        }
    }

    default {
        Write-Host ""
        Write-Host "Z-Armor Part 1 — PowerShell Runner" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "Usage: .\run.ps1 <command> [flag]"
        Write-Host ""
        Write-Host "  cleanup --dry-run    Xem truoc cleanup (an toan)"
        Write-Host "  cleanup --apply      Thuc thi xoa fix files"
        Write-Host "  verify               Kiem tra Definition of Done (10 checks)"
        Write-Host "  partition            Tao partition thang toi"
        Write-Host "  alembic-init         Stamp production DB (khong chay migrations)"
        Write-Host "  alembic-upgrade      Chay tat ca migrations"
        Write-Host "  alembic-check        Kiem tra migration status"
        Write-Host "  health               Smoke test /health endpoint"
        Write-Host "  grep-ip              Tim hardcoded IPs trong codebase"
    }
}
