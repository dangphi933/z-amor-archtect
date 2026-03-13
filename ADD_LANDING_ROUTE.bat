@echo off
title Add salemain route to zarmor-backend

:: 1. Tu dong lay duong dan thu muc hien tai cua file .bat
set "BASE_DIR=%~dp0"
set "BASE_DIR=%BASE_DIR:~0,-1%"

set "MAINPY=%BASE_DIR%\zarmor-backend\main.py"
set "SALEFILE=%BASE_DIR%\salemain.html"
set "LOG_DIR=%BASE_DIR%\logs"
set "LOG=%LOG_DIR%\backend.log"

echo [INFO] Thu muc goc: %BASE_DIR%
echo Kiem tra salemain.html...

if not exist "%SALEFILE%" (
    echo [!!] Khong tim thay salemain.html tai: %SALEFILE%
    echo     Vui long copy file salemain.html vao thu muc Z-ARMOR-CLOUD truoc!
    pause
    exit /b 1
)
echo [OK] salemain.html ton tai.

echo Them route serve salemain.html vao zarmor-backend\main.py...

:: 2. Tao mot file Python tam de chen code an toan
set "PATCH_SCRIPT=%BASE_DIR%\patch_temp.py"

echo import os, shutil > "%PATCH_SCRIPT%"
echo mainpy = r'%MAINPY%' >> "%PATCH_SCRIPT%"
echo salefile = r'%SALEFILE%' >> "%PATCH_SCRIPT%"
echo with open(mainpy, encoding='utf-8'^) as f: >> "%PATCH_SCRIPT%"
echo     content = f.read(^) >> "%PATCH_SCRIPT%"
echo if 'salemain' in content or 'FileResponse' in content: >> "%PATCH_SCRIPT%"
echo     print('Da co route salemain hoac FileResponse - khong can them.'^) >> "%PATCH_SCRIPT%"
echo     exit(0^) >> "%PATCH_SCRIPT%"
echo content = content.replace('from fastapi import FastAPI', 'from fastapi import FastAPI\nfrom fastapi.responses import FileResponse, HTMLResponse'^) >> "%PATCH_SCRIPT%"
echo route_code = """ >> "%PATCH_SCRIPT%"
echo SALE_HTML = r'%SALEFILE%' >> "%PATCH_SCRIPT%"
echo @app.get('/') >> "%PATCH_SCRIPT%"
echo def landing_page(): >> "%PATCH_SCRIPT%"
echo     if os.path.exists(SALE_HTML): >> "%PATCH_SCRIPT%"
echo         return FileResponse(SALE_HTML, media_type='text/html') >> "%PATCH_SCRIPT%"
echo     return HTMLResponse('Z-ARMOR CLOUD: salemain.html not found') >> "%PATCH_SCRIPT%"
echo """ >> "%PATCH_SCRIPT%"
echo if 'if __name__' in content: >> "%PATCH_SCRIPT%"
echo     content = content.replace('if __name__', route_code + '\nif __name__'^) >> "%PATCH_SCRIPT%"
echo else: >> "%PATCH_SCRIPT%"
echo     content += '\n' + route_code >> "%PATCH_SCRIPT%"
echo shutil.copy(mainpy, mainpy + '.bak'^) >> "%PATCH_SCRIPT%"
echo with open(mainpy, 'w', encoding='utf-8'^) as f: >> "%PATCH_SCRIPT%"
echo     f.write(content^) >> "%PATCH_SCRIPT%"
echo print('Done! Route added. Backup: main.py.bak'^) >> "%PATCH_SCRIPT%"

python "%PATCH_SCRIPT%"
del "%PATCH_SCRIPT%"

echo.
echo Khoi dong lai backend...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000 " ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>&1
timeout /t 2 /nobreak >nul

:: 3. Kiem tra va tao thu muc logs neu chua co
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

start "ZARMOR-BACKEND-8000" /min cmd /c "cd /d "%BASE_DIR%\zarmor-backend" && python -m uvicorn main:app --host 0.0.0.0 --port 8000 >> "%LOG%" 2>&1"
timeout /t 6 /nobreak >nul

netstat -aon | findstr ":8000 " | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
    echo [!!] Backend :8000 OFFLINE - xem logs\backend.log
) else (
    echo [OK] Backend :8000 ONLINE
    echo [OK] Landing page: http://localhost:8000/
)
pause >nul