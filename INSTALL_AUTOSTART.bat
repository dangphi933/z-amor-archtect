@echo off
chcp 437 >nul
set BASE=C:\Users\Administrator\Desktop\Z-ARMOR-CLOUD

echo [1] Dang ky Z-ARMOR tu khoi dong cung Windows...

schtasks /delete /tn "ZARMOR_CLOUD" /f >nul 2>&1
schtasks /create /tn "ZARMOR_CLOUD" ^
  /tr "cmd /c cd /d %BASE% && python ZARMOR_START.py >> %BASE%\logs\server_8000.log 2>&1" ^
  /sc ONSTART ^
  /ru SYSTEM ^
  /rl HIGHEST ^
  /f

if errorlevel 1 (
    echo [!!] Dang ky that bai - thu cach khac...
    schtasks /create /tn "ZARMOR_CLOUD" ^
      /tr "cmd /c cd /d %BASE% && python ZARMOR_START.py >> %BASE%\logs\server_8000.log 2>&1" ^
      /sc ONLOGON ^
      /ru Administrator ^
      /f
)

echo.
echo [2] Dang ky WATCHDOG tu khoi dong...
schtasks /delete /tn "ZARMOR_WATCHDOG" /f >nul 2>&1
schtasks /create /tn "ZARMOR_WATCHDOG" ^
  /tr "cmd /c cd /d %BASE% && %BASE%\WATCHDOG.bat" ^
  /sc ONSTART ^
  /ru SYSTEM ^
  /rl HIGHEST ^
  /f

echo.
echo [3] Kiem tra tasks da dang ky:
schtasks /query /tn "ZARMOR_CLOUD" /fo LIST 2>nul | findstr "Task Name\|Status\|Next Run"
schtasks /query /tn "ZARMOR_WATCHDOG" /fo LIST 2>nul | findstr "Task Name\|Status"

echo.
echo [OK] Hoan tat! Server se tu khoi dong khi Windows boot.
echo     De test: khoi dong lai may hoac chay START.bat thu cong.
pause
