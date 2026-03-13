# 🎨 UI SPECIFICATION v2: THERMODYNAMIC INTERFACE

## 1. Triết lý Thiết kế (Design Philosophy)
Giao diện không hiển thị "Tiền" (Money), mà hiển thị "Trạng thái Năng lượng" (Energy State).
* **Dark Mode (Deep Space):** Nền đen tuyệt đối (`#050505`) để làm nổi bật các luồng dữ liệu neon.
* **Physics-based Colors:** Màu sắc đại diện cho nhiệt độ và áp suất, không phải cảm xúc.
* **Data Density:** Mật độ thông tin cao nhưng phân cấp rõ ràng (Hierarchy).

## 2. Bảng màu Vật lý (Physics Color Palette)

| Màu sắc | Mã Hex | Ý nghĩa Vật lý | Trạng thái Hệ thống |
| :--- | :--- | :--- | :--- |
| **Neon Cyan** | `#00ffff` | **Gibbs Free Energy** | Equity, Lợi nhuận, Dòng chảy năng lượng hữu ích. |
| **Neon Red** | `#ff3131` | **High Entropy / Heat** | Rủi ro cao, Drawdown, Áp suất lớn, Nguy hiểm. |
| **Neon Green** | `#00ff00` | **Stability / Laminar** | Trạng thái cân bằng, Lệnh thắng, An toàn. |
| **Neon Yellow** | `#f4ff00` | **Friction / Warning** | Cảnh báo sớm, Regime Fit thấp, Ma sát. |
| **Deep Black** | `#050505` | **Void / Vacuum** | Nền tảng không gian, Vùng chết. |

## 3. Thành phần Giao diện (Component Library)

### A. The Zone (Khu vực)
* **Border:** 1px Solid `#1a1a1a` (Rất mờ, chỉ để ngăn cách không gian).
* **Background:** `#0a0a0a` (Nổi nhẹ trên nền đen).
* **Typography:** Monospace cho tiêu đề (`Courier New`) tạo cảm giác kỹ thuật, Sans-serif cho nội dung dễ đọc.

### B. The AI Matrix (Ma trận)
* **Layout:** Grid 3 cột (Entropy | Energy | Pressure).
* **Visual:** Mỗi chỉ số có một thanh màu (Bar) dọc bên cạnh.
    * Entropy cao -> Thanh đỏ cao.
    * Energy cao -> Thanh xanh cyan cao.

### C. The Panic Switch (Công tắc Chết)
* **Normal State:** Viền đỏ mờ, nền trong suốt, chữ đỏ tối.
* **Hover State:** Nền đỏ rực, chữ trắng, phát sáng (`box-shadow`).
* **Active State:** Kích hoạt lớp phủ (`Overlay`) toàn màn hình với `opacity: 0.8` và `grayscale: 100%`.

## 4. Phản hồi Thị giác (Visual Feedback)
* **Khi Turbulent:** Viền của Cockpit Container sẽ phát sáng (`box-shadow`) màu đỏ nhịp nhàng (Pulse Animation 2s).
* **Khi Locked:** Toàn bộ UI bị vô hiệu hóa (Pointer-events: none), con trỏ chuột biến mất hoặc hiện biểu tượng cấm.
