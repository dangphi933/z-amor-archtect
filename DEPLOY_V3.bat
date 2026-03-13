@echo off
REM ================================================================
REM Z-ARMOR CLOUD — Deploy Identity Platform v3.0
REM Run on Windows EC2: double-click or CMD as Administrator
REM ================================================================

SET APP_DIR=C:\Users\Administrator\Desktop\Z-ARMOR-CLOUD

echo [1/6] Copying new files...
copy /Y main.py           %APP_DIR%\main.py
copy /Y auth_service.py   %APP_DIR%\auth_service.py
copy /Y remarketing_scheduler.py %APP_DIR%\remarketing_scheduler.py
copy /Y api\auth_router.py      %APP_DIR%\api\auth_router.py
copy /Y api\identity_router.py  %APP_DIR%\api\identity_router.py
copy /Y api\billing_router.py   %APP_DIR%\api\billing_router.py
copy /Y api\radar_identity_router.py %APP_DIR%\api\radar_identity_router.py
copy /Y api\growth_router.py    %APP_DIR%\api\growth_router.py
copy /Y api\compliance_router.py %APP_DIR%\api\compliance_router.py
copy /Y _env_v3  %APP_DIR%\.env

echo [2/6] Installing new Python deps...
pip install PyJWT>=2.8.0 bcrypt>=4.0.0 python-multipart --break-system-packages

echo [3/6] Running database migration...
psql -U zarmor -d zarmor_db -f migration_identity_v3.sql
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Migration failed! Check PostgreSQL connection.
    pause
    exit /b 1
)

echo [4/6] Restarting PM2...
pm2 restart z-armor-core

echo [5/6] Waiting 5s for startup...
timeout /t 5 /nobreak

echo [6/6] Health check...
curl -s http://localhost:8000/api/health
curl -s http://localhost:8000/auth/me

echo.
echo ================================================================
echo DEPLOY COMPLETE — Z-ARMOR v3.0 Identity Platform
echo.
echo Test login:
echo   curl -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d "{\"license_key\":\"YOUR-KEY\"}"
echo.
echo PM2 logs:
echo   pm2 logs z-armor-core --lines 30
echo ================================================================
pause
