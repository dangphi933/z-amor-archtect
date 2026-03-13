# 1. Sử dụng hệ điều hành Linux với Python 3.11 bản slim (Siêu nhẹ, cực ổn định)
FROM python:3.11-slim

# 2. Tạo thư mục làm việc tên là /app bên trong Thùng
WORKDIR /app

# 3. Copy file requirements.txt vào trước (Mẹo để Docker build cực nhanh ở các lần sau)
COPY requirements.txt .

# 4. Cài đặt toàn bộ thư viện (Không lưu cache để thùng nhẹ nhất có thể)
RUN pip install --no-cache-dir -r requirements.txt

# 5. Bê toàn bộ mã nguồn của Sếp (main.py, api/, config/, web/...) vào Thùng
COPY . .

# 6. Đục một lỗ ở cổng 8000 trên Thùng để nối ra Internet
EXPOSE 8000

# 7. Lệnh bốc hỏa Động cơ khi Thùng được cắm điện (KHÔNG dùng tính năng reload)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]