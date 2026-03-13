# ⚠️ LỖI: COULD NOT CONNECT TO SERVER PORT 8000

## 🔴 VẤN ĐỀ

Khi chạy curl, bạn gặp lỗi:
```
curl: (7) Failed to connect to localhost port 8000 after 2236 ms: Could not connect to server
```

## 💡 NGUYÊN NHÂN

**Server Z-Armor Cloud CHƯA ĐƯỢC KHỞI ĐỘNG!**

API server phải chạy trước khi bạn có thể gửi requests tới nó.

---

## ✅ GIẢI PHÁP (2 CÁCH)

### CÁCH 1: Dùng Script Tự Động (KHUYẾN NGHỊ)

#### Bước 1: Copy 3 files .bat vào thư mục Z-ARMOR-CLOUD
- `START_SERVER.bat` - Khởi động server
- `CHECK_SERVER.bat` - Kiểm tra server có chạy không
- `TEST_CHECKOUT.bat` - Test API checkout

#### Bước 2: Khởi động server
Double-click file `START_SERVER.bat`

Bạn sẽ thấy:
```
╔════════════════════════════════════════════════════════════╗
║           Z-ARMOR CLOUD ENGINE - STARTING...               ║
╚════════════════════════════════════════════════════════════╝

✅ Python detected: Python 3.x.x
✅ Found main.py

🚀 Starting Z-Armor Cloud Server on port 8000...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[STARTUP] Z-Armor Cloud Engine V8.2 dang khoi dong...
[STARTUP] OK — san sang nhan ket noi.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

**⚠️ QUAN TRỌNG:** Giữ cửa sổ này mở! Đừng tắt.

#### Bước 3: Test server
Mở cửa sổ Command Prompt MỚI, chạy:
```bash
CHECK_SERVER.bat
```

Hoặc test checkout ngay:
```bash
TEST_CHECKOUT.bat
```

---

### CÁCH 2: Khởi Động Thủ Công

#### Bước 1: Mở Command Prompt
Nhấn `Win + R` → gõ `cmd` → Enter

#### Bước 2: Di chuyển vào thư mục dự án
```bash
cd C:\Users\Administrator\Desktop\Z-ARMOR-CLOUD
```

#### Bước 3: Chạy server
```bash
python main.py
```

Đợi cho đến khi thấy:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

#### Bước 4: Test (mở tab Command Prompt MỚI)
```bash
curl http://localhost:8000/
```

Nếu thấy HTML response → Server đã chạy OK!

---

## 🧪 TEST CHECKOUT SAU KHI SERVER CHẠY

### Cách 1: Dùng script
```bash
TEST_CHECKOUT.bat
```

### Cách 2: Dùng curl trực tiếp
```bash
curl -X POST http://localhost:8000/api/checkout ^
  -H "Content-Type: application/json" ^
  -d "{\"buyer_name\":\"Test\",\"buyer_email\":\"dangphi9339@gmail.com\",\"tier\":\"STARTER_TRIAL\",\"amount\":0,\"method\":\"TRIAL_FREE\"}"
```

### Kết quả mong đợi:
```json
{
  "status": "success",
  "order_id": "ORD-XXXXXX",
  "license_key": "ZARMOR-XXXXX-XXXXX",
  "expires_at": "2026-03-14T...",
  "message": "Trial license activated! Check your email."
}
```

---

## 📋 CHECKLIST

- [ ] Server đã được khởi động (`python main.py` hoặc `START_SERVER.bat`)
- [ ] Console hiện "Uvicorn running on http://0.0.0.0:8000"
- [ ] Giữ cửa sổ server mở (không tắt)
- [ ] Test `curl http://localhost:8000/` → thấy response
- [ ] Test checkout → nhận được license key

---

## 🔧 TROUBLESHOOTING

### Lỗi: "python: command not found"
**Nguyên nhân:** Python chưa cài đặt hoặc chưa thêm vào PATH

**Giải pháp:**
1. Tải Python: https://www.python.org/downloads/
2. Cài đặt, tick vào "Add Python to PATH"
3. Restart Command Prompt
4. Chạy lại `python main.py`

---

### Lỗi: "Address already in use" (Port 8000 bị chiếm)
**Nguyên nhân:** Có ứng dụng khác đang dùng port 8000

**Giải pháp:**
1. Tìm process đang dùng port 8000:
   ```bash
   netstat -ano | findstr :8000
   ```

2. Kill process đó:
   ```bash
   taskkill /PID <PID_NUMBER> /F
   ```

3. Hoặc đổi port trong main.py (dòng cuối):
   ```python
   uvicorn.run("main:app", host="0.0.0.0", port=8001)
   ```

---

### Lỗi: "ModuleNotFoundError: No module named 'fastapi'"
**Nguyên nhân:** Thiếu dependencies

**Giải pháp:**
```bash
pip install -r requirements.txt
```

Hoặc cài thủ công:
```bash
pip install fastapi uvicorn httpx python-dotenv sqlalchemy pydantic
```

---

## 💡 TIPS

### 1. Để Server Chạy Nền (Background)
Tạo Windows Service hoặc dùng `pythonw.exe`:
```bash
start /B pythonw main.py
```

### 2. Tự Động Khởi Động Khi Windows Start
Thêm shortcut của `START_SERVER.bat` vào:
```
C:\Users\Administrator\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup
```

### 3. Monitor Server Logs
Server sẽ in logs ra console, bạn có thể save vào file:
```bash
python main.py > server.log 2>&1
```

---

## 🎯 TÓM TẮT

**VẤN ĐỀ:** Server chưa chạy → curl không kết nối được
**GIẢI PHÁP:** Khởi động server trước khi test API
**CÁCH KHỞI ĐỘNG:** 
- Double-click `START_SERVER.bat`
- Hoặc chạy `python main.py`

**LƯU Ý:** Giữ cửa sổ server mở trong suốt quá trình test!

---

**Created:** 2026-03-07
**Version:** 1.0
