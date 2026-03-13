# 🔧 SỬA LỖI: CheckoutPayload has no attribute 'method'

## 🔴 LỖI HIỆN TẠI

```
AttributeError: 'CheckoutPayload' object has no attribute 'method'
File "C:\Users\Administrator\Desktop\Z-ARMOR-CLOUD\main.py", line 604
    method = payload.method or "MANUAL"
             ^^^^^^^^^^^^^^
```

## 💡 NGUYÊN NHÂN

File `api/schemas.py` định nghĩa `CheckoutPayload` model **THIẾU field `method`**:

```python
# api/schemas.py - CODE CŨ (SAI)
class CheckoutPayload(BaseModel):
    buyer_name: str
    buyer_email: str
    tier: Optional[str] = "STARTER"
    amount: Optional[float] = 0.0
    # ← THIẾU: method field
```

Nhưng trong `main.py` lại cố đọc field này:
```python
# main.py dòng 604
method = payload.method or "MANUAL"  # ← LỖI: field không tồn tại!
```

---

## ✅ GIẢI PHÁP (2 CÁCH)

### CÁCH 1: SỬA FILE api/schemas.py (KHUYẾN NGHỊ)

#### Bước 1: Mở file
```
C:\Users\Administrator\Desktop\Z-ARMOR-CLOUD\api\schemas.py
```

#### Bước 2: Tìm class CheckoutPayload

Dùng Ctrl+F tìm: `class CheckoutPayload`

#### Bước 3: Thêm field method

Sửa từ:
```python
class CheckoutPayload(BaseModel):
    buyer_name: str
    buyer_email: str
    tier: Optional[str] = "STARTER"
    amount: Optional[float] = 0.0
```

Thành:
```python
class CheckoutPayload(BaseModel):
    buyer_name: str
    buyer_email: str
    tier: Optional[str] = "STARTER"
    amount: Optional[float] = 0.0
    method: Optional[str] = "MANUAL"  # ← THÊM DÒNG NÀY
```

#### Bước 4: Lưu file (Ctrl+S)

#### Bước 5: Restart server

Nhấn Ctrl+C trong cửa sổ server, rồi chạy lại:
```bash
python main.py
```

---

### CÁCH 2: THAY THẾ TOÀN BỘ FILE (NHANH HƠN)

#### Bước 1: Backup file cũ
```bash
cd C:\Users\Administrator\Desktop\Z-ARMOR-CLOUD\api
copy schemas.py schemas.py.backup
```

#### Bước 2: Download file mới

Tôi đã tạo file `schemas_fixed.py` với đầy đủ các fields cần thiết.

#### Bước 3: Thay thế

Copy nội dung từ `schemas_fixed.py` → paste vào `api/schemas.py`

Hoặc đổi tên file:
```bash
copy schemas_fixed.py schemas.py
```

#### Bước 4: Restart server
```bash
python main.py
```

---

## ✅ KIỂM TRA SAU KHI SỬA

### Test 1: Checkout với method

```bash
curl -X POST http://localhost:8000/api/checkout ^
  -H "Content-Type: application/json" ^
  -d "{\"buyer_name\":\"Test\",\"buyer_email\":\"test@example.com\",\"tier\":\"STARTER_TRIAL\",\"amount\":0,\"method\":\"TRIAL_FREE\"}"
```

**Kết quả mong đợi:**
```json
{
  "status": "success",
  "order_id": "ORD-XXXXXX",
  "license_key": "ZARMOR-XXXXX-XXXXX",
  ...
}
```

### Test 2: Checkout không có method (dùng default)

```bash
curl -X POST http://localhost:8000/api/checkout ^
  -H "Content-Type: application/json" ^
  -d "{\"buyer_name\":\"Test\",\"buyer_email\":\"test@example.com\",\"tier\":\"STARTER\",\"amount\":10}"
```

Method sẽ tự động là "MANUAL" (giá trị default).

---

## 📋 CODE SO SÁNH

### TRƯỚC (LỖI):
```python
# api/schemas.py
class CheckoutPayload(BaseModel):
    buyer_name: str
    buyer_email: str
    tier: Optional[str] = "STARTER"
    amount: Optional[float] = 0.0
    # ← THIẾU field method
```

### SAU (ĐÚNG):
```python
# api/schemas.py  
class CheckoutPayload(BaseModel):
    buyer_name: str
    buyer_email: str
    tier: Optional[str] = "STARTER"
    amount: Optional[float] = 0.0
    method: Optional[str] = "MANUAL"  # ✅ ĐÃ THÊM
```

---

## 🎯 TẠI SAO CẦN FIELD 'method'?

Field `method` cho biết phương thức thanh toán:

- **`TRIAL_FREE`** → Tạo license key ngay lập tức (7 ngày trial)
- **`STRIPE`** → Chờ webhook từ Stripe confirm payment
- **`PAYPAL`** → Chờ webhook từ PayPal confirm payment  
- **`BANK_TRANSFER`** → Admin xác nhận thủ công
- **`MANUAL`** → Admin tạo key thủ công

Logic xử lý trong `main.py`:
```python
if method == "TRIAL_FREE":
    # Tạo license key ngay
    license_key = generate_key()
    send_email(license_key)
    notify_telegram()
elif method in ["STRIPE", "PAYPAL"]:
    # Tạo pending order, đợi webhook
    create_pending_order()
else:
    # Manual handling
    create_pending_order()
```

---

## 🐛 CÁC LỖI LIÊN QUAN CÓ THỂ GẶP

### 1. ValidationError: field required

**Lỗi:**
```
ValidationError: buyer_name field required
```

**Nguyên nhân:** Request JSON thiếu field bắt buộc

**Giải pháp:** Đảm bảo request có đủ:
```json
{
  "buyer_name": "...",     // BẮT BUỘC
  "buyer_email": "...",    // BẮT BUỘC
  "tier": "...",           // Optional (default: STARTER)
  "amount": 0,             // Optional (default: 0.0)
  "method": "TRIAL_FREE"   // Optional (default: MANUAL)
}
```

### 2. JSON decode error

**Lỗi:**
```
JSONDecodeError: Expecting value
```

**Nguyên nhân:** JSON format sai

**Giải pháp:** Dùng JSON validator hoặc escape đúng:
```bash
# Windows CMD - dùng \" để escape quotes
-d "{\"buyer_name\":\"Test\"}"

# PowerShell - dùng single quotes hoặc backtick
-d '{\"buyer_name\":\"Test\"}'
# hoặc
-d "{`"buyer_name`":`"Test`"}"
```

---

## 📁 FILES CẦN SỬA

1. **`api/schemas.py`** - Thêm field `method` vào `CheckoutPayload`

Hoặc thay thế toàn bộ bằng **`schemas_fixed.py`**

---

## 🎯 CHECKLIST

- [ ] Mở file `api/schemas.py`
- [ ] Tìm `class CheckoutPayload`
- [ ] Thêm dòng: `method: Optional[str] = "MANUAL"`
- [ ] Lưu file (Ctrl+S)
- [ ] Restart server (Ctrl+C → `python main.py`)
- [ ] Test checkout → Không còn AttributeError
- [ ] Response có license_key (nếu method=TRIAL_FREE)

---

## 💡 TÓM TẮT

**VẤN ĐỀ:** `CheckoutPayload` thiếu field `method`
**NGUYÊN NHÂN:** File `api/schemas.py` chưa khai báo field này
**GIẢI PHÁP:** Thêm `method: Optional[str] = "MANUAL"` vào schema
**FILE SỬA:** `api/schemas.py` (hoặc dùng `schemas_fixed.py`)
**SAU KHI SỬA:** Restart server và test lại

---

**Created:** 2026-03-07
**Version:** 1.0
