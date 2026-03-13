# 🛡️ Z-ARMOR: DYNAMIC CAPACITY SYSTEM (v5.0)

## 1. Triết lý Vận hành
Hệ thống Z-ARMOR không sử dụng mức rủi ro Tĩnh (Static Risk). Thay vào đó, nó áp dụng nguyên lý **Động lực học Chất lưu (Fluid Dynamics)** kết hợp với **Tiêu chuẩn Kelly** để đo lường "Sức khỏe" của tài khoản theo từng tích tắc (Real-time).

Khi bạn thắng, hệ thống cấp cho bạn một tấm giáp lớn hơn (Laminar Flow). Khi bạn thua, tấm giáp co lại và hệ thống ép bạn phải thu mình (Turbulent Force).

---

## 2. Nền tảng Toán học (The Math)

Hệ thống xoay quanh 2 biến số cực kỳ quan trọng:

### A. Năng lực Sinh tồn Động ($C_d$ - Dynamic Capacity)
Đo lường "Ngân sách sống sót" thực tế của bạn trong ngày.
> **Công thức:** `Cd = Daily Loss Plan + Total PnL (Lãi/lỗ ròng)`

*Ý nghĩa:* * Lợi nhuận sinh ra sẽ làm Đệm (Buffer) bảo vệ bạn. 
* Thua lỗ sẽ bào mòn trực tiếp vào Kế hoạch ngày.
* **Chốt chặn:** Nếu $C_d \le 0$, hệ thống rơi vào trạng thái Tử thần (Dead Zone).

### B. Áp suất Tải trọng ($Z_{Load}$ - Z-Pressure)
Đo lường mức độ "Căng thẳng" của các lệnh đang mở so với ngân sách sống sót.
> **Công thức:** `Z_Load = abs(Total STL) / Cd`

*Ý nghĩa:* Tổng rủi ro các lệnh đang mở (Stop Loss) chiếm bao nhiêu phần trăm mạng sống còn lại của bạn?

---

## 3. Các Trạng thái Động lực học (Flow Regimes)

Dựa vào chỉ số $Z_{Load}$, hệ thống tự động "sang số" qua 4 trạng thái:

| Ký hiệu | Trạng thái (Regime) | Vùng Áp suất ($Z_{Load}$) | Hành động của AI (Damping) | Ý nghĩa Lâm sàng |
| :--- | :--- | :--- | :--- | :--- |
| 🟢 | **LAMINAR FLOW** | `< 0.4` (Dưới 40%) | **1.0x** (Full Volume) | An toàn tuyệt đối. Được phép Scaling (Nhồi lệnh). |
| 🟡 | **STRUCTURAL EROSION** | `0.4 - 0.75` (40% - 75%) | **0.5x** (Bóp 50% Vol) | Rủi ro trung bình. Khuyên cáo thận trọng. |
| 🔴 | **TURBULENT FORCE** | `0.75 - 1.0` (75% - 100%)| **0.1x** (Bóp 90% Vol) | Báo động đỏ. Tiệm cận vùng cháy ngân sách. Cấm nhồi lệnh lớn. |
| 🚨 | **CRITICAL BREACH** | `> 1.0` (Trên 100%) | **0.0x** (Khóa lệnh mới) | Vỡ Cấu Trúc! Bạn đã vào lệnh quá lớn so với vốn sống sót. Phải tự hạ Volume. |

---

## 4. Các Ví dụ Minh họa (Scenarios)

### Kịch bản 1: Quả cầu Tuyết (Snowball - Thắng liên tiếp)
* **Khởi đầu:** Daily Plan = 150$. 
* **Hành động:** Bạn đánh 1 lệnh lời 100$ và chưa chốt (Total PnL = +100$).
* **Năng lực:** $C_d$ = 150 + 100 = 250$.
* **Nhồi lệnh:** Bạn mở thêm 1 lệnh mới có SL là 80$.
* **Đo lường:** $Z_{Load}$ = 80 / 250 = **0.32 (32%)**.
* **Kết quả:** Hệ thống báo 🟢 **LAMINAR FLOW**. Bạn vẫn an toàn tuyệt đối nhờ lấy mỡ nó rán nó!

### Kịch bản 2: Vòng xoáy Tử thần (Death Spiral - Thua lỗ & Trả thù)
* **Khởi đầu:** Daily Plan = 150$.
* **Hành động:** Bạn đánh thua và đang âm 100$ (Total PnL = -100$).
* **Năng lực:** $C_d$ = 150 - 100 = **Chỉ còn 50$**.
* **Nhồi lệnh:** Bạn cay cú vào 1 lệnh có rủi ro SL là 45$.
* **Đo lường:** $Z_{Load}$ = 45 / 50 = **0.9 (90%)**.
* **Kết quả:** Hệ thống báo 🔴 **TURBULENT FORCE**. Trí tuệ nhân tạo nhận diện sự nguy hiểm và ép Volume lệnh tiếp theo của bạn xuống chỉ còn 0.1x.