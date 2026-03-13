@echo off
REM ==========================================
REM Z-ARMOR CLOUD - TEST CHECKOUT API
REM ==========================================

echo.
echo ╔════════════════════════════════════════════════════════════╗
echo ║           Z-ARMOR CLOUD - TEST CHECKOUT API                ║
echo ╚════════════════════════════════════════════════════════════╝
echo.

REM Kiểm tra curl có sẵn không
curl --version >nul 2>&1
if errorlevel 1 (
    echo ❌ ERROR: curl không tìm thấy!
    echo.
    echo Windows 10 version 1803+ đã có sẵn curl
    echo Nếu bạn dùng Windows cũ hơn, tải curl tại: https://curl.se/windows/
    echo.
    pause
    exit /b 1
)

echo 🔍 Checking server status...
curl -s http://localhost:8000/ >nul 2>&1
if errorlevel 1 (
    echo ❌ Server không chạy trên port 8000!
    echo.
    echo Vui lòng khởi động server trước:
    echo → Double-click START_SERVER.bat
    echo.
    pause
    exit /b 1
)

echo ✅ Server is running
echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo 🧪 TESTING CHECKOUT API - TRIAL FREE
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo.

echo 📤 Request:
echo POST http://localhost:8000/api/checkout
echo Body:
echo {
echo   "buyer_name": "Test User",
echo   "buyer_email": "dangphi9339@gmail.com",
echo   "tier": "STARTER_TRIAL",
echo   "amount": 0,
echo   "method": "TRIAL_FREE"
echo }
echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo.
echo 📥 Response:
echo.

curl -X POST http://localhost:8000/api/checkout ^
  -H "Content-Type: application/json" ^
  -d "{\"buyer_name\":\"Test User\",\"buyer_email\":\"dangphi9339@gmail.com\",\"tier\":\"STARTER_TRIAL\",\"amount\":0,\"method\":\"TRIAL_FREE\"}"

echo.
echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo.
echo ✅ Test completed!
echo.
echo 📋 Kiểm tra thêm:
echo 1. Console log của server (cửa sổ chạy START_SERVER.bat)
echo 2. Email tại dangphi9339@gmail.com
echo 3. Telegram notification
echo 4. Lark Base records
echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo.
pause
