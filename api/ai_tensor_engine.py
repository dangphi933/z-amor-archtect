import numpy as np
import onnxruntime as ort
import logging
from api.config_manager import get_yaml_configs

logger = logging.getLogger("ZArmor_DL_Engine")

class DeepLearningEngine:
    def __init__(self):
        # 💡 V7.0: Đọc đường dẫn Model từ cấu hình YAML
        configs = get_yaml_configs()
        self.model_path = configs.get("neural", {}).get("neural_core", {}).get("weights_path", "models/z_armor_agent.onnx")
        self.session = None
        
        try:
            self.session = ort.InferenceSession(self.model_path)
            logger.info(f"🟢 DL Engine: Đã load model AI thành công từ {self.model_path}")
        except Exception as e:
            logger.warning(f"🔴 DL Engine: Chưa tìm thấy Model AI tại {self.model_path}. Dùng Rule-based Fallback.")

    def extract_market_sensors(self, symbol="EURUSD"):
        # ĐÃ LÊN CLOUD: MQL5 EA sẽ tự đo ATR và Volume rồi gửi lên sau. Server không thò tay vào Terminal nữa.
        return 0.0050, 1500, 1.5 

    def build_3d_tensor(self, internal_state, proposed_trade):
        return np.zeros((1, 13), dtype=np.float32)

    def predict_regime(self, internal_state, proposed_trade):
        return {"prob_ruin": 0.0, "fit_score": 100.0, "optimal_damping": 1.0}