# 🏛️ KIẾN TRÚC HỆ THỐNG: Z-ARMOR CLOUD SAAS
**Phiên bản:** 7.0 (Global SaaS Edition)
**Codename:** Sovereign Thermodynamics & Quantum Funnel


## 1. Tổng quan Đế chế (The Empire Overview)
Z-ARMOR không còn là một công cụ cá nhân, mà đã tiến hóa thành một **Hệ sinh thái Phần mềm Dịch vụ (SaaS) khép kín**. Hệ thống coi Vốn là Năng lượng, Drawdown là Entropy, và Tự động hóa Doanh thu là Dòng máu duy trì Đế chế.

### Ngăn xếp Tứ trụ (The Quad-Stack)
1. **Lớp Giao dịch & Mũi nhọn (Client Side):** MQL5 EA (Cài trên MT5 khách hàng). Hoạt động như xúc tu thu thập dữ liệu và thi hành án (ExpertRemove) nếu vi phạm bản quyền.
2. **Lớp Xử lý Lõi (Python Cloud Engine):** FastAPI Asynchronous Engine. Nơi tính toán Vận tốc Entropy ($dDD/dt$) và xử lý logic Giảm chấn.
3. **Lớp Quản trị Bản quyền & Kế toán (SaaS Layer):** Quản lý License Key, liên kết ID MT5, xử lý Webhook thanh toán và Lark Automation.
4. **Lớp Trình bày (Giao diện Web):** Cyberpunk Dashboard (Preact/HTML5) cho khách hàng theo dõi Radar và nhập mã kích hoạt.

---

## 2. Đường ống Dữ liệu & Kế toán (Data & Revenue Pipeline)

### A. Luồng Vận hành Sinh tồn (Trading Pipeline)
1. **Ingestion (Lấy mẫu 1s/lần):** EA MT5 bắn Heartbeat & Positions (JSON) qua `/api/webhook/`. Bộ lọc chặn đứng mọi ký tự tàng hình (`\0`).
2. **Computation (Nhiệt động lực học):** Lõi Python tính toán $Z_{Load}$ và Vận tốc Entropy. Phân loại trạng thái (Laminar / Turbulent).
3. **Execution (Thi hành):** Bóp Volume (Damping) hoặc ra lệnh "SCRAM" (Cắt toàn bộ lệnh) nếu vượt Sàn Z-Armor.

### B. Luồng Doanh thu Tự động (Quantum Funnel)
1. **Checkout:** Khách thanh toán qua Stripe (Thẻ) hoặc NowPayments (Crypto) trên Landing Page.
2. **License Minting:** Cổng thanh toán gọi Webhook. Cloud tự đúc mã `ZARMOR-XXXXXX` lưu vào SQLite.
3. **Fulfillment:** Background Task tự động gửi Email chứa Key cho khách.
4. **Accounting:** Bắn dữ liệu Doanh thu (API) về hệ thống Lark Suite Base. Bot Telegram réo "TING TING".

---

## 3. Ma trận Cốt lõi (Core Matrices)

### A. Ma trận Bản quyền (License Gatekeeper)
* **Binding Rule:** 1 License Key chỉ được gắn (Bind) với một số lượng ID MT5 nhất định.
* **Heartbeat Verification:** Mỗi 60 giây, EA kiểm tra `/api/verify-license`. Trả về `False` -> EA tự hủy.

### B. Ma trận Không gian Pha 3D (Động lực học)
* **Trục X (Momentum):** Tốc độ lợi nhuận.
* **Trục Y (Stress):** Áp suất nội tại (Sử dụng Margin).
* **Trục Z (Velocity):** Tốc độ sản sinh Entropy ($dDD/dt$).