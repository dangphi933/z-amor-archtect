@echo off
REM ==========================================
REM Z-ARMOR CLOUD - START SERVER
REM ==========================================

echo.
echo ╔════════════════════════════════════════════════════════════╗
echo ║           Z-ARMOR CLOUD ENGINE - STARTING...               ║
echo ╚════════════════════════════════════════════════════════════╝
echo.

REM Di chuyển đến thư mục dự án
cd /d "%~dp0"

REM Kiểm tra Python đã cài chưa
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ ERROR: Python chưa được cài đặt hoặc chưa thêm vào PATH!
    echo.
    echo Hướng dẫn:
    echo 1. Tải Python tại: https://www.python.org/downloads/
    echo 2. Cài đặt và tick vào "Add Python to PATH"
    echo 3. Chạy lại script này
    echo.
    pause
    exit /b 1
)

echo ✅ Python detected: 
python --version
echo.

REM Kiểm tra file main.py có tồn tại không
if not exist "main.py" (
    echo ❌ ERROR: File main.py không tìm thấy!
    echo Đảm bảo script này nằm trong thư mục Z-ARMOR-CLOUD
    echo.
    pause
    exit /b 1
)

echo ✅ Found main.py
echo.

REM Cài đặt dependencies (nếu cần)
echo 📦 Checking dependencies...
pip install -r requirements.txt --quiet 2>nul

echo.
echo 🚀 Starting Z-Armor Cloud Server on port 8000...
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo.
echo 💡 Tip: Giữ cửa sổ này mở để server hoạt động
echo 💡 Nhấn Ctrl+C để dừng server
echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo.

REM Khởi động server
python main.py

REM Nếu server bị dừng
echo.
echo ⚠️  Server đã dừng!
echo.
pause
