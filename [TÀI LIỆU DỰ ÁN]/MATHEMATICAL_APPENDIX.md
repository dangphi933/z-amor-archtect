# 📐 PHỤ LỤC TOÁN HỌC (v2)

## 1. Entropy Hệ thống ($S_{sys}$)

Entropy không chỉ là Drawdown; nó là tổng có trọng số của sự hỗn loạn thị trường.

$$S_{sys} = \sum (w_i \cdot f_i)$$

Trong đó $w_i$ là các trọng số được định nghĩa trong `entropy_weights` (YAML):
* $f_{price}$: Độ nhiễu hành động giá (Chiều Fractal).
* $f_{vol}$: Biến thiên độ động (Thay đổi nhiệt độ).
* $f_{flow}$: Bất thường về Thanh khoản/Volume.

*Kết quả được chuẩn hóa về [0, 1] cho thanh Entropy trên giao diện.*

## 2. Định luật Khí lý tưởng trong Trading

Chúng ta ánh xạ Định luật Khí lý tưởng ($PV = nRT$) sang các ràng buộc giao dịch:

$$P \cdot V = \mu \cdot T$$

* **$P$ (Áp suất):** Mức sử dụng Margin (%).
* **$V$ (Thể tích):** Tổng số Lots đang mở.
* **$\mu$ (Thanh khoản):** Hằng số độ sâu thị trường.
* **$T$ (Nhiệt độ):** Biến động thị trường (Volatility).

**Định lý:** Nếu Biến động thị trường ($T$) tăng lên, để giữ cho Áp suất ($P$) không đổi (an toàn), Thể tích ($V$) **BẮT BUỘC phải giảm**.
* *Phương trình này chứng minh sự cần thiết về mặt vật lý của Cơ chế Giảm chấn.*

## 3. Vận tốc ($v$)
Đạo hàm bậc nhất của Drawdown ($D$):

$$v = \frac{\Delta DD}{\Delta t}$$

* Nếu $v$ dương và lớn: Tài khoản đang rơi tự do. **(Turbulent)**
* Nếu $v$ gần bằng 0: Tài khoản ổn định. **(Laminar)**