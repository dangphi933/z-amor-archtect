@echo off
:: run.bat — Windows helper cho Z-Armor Part 1 scripts
:: Tự động detect python / py / python3
:: Usage: run.bat cleanup --dry-run
::        run.bat cleanup --apply
::        run.bat verify
::        run.bat partition

setlocal

:: Detect Python command
set PYTHON=
where python >nul 2>&1 && set PYTHON=python
if "%PYTHON%"=="" where py >nul 2>&1 && set PYTHON=py
if "%PYTHON%"=="" where python3 >nul 2>&1 && set PYTHON=python3

if "%PYTHON%"=="" (
    echo [ERROR] Python not found. Install from https://python.org
    echo         Make sure to check "Add Python to PATH" during install
    exit /b 1
)

echo [INFO] Using: %PYTHON%
echo.

if "%1"=="cleanup" (
    %PYTHON% scripts\cleanup_hotfixes.py %2 %3
) else if "%1"=="verify" (
    %PYTHON% scripts\verify_dod.py
) else if "%1"=="partition" (
    %PYTHON% scripts\create_partition.py
) else if "%1"=="alembic-stamp" (
    alembic stamp head
) else if "%1"=="alembic-upgrade" (
    alembic upgrade head
) else if "%1"=="alembic-check" (
    alembic current
    alembic check
) else if "%1"=="health" (
    curl -s http://localhost:8000/health
) else (
    echo Z-Armor Part 1 — Windows Runner
    echo.
    echo Usage:
    echo   run.bat cleanup --dry-run     ^| Xem trước cleanup (an toan)
    echo   run.bat cleanup --apply       ^| Thuc thi xoa fix files
    echo   run.bat verify                ^| Kiem tra Definition of Done
    echo   run.bat partition             ^| Tao partition thang toi
    echo   run.bat alembic-stamp         ^| Stamp production DB
    echo   run.bat alembic-upgrade       ^| Chay migrations
    echo   run.bat alembic-check         ^| Kiem tra migration status
    echo   run.bat health                ^| Smoke test /health endpoint
)

endlocal
