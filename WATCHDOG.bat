@echo off
title Z-ARMOR WATCHDOG
cd /d C:\Users\Administrator\Desktop\Z-ARMOR-CLOUD

:loop
echo [%time%] Checking server...
netstat -aon | findstr ":8000 " | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
    echo [%time%] Server DOWN - restarting...
    python ZARMOR_START.py >> logs\server_8000.log 2>&1
    timeout /t 10 /nobreak >nul
) else (
    timeout /t 30 /nobreak >nul
)
goto loop
