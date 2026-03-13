import os
import yaml
from datetime import datetime
import logging
from database import SessionLocal, TradingAccount, SystemState, RiskHardLimit, RiskTactical, NeuralProfile, TelegramConfig

logger = logging.getLogger("ZArmor_Main")

# ==========================================================
# TÍCH HỢP ĐỌC FILE YAML (THE TRINITY CONFIG)
# ==========================================================
def load_yaml_config(filename):
    filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", filename)
    if not os.path.exists(filepath):
        logger.warning(f"⚠️ Không tìm thấy file {filename}")
        return {}
    with open(filepath, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def get_yaml_configs():
    return {
        "physics": load_yaml_config("zarmor_physics_core.yaml"),
        "neural": load_yaml_config("zarmor_ai_neural.yaml"),
        "tactical": load_yaml_config("zarmor_tactical_ops.yaml")
    }

# ==========================================================
# CÁC HÀM QUẢN LÝ DB (ĐÃ BỌC THÉP CHỐNG LỖI ORM)
# ==========================================================
def perform_daily_rollover():
    """Chạy rollover nếu đúng giờ. Trả về True nếu có rollover xảy ra."""
    db = SessionLocal()
    try:
        now = datetime.now()
        today_str = now.strftime('%Y-%m-%d')
        changed = False
        accounts = db.query(TradingAccount).all()
        for acc in accounts:
            acc_id = str(getattr(acc, 'account_id', None) or acc.id)
            state = db.query(SystemState).filter(SystemState.account_id == acc_id).first()
            tactical = db.query(RiskTactical).filter(RiskTactical.account_id == acc_id).first()
            
            if state and tactical:
                rollover_hour = getattr(tactical, 'rollover_hour', 0) or 0
                if now.hour == rollover_hour and getattr(state, 'last_reset_date', None) != today_str:
                    if getattr(state, 'is_hibernating', False): state.is_hibernating = False
                    state.last_reset_date = today_str
                    changed = True
        if changed: db.commit()
        return changed  # BUG 1 FIX: trả về True khi có rollover thực sự
    except Exception as e: 
        logger.error(f"Lỗi Rollover: {e}")
        db.rollback()
        return False
    finally: 
        db.close()

def get_all_units():
    db = SessionLocal()
    units = {}
    try:
        accounts = db.query(TradingAccount).all()
        for acc in accounts:
            # Phase 4B FIX: Lọc orphan rows — account_id=None xảy ra khi
            # TradingAccount được tạo với id=mt5_login (int PK) thay vì account_id (string)
            # Những row này không có account_id hợp lệ → bỏ qua
            raw_acc_id = getattr(acc, 'account_id', None)
            if not raw_acc_id:
                continue  # Skip orphan row

            acc_id = str(raw_acc_id)

            # 💡 TRUY VẤN TRỰC TIẾP: Chống tuyệt đối lỗi "Has no attribute"
            sys_state = db.query(SystemState).filter(SystemState.account_id == acc_id).first()
            tg_cfg    = db.query(TelegramConfig).filter(TelegramConfig.account_id == acc_id).first()
            neural    = db.query(NeuralProfile).filter(NeuralProfile.account_id == acc_id).first()
            tactical  = db.query(RiskTactical).filter(RiskTactical.account_id == acc_id).first()
            hard      = db.query(RiskHardLimit).filter(RiskHardLimit.account_id == acc_id).first()

            units[acc_id] = {
                "alias": getattr(acc, 'alias', acc_id),
                "mt5_login": acc_id,
                "mt5_password": getattr(acc, 'password', ""),
                "mt5_server": getattr(acc, 'server', ""),
                "is_locked": getattr(sys_state, 'is_locked', False) if sys_state else False,
                "is_hibernating": getattr(sys_state, 'is_hibernating', False) if sys_state else False,
                "telegram_config": {
                    "chat_id": getattr(tg_cfg, 'chat_id', "") if tg_cfg else "",
                    "is_active": getattr(tg_cfg, 'is_active', True) if tg_cfg else True
                },
                "neural_profile": {
                    "trader_archetype": getattr(neural, 'trader_archetype', "UNKNOWN") if neural else "UNKNOWN",
                    "historical_win_rate": getattr(neural, 'historical_win_rate', 40.0) if neural else 40.0,
                    "historical_rr": getattr(neural, 'historical_rr', 1.5) if neural else 1.5,
                    "optimization_bias": getattr(neural, 'optimization_bias', "SURVIVAL") if neural else "SURVIVAL",
                    "trust_status": getattr(neural, 'trust_status', "NORMAL") if neural else "NORMAL"
                },
                "risk_params": {
                    # ── Tactical (MacroModal + rollover settings) ─────────
                    "daily_limit_money": getattr(tactical, 'daily_limit_money', 150.0) if tactical else 150.0,
                    "profit_lock_pct":   getattr(tactical, 'profit_lock_pct',   40.0)  if tactical else 40.0,
                    "rollover_hour":     getattr(tactical, 'rollover_hour',     0)     if tactical else 0,
                    "broker_timezone":   getattr(tactical, 'broker_timezone',   2)     if tactical else 2,
                    "target_profit":     getattr(tactical, 'target_profit',     0.0)   if tactical else 0.0,
                    "target_timeframe":  getattr(tactical, 'target_timeframe',  "MONTH") if tactical else "MONTH",
                    # ── Hard Limits (SetupModal — Hiến Pháp vật lý) ───────
                    "max_daily_dd_pct":  getattr(hard, 'max_daily_dd_pct', 5.0)    if hard else 5.0,
                    "max_dd":            getattr(hard, 'max_dd_pct',        10.0)   if hard else 10.0,
                    # BUG A FIX: đọc consistency_pct (%), không phải hard_floor_money ($)
                    "consistency":       getattr(hard, 'consistency_pct',   97.0)   if hard else 97.0,
                    "dd_type":           getattr(hard, 'dd_mode',           "STATIC") if hard else "STATIC"
                }
            }
    except Exception as e:
        logger.error(f"Lỗi get_all_units: {e}")
    finally:
        db.close()
    return units

def update_unit_from_payload(mt5_login, payload):
    db = SessionLocal()
    try:
        login_str = str(mt5_login)
        if not login_str: return False
        
        # BUGFIX: TradingAccount.id là int PK, phải query bằng account_id (string MT5)
        acc = db.query(TradingAccount).filter(TradingAccount.account_id == login_str).first()
        if not acc:
            acc = TradingAccount(account_id=login_str)
            db.add(acc)
            db.flush()

        # Cập nhật an toàn với getattr/hasattr
        if "alias" in payload: 
            acc.alias = payload["alias"]
        if hasattr(acc, 'server') and "mt5_server" in payload: 
            acc.server = payload["mt5_server"]
        if hasattr(acc, 'password') and "mt5_password" in payload: 
            acc.password = payload["mt5_password"]

        # 💡 LƯU TRỰC TIẾP VÀO TỪNG BẢNG
        # 1. System State
        sys_state = db.query(SystemState).filter(SystemState.account_id == login_str).first()
        if not sys_state:
            sys_state = SystemState(account_id=login_str)
            db.add(sys_state)

        # BUG 1 FIX: Không hard-code is_locked = True mọi lúc.
        # Chỉ ARM (is_locked=True) khi payload gửi rõ ràng "arm": True
        # MacroModal gọi update-unit-config chỉ để save budget → KHÔNG lock
        # handleArmSystem mới gọi với "arm": True → mới lock
        if payload.get("arm") is True:
            sys_state.is_locked = True
            sys_state.is_hibernating = False
        elif payload.get("arm") is False:
            sys_state.is_locked = False
        
        # 2. Telegram Config
        tg_cfg = db.query(TelegramConfig).filter(TelegramConfig.account_id == login_str).first()
        if not tg_cfg:
            tg_cfg = TelegramConfig(account_id=login_str)
            db.add(tg_cfg)
        tg = payload.get("telegram_config", {})
        if "chat_id" in tg: tg_cfg.chat_id = str(tg["chat_id"])
        if "is_active" in tg: tg_cfg.is_active = tg["is_active"]
        
        # 3. Tactical Limit
        tactical = db.query(RiskTactical).filter(RiskTactical.account_id == login_str).first()
        if not tactical:
            tactical = RiskTactical(account_id=login_str)
            db.add(tactical)
            
        # 4. Hard Limit
        hard = db.query(RiskHardLimit).filter(RiskHardLimit.account_id == login_str).first()
        if not hard:
            hard = RiskHardLimit(account_id=login_str)
            db.add(hard)
            
        risk = payload.get("risk_params", {})
        # ── BUG B FIX: Source-based guard — chỉ SetupModal mới được ghi Hiến Pháp ──
        # MacroModal gửi source="MacroModal" → chỉ ghi tactical fields
        # SetupModal không gửi source (hoặc source="SetupModal") → ghi hard limits
        source = payload.get("source", "SetupModal")

        # ── Tactical fields — cả 2 modal đều được ghi ─────────────────
        # Hỗ trợ cả 2 tên field (tactical_daily_money từ MacroModal, daily_limit_money từ SetupModal)
        if "tactical_daily_money" in risk: tactical.daily_limit_money = float(risk["tactical_daily_money"])
        if "daily_limit_money"    in risk: tactical.daily_limit_money = float(risk["daily_limit_money"])
        if "profit_lock_pct"      in risk: tactical.profit_lock_pct   = float(risk["profit_lock_pct"])
        if "rollover_hour"        in risk: tactical.rollover_hour      = int(risk["rollover_hour"])
        if "broker_timezone"      in risk: tactical.broker_timezone    = int(risk["broker_timezone"])
        if "target_profit"        in risk: tactical.target_profit      = float(risk["target_profit"])
        if "target_timeframe"     in risk: tactical.target_timeframe   = str(risk["target_timeframe"])

        # ── Hard Limit fields — CHỈ SetupModal mới được ghi ───────────
        if source != "MacroModal":
            if "max_daily_dd_pct" in risk:
                hard.max_daily_dd_pct = float(risk["max_daily_dd_pct"])
            if "max_dd" in risk:
                hard.max_dd_pct = float(risk["max_dd"])
            if "consistency" in risk:
                # BUG A FIX: ghi vào consistency_pct (%), không phải hard_floor_money ($)
                hard.consistency_pct  = float(risk["consistency"])
                hard.hard_floor_money = 0.0   # reset legacy field để tránh nhầm lẫn
            if "dd_type" in risk:
                hard.dd_mode = str(risk["dd_type"])

        # 5. Neural Profile
        neural = db.query(NeuralProfile).filter(NeuralProfile.account_id == login_str).first()
        if not neural:
            neural = NeuralProfile(account_id=login_str)
            db.add(neural)
        np = payload.get("neural_profile", {})
        if "historical_win_rate" in np: neural.historical_win_rate = float(np["historical_win_rate"])
        if "historical_rr" in np: neural.historical_rr = float(np["historical_rr"])
        if "optimization_bias" in np: neural.optimization_bias = str(np["optimization_bias"])

        db.commit()
        return True
    except Exception as e:
        logger.error(f"Lỗi update DB: {e}")
        db.rollback()
        raise e  
    finally:
        db.close()

def set_lock_status(mt5_login, is_locked, is_hibernating=None):
    db = SessionLocal()
    try:
        state = db.query(SystemState).filter(SystemState.account_id == str(mt5_login)).first()
        if state:
            state.is_locked = is_locked
            if is_hibernating is not None: state.is_hibernating = is_hibernating
            db.commit()
            return True
        return False
    finally:
        db.close()