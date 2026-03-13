# 🌀 MA TRẬN TRẠNG THÁI AI (AI STATE MATRIX)

## 1. Định nghĩa Không gian Trạng thái 3D
Hệ thống AI Cockpit định vị mình trong một không gian 3 chiều để đánh giá "sức khỏe" của dòng chảy Equity.

### Trục X: Momentum (Động lượng)
- **Nguồn:** `Cookpit!NET P/L`
- **Ý nghĩa:** Đo lường sức mạnh của xu hướng tăng trưởng tài khoản.
- **Logic:** Momentum dương lớn cho phép AI mở rộng biên độ giao dịch.

### Trục Y: Stress (Áp suất)
- **Nguồn:** `Cookpit!STRESS IDX`
- **Ý nghĩa:** Đo lường áp lực ký quỹ (Margin) và rủi ro sụt giảm tiềm tàng.
- **Logic:** Khi Stress vượt 50%, AI bắt đầu kích hoạt cơ chế phòng vệ chủ động.

### Trục Z: Velocity (Vận tốc Entropy)
- **Nguồn:** Tính toán đạo hàm `dDD/dt` (Biến thiên Drawdown).
- **Ý nghĩa:** Tốc độ mất năng lượng. Đây là biến số "sống còn".
- **Logic:** Velocity tăng đột biến là dấu hiệu của "Sốc nhiệt" (Flash Risk).

---

## 2. Bảng Trạng thái Nhiệt động lực học
AI sẽ phân loại hệ thống vào một trong các trạng thái sau dựa trên tọa độ ma trận:

| Trạng thái | Điều kiện (Velocity) | Đặc điểm |
| :--- | :--- | :--- |
| **LAMINAR** | $v \le 0.001$ | Dòng chảy tầng, ổn định tuyệt đối. |
| **EROSION** | $0.001 < v \le 0.005$ | Rò rỉ năng lượng, có dấu hiệu nhiễu. |
| **TURBULENT** | $v > 0.005$ | Dòng chảy xoáy, mất kiểm soát xung lực. |
3. Bản đồ Hành động theo Tọa độ (Action Mapping)AI sẽ xác định hành động dựa trên vị trí của hệ thống trong không gian 3D. Mỗi khu vực (Zone) đại diện cho một trạng thái nhiệt động lực học khác nhau.A. Khu vực Tăng trưởng Laminar (Safe Zone)Tọa độ: $X(+) / Y(-) / Z(-)$Mô tả: Động lượng dương (có lãi), Áp suất thấp (Margin an toàn), Vận tốc DD thấp.AI Verdict: MAXIMIZE EXERGYHành động: * Giữ nguyên Damping Factor = 1.0.Cho phép AI đề xuất tăng quy mô (Scaling) nếu $X$ tăng bền vững.Màu sắc UI: Neon Cyan (Steady).B. Khu vực Ma sát (Warning Zone)Tọa độ: $X(-) / Y(+) / Z(Low)$Mô tả: Động lượng âm (lỗ nhẹ), Áp suất bắt đầu tăng, nhưng Vận tốc sụt giảm vẫn trong tầm kiểm soát.AI Verdict: FRICTION ALERTHành động:Kích hoạt Damping Factor = 0.7.Chặn mở thêm các cặp tiền mới (Node Lock).Rà soát các lệnh có tương quan (Correlation) cao hơn 0.7.Màu sắc UI: Neon Yellow (Flicker).C. Khu vực Xoáy (Critical Zone)Tọa độ: $X(--) / Y(++) / Z(+)$Mô tả: Lỗ sâu, Áp suất Margin vượt ngưỡng 50%, Vận tốc DD tăng vọt ($> 0.005$).AI Verdict: TURBULENT DAMPINGHành động:Cưỡng bức Damping Factor = 0.3.Panic Kill Recommendation: Đề xuất đóng ngay các vị thế gây "nhiệt" lớn nhất (High Entropy positions).Tự động dời Stoploss về vùng an toàn cho các lệnh còn lại.Màu sắc UI: Neon Red (Pulse).D. Khu vực Đóng băng (Dead Zone)Tọa độ: $Equity \le Z-Armor Floor$ ($85K)Mô tả: Chạm ngưỡng sàn hiến pháp.AI Verdict: SYSTEM HIBERNATIONHành động:Ngắt toàn bộ kết nối giao dịch (Hard Kill).Chuyển trạng thái sang "Manual Recovery Only".Yêu cầu Trader thực hiện Quy trình bảo trì (Maintenance SOP).