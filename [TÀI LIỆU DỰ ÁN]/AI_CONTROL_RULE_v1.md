# ⚖️ CÁC GIAO THỨC ĐIỀU KHIỂN AI (v2)

## 1. Cơ chế Giảm chấn (Kiểm soát Dòng chảy)
AI hoạt động như một **Van Nhiệt động lực học**. Nó đọc `velocity` (trục Z) và tiết chế `Volume` (Lưu lượng) dựa trên `flyhome_matrices.YAML`.

### A. Trạng thái Hỗn loạn (Turbulent - Entropy Cao)
* **Điều kiện:** $v >$ `velocity_thresholds.erosion_max`
* **Hành động:** Áp dụng `damping_factors.turbulent` (Mặc định: **0.3x**).
* **Mô tả:** Bóp nghẹt ngay lập tức. Giảm quy mô lệnh xuống còn 30%. Tập trung vào sinh tồn.

### B. Trạng thái Xói mòn (Erosion - Rò rỉ Năng lượng)
* **Điều kiện:** $v$ nằm giữa `laminar_max` và `erosion_max`.
* **Hành động:** Áp dụng `damping_factors.erosion` (Mặc định: **0.7x**).
* **Mô tả:** "Niêm phong mềm". Chặn các nút (lệnh) mới. Chỉ quản lý các vị thế hiện tại.

### C. Trạng thái Dòng chảy tầng (Laminar - Trôi chảy)
* **Điều kiện:** $v \le$ `velocity_thresholds.laminar_max`.
* **Hành động:** Áp dụng `damping_factors.laminar` (Mặc định: **1.0x**).
* **Mô tả:** Exergy Tối ưu. Hệ thống vận hành ở công suất tối đa.

---

## 2. Giao thức Giáp Z (Công tắc Tử thần)
Nếu $Equity \le$ `constitution.global_limits.equity_floor_usd`:
1.  **Cắt đứt:** Ngắt kết nối API tới Broker.
2.  **Tắt đèn (Blackout):** Giao diện chuyển sang Xám/Đen (Vùng chết).
3.  **Khóa:** Hệ thống yêu cầu Khóa Admin (Can thiệp thủ công) để khởi động lại.

## 3. Vật lý Hồi phục
Để ngăn chặn "Sốc tái nhập" (Re-entry Shock), hệ thống yêu cầu sự ổn định:
* **Thời gian:** Phải duy trì trạng thái **Laminar** trong `stabilization_period_min`.
* **Xu hướng:** Equity phải cắt lên trên đường `min_equity_recovery_ma` của nó.