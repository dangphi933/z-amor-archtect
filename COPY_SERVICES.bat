@echo off
set BASE=C:\Users\Administrator\Desktop\Z-ARMOR-CLOUD
set SRC=%BASE%\zarmor-backend

echo Copying service files from zarmor-backend...
for %%f in (telegram_notify.py keygen.py email_service.py lark_service.py config.py) do (
    if exist "%SRC%\%%f" (
        copy /Y "%SRC%\%%f" "%BASE%\%%f" >nul
        echo [OK] %%f
    ) else (
        echo [!!] NOT FOUND: %%f
    )
)

echo.
echo Starting server...
cd /d %BASE%
python -m uvicorn main:app --host 0.0.0.0 --port 8000
