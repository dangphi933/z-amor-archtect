# Z-ARMOR: CƠ SỞ LÝ THUYẾT HOẠCH ĐỊNH MỤC TIÊU LỢI NHUẬN (TARGET PROFIT)

**Phiên bản:** 1.0
**Hệ thống áp dụng:** Z-ARMOR OS v5.0
**Mô đun:** AI Setup Guard & Risk Engine

---

## 1. TỔNG QUAN HỆ THỐNG
Trong hệ thống Z-ARMOR, **Target Profit (Mục tiêu lợi nhuận ngày)** không phải là một con số cảm tính. Nó là một biến số đầu vào của bài toán **Tối ưu hóa Ràng buộc (Constrained Optimization)**. Nếu Target Profit được đặt quá cao so với Giới hạn rủi ro (Daily Limit) và Lợi thế thống kê (Edge), hệ thống sẽ tự động phá vỡ trạng thái LAMINAR FLOW và rơi vào vùng TURBULENT.

## 2. CƠ SỞ TOÁN HỌC: KỲ VỌNG TOÁN HỌC (EXPECTED VALUE - EV)
Mục tiêu lợi nhuận không được vượt quá tổng Kỳ vọng Toán học của hệ thống giao dịch trong giới hạn số lượng lệnh an toàn mỗi ngày.

* **Công thức EV:** `EV = (P_win * R_win) - (P_loss * R_loss)`
* **Luận điểm:** Đặt Target Profit cao hơn EV hàng ngày ép buộc Trader phải tăng tần suất giao dịch (Overtrade) hoặc tăng khối lượng (Overleverage), làm tăng rủi ro tiến gần đến mức Daily Limit.

## 3. CƠ SỞ KINH TẾ HỌC: ĐƯỜNG CONG HIỆU QUẢ MARKOWITZ
Dựa trên *Modern Portfolio Theory (MPT)*, tỷ lệ Risk/Reward không biến thiên tuyến tính.

* **Hiệu ứng cận biên:** Tại vùng rủi ro thấp, 1 đơn vị rủi ro có thể đổi lấy 1.5 đơn vị lợi nhuận. Tuy nhiên, khi cố gắng đẩy lợi nhuận lên biên độ cực đại, 1 đơn vị lợi nhuận biên có thể đòi hỏi tới 3-4 đơn vị rủi ro.
* **Quy tắc Z-ARMOR:** Target Profit phải được neo tại điểm tiếp tuyến tối ưu trên đường Efficient Frontier, nơi mà Tỷ lệ Sharpe (Sharpe Ratio) đạt mức cao nhất. Thông thường, vùng này nằm ở mức Lợi nhuận bằng **1.2x đến 2.0x** so với Rủi ro tối đa (Daily Limit).

## 4. XÁC SUẤT PHÁ SẢN (PROBABILITY OF RUIN - PoR)
Dựa trên tiêu chuẩn Kelly (Kelly Criterion), việc đặt Target xa bờ sẽ đẩy Xác suất chạm Daily Limit (PoR) tăng vọt theo hàm mũ.

* **Công thức PoR ước tính:** `PoR ≈ [(1 - Edge) / (1 + Edge)] ^ (Capital / Risk_Per_Trade)`
* **Chiến lược:** Bằng cách khóa lợi nhuận (Positive Lock) tại một mức Target hợp lý, Z-ARMOR cắt đứt chuỗi phân phối xác suất đuôi béo (fat-tail distribution) của thị trường, ép Xác suất phá sản trong ngày về mức dưới 5%.

## 5. PHƯƠNG TRÌNH TỐI ƯU Z-ARMOR (OPTIMAL TARGET FORMULA)
Dựa trên các lý thuyết trên, Z-ARMOR AI Guard sử dụng phương trình sau để tính toán và đề xuất Mục tiêu Lợi nhuận lý tưởng cho người dùng:

> **`Optimal Target ($)` = `Daily Limit ($)` * `Historical R:R` * `Entropy Modifier`**

* **Daily Limit:** Ngân sách sinh tồn trong ngày (Survival Capital).
* **Historical R:R:** Tỷ lệ Risk:Reward trung bình (Mặc định: 1.5).
* **Entropy Modifier:** Hệ số chiết khấu rủi ro thị trường (Thường từ 0.8 đến 0.9, bù trừ cho các điểm vào lệnh trượt giá hoặc sai số tâm lý).

**Ví dụ:** Nếu Trader cấp ngân sách rủi ro là 100$/ngày. Tỷ lệ R:R là 1.5 và Hệ số Entropy là 0.8.
=> Optimal Target = 100 * 1.5 * 0.8 = **120$**