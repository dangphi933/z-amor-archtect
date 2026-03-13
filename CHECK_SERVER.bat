@echo off
REM ==========================================
REM Z-ARMOR CLOUD - CHECK SERVER STATUS
REM ==========================================

echo.
echo ╔════════════════════════════════════════════════════════════╗
echo ║        Z-ARMOR CLOUD - SERVER STATUS CHECK                 ║
echo ╚════════════════════════════════════════════════════════════╝
echo.

echo 🔍 Checking if server is running on port 8000...
echo.

REM Kiểm tra xem có process nào đang lắng nghe port 8000 không
netstat -ano | findstr :8000 >nul 2>&1
if errorlevel 1 (
    echo ❌ SERVER IS NOT RUNNING
    echo.
    echo Server chưa được khởi động trên port 8000
    echo.
    echo Để khởi động server:
    echo 1. Double-click file START_SERVER.bat
    echo    hoặc
    echo 2. Chạy lệnh: python main.py
    echo.
    goto :end
) else (
    echo ✅ SERVER IS RUNNING on port 8000
    echo.
    
    REM Hiển thị process ID
    echo 📋 Process details:
    netstat -ano | findstr :8000
    echo.
    
    REM Test ping server
    echo 🏓 Testing server connection...
    curl -s http://localhost:8000/ >nul 2>&1
    if errorlevel 1 (
        echo ⚠️  Port 8000 đang được sử dụng nhưng không phải Z-Armor server
        echo    (có thể là ứng dụng khác)
        echo.
    ) else (
        echo ✅ Server responding OK!
        echo.
        echo 🌐 Server URL: http://localhost:8000
        echo 🖥️  Dashboard: http://localhost:8000/web/
        echo 📊 API Status: http://localhost:8000/admin/stats
        echo.
    )
)

:end
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo.
pause
