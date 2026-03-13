import os
import json
import yaml
import logging
from datetime import datetime
import threading
import asyncio
from api.config_manager import get_all_units, get_yaml_configs

# Telegram engine — thêm send_session_debrief + send_compliance_alert
from telegram_engine import (
    push_to_telegram,
    send_defcon1_scram,
    send_defcon2_warning,
    send_defcon3_silent,
    send_session_debrief,
    send_compliance_alert,
)

# Database models mới
from database import SessionLocal, TradeHistory, SessionHistory, AuditLog

# =====================================================================
# ⚙️ CẦU NỐI KHÔNG GIAN — GIỮ NGUYÊN
# =====================================================================
def fire_async(coro):
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        threading.Thread(target=lambda: asyncio.run(coro)).start()

def safe_telegram_send(message: str, chat_id: str = None):
    target_chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
    if not target_chat_id:
        return
    fire_async(push_to_telegram(target_chat_id, message, disable_notification=False))

# =====================================================================
# CACHE IN-MEMORY — GIỮ NGUYÊN
# =====================================================================
_mt5_cache = {}
_chart_history = {}
_equity_history_queue = {}

# BUG 2 FIX: Cache units_config để tránh DB query mỗi heartbeat
# get_all_units() tốn 5 queries × N accounts — không cần refresh mỗi 30s
_units_config_cache = {}
_units_config_last_refresh = 0.0
_UNITS_CONFIG_TTL = 30.0  # Refresh tối đa mỗi 30 giây

def get_units_config_cached() -> dict:
    """Trả về units_config từ cache, refresh từ DB nếu đã quá TTL."""
    global _units_config_cache, _units_config_last_refresh
    now = datetime.now().timestamp()
    if now - _units_config_last_refresh > _UNITS_CONFIG_TTL:
        _units_config_cache = get_all_units()
        _units_config_last_refresh = now
    return _units_config_cache

def invalidate_units_cache():
    """Gọi sau khi update config để force refresh lần tiếp theo."""
    global _units_config_last_refresh
    _units_config_last_refresh = 0.0

def init_acc_cache(acc_id):
    if acc_id not in _mt5_cache:
        _mt5_cache[acc_id] = {
            "last_heartbeat": None, "balance": 0.0, "equity": 0.0, "margin": 0.0,
            "daily_closed_profit": 0.0, "positions": [], "daily_peak_equity": 0.0,
            "last_alert_state": "INIT",
            "last_alert_time": 0.0,      # BUG SPAM FIX: timestamp float cho cooldown
            "alerted_bad_trades": set(),
            "computed_physics": {},
            # ── TẦNG 1: Account-level tracking (không reset theo ngày) ──
            "initial_balance": 0.0,           # Balance lần đầu kết nối — điểm tham chiếu tuyệt đối
            "account_peak_equity": 0.0,       # Đỉnh equity all-time (ratchet lên, không bao giờ giảm)
            "account_trail_floor": 0.0,       # Sàn Trailing đã tính (ratchet lên)
        }
    if acc_id not in _chart_history:
        _chart_history[acc_id] = {"labels": [], "equity": [], "z_pressure": []}
    if acc_id not in _equity_history_queue:
        _equity_history_queue[acc_id] = []

def reset_daily_cache(acc_id: str):
    """
    BUG F FIX: Reset daily-level cache sau mỗi Rollover.
    Gọi từ main.py _rollover_loop() — không phải init (chỉ reset metrics ngày, giữ account-level).

    Reset:
      - daily_peak_equity   → về balance hiện tại (ngày mới bắt đầu từ đây)
      - daily_closed_profit → về 0
      - last_alert_state    → INIT (tránh miss alert đầu ngày)
      - _chart_history      → xóa chart cũ

    GIỮ NGUYÊN (account-level, không bao giờ reset):
      - initial_balance     → điểm tham chiếu tuyệt đối từ lần đầu kết nối
      - account_peak_equity → đỉnh all-time (chỉ ratchet lên)
      - account_trail_floor → sàn trailing đã tính (chỉ ratchet lên)
    """
    if acc_id not in _mt5_cache:
        return  # Chưa có cache → không cần reset
    cache = _mt5_cache[acc_id]
    current_balance = cache.get("balance", 0.0)

    # Reset daily metrics
    cache["daily_peak_equity"]   = current_balance   # Ngày mới bắt đầu từ balance hiện tại
    cache["daily_closed_profit"] = 0.0
    cache["last_alert_state"]    = "INIT"             # Reset để detect state change đầu ngày
    cache["last_alert_time"]     = 0.0                # Reset cooldown — ngày mới bắt đầu sạch

    # Reset chart (biểu đồ ngày mới bắt đầu trắng)
    if acc_id in _chart_history:
        _chart_history[acc_id] = {"labels": [], "equity": [], "z_pressure": []}

    # Reset velocity queue (dữ liệu velocity ngày cũ không còn ý nghĩa)
    if acc_id in _equity_history_queue:
        _equity_history_queue[acc_id] = []

    logging.getLogger("ZArmor_Main").info(f"[ROLLOVER] Cache reset cho {acc_id} — balance={current_balance:.2f}")

# =====================================================================
# 🧠 ĐỘNG CƠ VẬT LÝ V8.0 — DUAL-LAYER TRAILING DD
# =====================================================================
# ==========================================================
# 🧠 ADAPTIVE WEIGHT ENGINE (Session-based)
# ==========================================================
def compute_adaptive_weights(account_id: str) -> dict:
    db = SessionLocal()
    try:
        sessions = (
            db.query(SessionHistory)
            .filter_by(account_id=str(account_id))
            .order_by(SessionHistory.opened_at.desc())
            .limit(30)
            .all()
        )

        if not sessions:
            return {
                "daily_loss": 0.4,
                "giveback": 0.2,
                "account": 0.3,
                "margin": 0.1
            }

        loss_bias = 0.0
        giveback_bias = 0.0
        account_bias = 0.0
        margin_bias = 0.0

        n = len(sessions)
        for i, s in enumerate(sessions):
            # RECENCY FIX: session mới nhất (i=0) = weight 1.0, cũ nhất = 0.33
            recency_w = 1.0 - (i / n) * 0.67

            if s.pnl and s.pnl < 0:
                loss_bias += recency_w

            # DD-SCALE FIX: normalize về 0-1 trước khi so threshold
            # DB có thể lưu 0-100 (%) hoặc 0-1 (ratio) → guard cả 2 trường hợp
            raw_dd = s.actual_max_dd_hit or 0.0
            dd_normalized = raw_dd / 100.0 if raw_dd > 1.0 else raw_dd
            if dd_normalized > 0.7:
                account_bias += recency_w

            if s.compliance_score and s.compliance_score < 80:
                margin_bias += recency_w

            if s.pnl and s.pnl > 0 and dd_normalized > 0.5:
                giveback_bias += recency_w

        total = loss_bias + giveback_bias + account_bias + margin_bias
        if total == 0:
            total = 1.0

        w_loss    = 0.3 + (loss_bias / total) * 0.3
        w_give    = 0.1 + (giveback_bias / total) * 0.2
        w_account = 0.2 + (account_bias / total) * 0.3
        w_margin  = 0.1 + (margin_bias / total) * 0.2

        weight_sum = w_loss + w_give + w_account + w_margin

        return {
            "daily_loss": w_loss / weight_sum,
            "giveback":   w_give / weight_sum,
            "account":    w_account / weight_sum,
            "margin":     w_margin / weight_sum
        }

    except Exception:
        return {
            "daily_loss": 0.4,
            "giveback": 0.2,
            "account": 0.3,
            "margin": 0.1
        }
    finally:
        db.close()
def evaluate_cloud_physics(acc_id):
    cache = _mt5_cache[acc_id]
    units_config = get_units_config_cached()  # BUG 2 FIX: dùng cache thay vì query DB mỗi lần
    main_unit_cfg = units_config.get(acc_id, {})
    risk_params = main_unit_cfg.get("risk_params", {})
    neural_profile = main_unit_cfg.get("neural_profile", {})
    acc_chat_id = main_unit_cfg.get("telegram_config", {}).get("chat_id") or None

    is_locked = main_unit_cfg.get("is_locked", False)
    is_hibernating_flag = main_unit_cfg.get("is_hibernating", False)

    balance, equity, margin_used = cache["balance"], cache["equity"], cache["margin"]
    start_balance = balance - cache["daily_closed_profit"]

    profit_lock_pct   = float(risk_params.get("profit_lock_pct", 40.0))
    rr_ratio          = float(neural_profile.get("historical_rr", 1.5))

    # ==========================================================
    # 🔵 LAYER 2 INIT — FINALIZE DAILY BUDGET
    # ==========================================================
    daily_limit_cfg  = float(risk_params.get("daily_limit_money", 150.0))
    max_daily_dd_pct = float(risk_params.get("max_daily_dd_pct", 5.0))
    if start_balance > 0:
        hard_daily_limit = start_balance * (max_daily_dd_pct / 100.0)
    else:
        hard_daily_limit = daily_limit_cfg

    if daily_limit_cfg > 0:
        daily_limit_money = min(daily_limit_cfg, hard_daily_limit)
    else:
        daily_limit_money = hard_daily_limit

    daily_limit_money = max(daily_limit_money, 10.0)

    # ── TẦNG 1 params ────────────────────────────────────────────────
    dd_type    = str(risk_params.get("dd_type", "STATIC")).upper()   # "STATIC" | "TRAILING"
    max_dd_pct = float(risk_params.get("max_dd", 10.0))

    # Initial balance: lần đầu kết nối hoặc sau rollover thủ công
    if not cache.get("initial_balance") or cache["initial_balance"] == 0.0:
        cache["initial_balance"] = balance
    initial_balance = cache["initial_balance"]

    # ── Account-level peak tracking (ratchet — chỉ tăng, không giảm) ──
    # Phải khai báo TRƯỚC khi tính account_hard_floor (dùng ở dòng dưới)
    if not cache.get("account_peak_equity") or cache["account_peak_equity"] == 0.0:
        cache["account_peak_equity"] = equity
    if equity > cache["account_peak_equity"]:
        cache["account_peak_equity"] = equity
    account_peak_equity = cache["account_peak_equity"]

    # ── Daily peak tracking (reset mỗi Rollover qua reset_daily_cache) ──
    # PEAK-SEED FIX: seed từ max(equity, start_balance) — không phải chỉ equity
    # Khi có lệnh lỗ floating lúc kết nối: equity < start_balance
    # → daily_max_profit âm → trailing không bao giờ active cho đến khi equity > start
    if not cache.get("daily_peak_equity") or cache["daily_peak_equity"] == 0.0:
        cache["daily_peak_equity"] = max(equity, start_balance)
    if equity > cache["daily_peak_equity"]:
        cache["daily_peak_equity"] = equity
    daily_peak_equity = cache["daily_peak_equity"]

    # ── Xử lý vị thế ─────────────────────────────────────────────────
    total_stl = 0.0
    processed_positions = []

    for pos in cache["positions"]:
        profit   = float(pos.get("profit", 0))
        volume   = float(pos.get("volume") or pos.get("lots") or 0)
        open_px  = float(pos.get("open_price") or pos.get("entry_price") or 0)
        sl_px    = float(pos.get("sl") or 0)
        tp_px    = float(pos.get("tp") or 0)
        symbol   = str(pos.get("symbol") or "")
        is_buy   = int(pos.get("type", 0)) == 0

        # ── Tính sl_money / tp_money từ prices (đơn vị USD chuẩn) ──────
        # EA đôi khi gửi sai đơn vị (dùng contract_size forex thay vì đúng symbol).
        # Dùng profit hiện tại để ước tính pip_value rồi tính ngược.
        # Nếu không có profit reference → fallback về EA-provided value, sanity-check.
        sl_money = float(pos.get("sl_money") or 0)
        tp_money = float(pos.get("tp_money") or 0)

        if open_px > 0 and volume > 0:
            # Ước tính pip_value từ profit thực tế (nếu có floating pnl & price delta)
            cur_px = float(pos.get("current_price") or pos.get("price_current") or 0)
            if cur_px > 0 and abs(profit) > 0:
                price_delta = abs(cur_px - open_px)
                if price_delta > 0:
                    pip_value_per_lot = abs(profit) / (price_delta * volume)
                    # Sanity: pip_value_per_lot cho XAUUSD ≈ 100 USD/lot, EURUSD ≈ 100000 USD/lot
                    # Nhưng thực tế MT5 tính pip_value theo account currency
                    if sl_px > 0:
                        sl_dist   = abs(sl_px - open_px)
                        sl_money  = -(sl_dist * volume * pip_value_per_lot)
                    if tp_px > 0:
                        tp_dist   = abs(tp_px - open_px)
                        tp_money  = tp_dist * volume * pip_value_per_lot

            # Sanity check: nếu EA gửi sl_money có vẻ hợp lý (< equity * 0.5) thì dùng
            # Nếu bất hợp lý (> equity * 0.5) → recalc từ prices với contract_size ước tính
            if sl_money == 0 and sl_px > 0 and equity > 0:
                # Contract size map theo symbol prefix
                _sym_up = symbol.upper().replace("M", "").replace(".PRO", "").replace(".CASH", "")
                _contract = 100.0   # default XAUUSD
                if any(x in _sym_up for x in ("EUR", "GBP", "AUD", "NZD", "USD", "CHF", "CAD", "JPY")):
                    _contract = 100000.0
                elif any(x in _sym_up for x in ("BTC", "ETH", "LTC")):
                    _contract = 1.0
                elif any(x in _sym_up for x in ("NAS", "SPX", "US100", "US500", "USTEC", "DAX")):
                    _contract = 10.0
                sl_dist  = abs(sl_px - open_px)
                sl_money = -(sl_dist * volume * _contract) if sl_dist > 0 else 0
                if abs(sl_money) > equity * 0.5:
                    # Vẫn sai → normalize về profit-based ước tính hoặc để 0
                    sl_money = 0

            if tp_money == 0 and tp_px > 0 and sl_money != 0:
                sl_dist = abs(sl_px - open_px) if sl_px > 0 else 0
                tp_dist = abs(tp_px - open_px) if tp_px > 0 else 0
                if sl_dist > 0:
                    tp_money = abs(sl_money) * (tp_dist / sl_dist)

        # Nếu EA gửi sl_money đúng (âm và magnitude hợp lý) → dùng luôn
        ea_sl = float(pos.get("sl_money") or 0)
        ea_tp = float(pos.get("tp_money") or 0)
        if ea_sl < 0 and equity > 0 and abs(ea_sl) < equity * 0.5:
            sl_money = ea_sl
        if ea_tp > 0 and equity > 0 and abs(ea_tp) < equity * 2.0:
            tp_money = ea_tp

        # Đảm bảo đúng chiều: sl_money âm (rủi ro), tp_money dương (lợi nhuận)
        sl_money = -abs(sl_money) if sl_money != 0 else 0
        tp_money =  abs(tp_money) if tp_money != 0 else 0

        fit_score = 100.0
        if sl_money < 0 and profit < 0:
            fit_score = max(0.0, 100.0 - (abs(profit) / abs(sl_money)) * 100)
        elif pos.get("sl", 0) <= 0 and profit < 0:
            fit_score = max(0.0, 100.0 - (abs(profit) / 2))

        regime_status = "SYSTEM ALIGNED"
        if fit_score <= 30.0:   regime_status = "STRATEGY MISMATCH"
        elif fit_score <= 70.0: regime_status = "ELEVATED RISK"

        processed_positions.append({
            "ticket":           pos.get("ticket"),
            "symbol":           symbol,
            "side":             "BUY" if int(pos.get("type", 0)) == 0 else "SELL",
            "lots":             volume,
            "entry_price":      open_px,
            "current_price":    float(pos.get("current_price") or pos.get("price_current") or 0),
            "sl":               sl_px,
            "tp":               tp_px,
            "profit":           profit,
            "swap":             float(pos.get("swap") or 0),
            "stl_money":        round(sl_money, 2),
            "tp_money":         round(tp_money, 2),
            "regime_fit_score": round(fit_score, 1),
            "regime_status":    regime_status,
        })
        if sl_money < 0:
            total_stl += abs(sl_money)

    processed_positions.sort(key=lambda x: x["regime_fit_score"])

    # ── Velocity ─────────────────────────────────────────────────────
    current_velocity = 0.0
    current_time = datetime.now()
    _equity_history_queue[acc_id].append((current_time, equity))
    _equity_history_queue[acc_id] = [
        item for item in _equity_history_queue[acc_id]
        if (current_time - item[0]).total_seconds() <= 5.0
    ]
    if len(_equity_history_queue[acc_id]) >= 2:
        dt = (current_time - _equity_history_queue[acc_id][0][0]).total_seconds()
        if dt >= 2.0:
            current_velocity = (equity - _equity_history_queue[acc_id][0][1]) / dt

    # Tính account_hard_floor theo dd_type
    # GUARD: initial_balance có thể = 0 khi EA vừa kết nối, chưa gửi balance
    _safe_initial = initial_balance if initial_balance > 0 else (balance if balance > 0 else 1.0)

    static_floor_ref = _safe_initial * (1.0 - max_dd_pct / 100.0)
    if dd_type == "TRAILING":
        raw_trail_floor  = account_peak_equity * (1.0 - max_dd_pct / 100.0)
        # BUG TRAIL FIX: account_trail_floor = 0 khi mới init → phải seed từ static_floor_ref
        # Nếu không, prev_acc_floor = 0 → floor = raw_trail_floor nhưng bar D.TRAIL = 0%
        # vì khoảng cách equity → floor quá lớn so với expected
        prev_acc_floor = cache.get("account_trail_floor", 0.0)
        if prev_acc_floor == 0.0:
            prev_acc_floor = static_floor_ref  # seed lần đầu
        account_hard_floor = max(raw_trail_floor, prev_acc_floor, static_floor_ref)
        cache["account_trail_floor"] = account_hard_floor
    else:  # STATIC
        account_hard_floor = static_floor_ref

    dist_to_account_floor = equity - account_hard_floor
    # % drawdown so với initial balance (luôn dương khi lỗ)
    account_dd_pct = max(0.0, (_safe_initial - equity) / _safe_initial * 100.0)
    # % buffer còn lại trước khi chạm account floor (0% = đã chạm, 100% = toàn vẹn)
    # GUARD: _floor_zone phải > 0 để tránh ZeroDivisionError
    _floor_zone = _safe_initial * max_dd_pct / 100.0 if max_dd_pct > 0 else 0.0
    account_buffer_pct = max(0.0, dist_to_account_floor / _floor_zone * 100.0) if _floor_zone > 0.0 else 100.0

    # ── TẦNG 2: Base pressure từ budget ngày ─────────────────────────
    daily_floor   = start_balance - daily_limit_money
    dist_to_daily = equity - daily_floor
    abs_total_stl = abs(total_stl)

    # ==========================================================
    # 🟢 DAILY BASE PRESSURE
    # ==========================================================
    used_daily_budget = max(0.0, start_balance - equity)

    if daily_limit_money > 0:
        base_pressure = used_daily_budget / daily_limit_money
    else:
        base_pressure = 0.0

    # ── TẦNG 2: Daily trailing pressure (van điều áp lợi nhuận ngày) ─
    # TRAIL-NEGATIVE FIX: max(0.0) chặn daily_max_profit âm
    daily_trailing_pressure = 0.0
    daily_max_profit        = max(0.0, daily_peak_equity - start_balance)
    daily_allowed_giveback  = daily_max_profit * (profit_lock_pct / 100.0) if daily_max_profit > 0 else 0.0
    daily_current_giveback  = max(0.0, daily_peak_equity - equity)
    if daily_allowed_giveback > 0:
        daily_trailing_pressure = min(1.0, daily_current_giveback / daily_allowed_giveback)

    # Giveback đã dùng theo % (để hiển thị progress bar)
    daily_giveback_pct = min(100.0, daily_trailing_pressure * 100.0)

    # ── TẦNG 1: Account proximity pressure (cảnh báo sớm khi gần sàn) ─
    # Bắt đầu tăng khi buffer còn < 30% vùng max_dd → pressure 0 → 0.15
    account_proximity_pressure = 0.0
    if max_dd_pct > 0 and initial_balance > 0:
        full_zone  = initial_balance * max_dd_pct / 100.0
        warn_zone  = full_zone * 0.30  # cảnh báo khi còn 30% buffer
        if dist_to_account_floor < warn_zone:
            account_proximity_pressure = (1.0 - dist_to_account_floor / warn_zone) * 0.15 if warn_zone > 0 else 0.15

    # ── Tổng hợp Z-Pressure ──────────────────────────────────────────
    # ==========================================================
    # 🧠 VECTOR Z-PRESSURE ENGINE (Adaptive Weighted)
    # ==========================================================
    mur_pct = (margin_used / equity * 100.0) if equity > 0 else 0.0
    fre_pct = (abs_total_stl / equity * 100.0) if equity > 0 else 0.0

    adaptive_weights = compute_adaptive_weights(acc_id)

    loss_component      = min(1.0, base_pressure)
    giveback_component  = min(1.0, daily_trailing_pressure)
    account_component   = min(1.0, account_proximity_pressure / 0.15 if 0.15 > 0 else 0.0)
    margin_component    = min(1.0, mur_pct / 50.0) if equity > 0 else 0.0

    w_loss    = adaptive_weights["daily_loss"]
    w_give    = adaptive_weights["giveback"]
    w_account = adaptive_weights["account"]
    w_margin  = adaptive_weights["margin"]

    vector_pressure = (
        w_loss    * loss_component +
        w_give    * giveback_component +
        w_account * account_component +
        w_margin  * margin_component
    )

    computed_z_pressure = min(1.5, vector_pressure)

    # ── Tính saturation ──────────────────────────────────────────────
    optimal_target  = daily_limit_money * rr_ratio * 0.85
    total_pnl       = equity - start_balance
    saturation_pct  = min(100.0, (max(0.0, total_pnl) / optimal_target * 100)) if optimal_target > 0 else 0.0

    # ── STATE MACHINE ────────────────────────────────────────────────
    auto_state, auto_damping, tax_rate = "OPTIMAL_FLOW", 1.0, 0.0

    # Tầng 1: ACCOUNT_LIQUIDATION — ưu tiên tuyệt đối, override tất cả
    if dist_to_account_floor <= 0:
        auto_state, auto_damping, tax_rate = "ACCOUNT_LIQUIDATION", 0.0, 1.0
        computed_z_pressure = 2.0
    elif saturation_pct >= 100.0:
        auto_state, auto_damping, tax_rate = "POSITIVE_LOCK", 0.0, 1.0
        computed_z_pressure = 0.0
    elif dist_to_daily <= 0 or computed_z_pressure >= 1.0:
        auto_state, auto_damping, tax_rate = "CRITICAL_BREACH", 0.0, 1.0
    elif computed_z_pressure >= 0.85:
        auto_state, auto_damping, tax_rate = "TURBULENT_FORCE", 0.1, 0.8
    elif computed_z_pressure >= 0.60:
        auto_state, auto_damping, tax_rate = "KINETIC_EROSION", 0.5, 0.4
    elif computed_z_pressure >= 0.15:
        auto_state, auto_damping, tax_rate = "OPTIMAL_FLOW", 1.0, 0.0
    else:
        auto_state, auto_damping, tax_rate = "ABSOLUTE_ZERO", 1.0, 0.0

    if is_hibernating_flag and auto_state not in ["CRITICAL_BREACH", "POSITIVE_LOCK", "ACCOUNT_LIQUIDATION"]:
        auto_state, auto_damping, tax_rate = "HIBERNATING", 0.0, 0.0
    if is_locked and "BREACH" in auto_state:
        auto_state = "CRITICAL_BREACH"

    # ── Telegram alerts — rate-limited state machine ─────────────────
    # BUG SPAM FIX: 3 vấn đề cũ:
    #   1. last_alert_state = "INIT" → condition "!= INIT" chặn alert đầu → OK
    #      nhưng KHÔNG update last_alert_state → lần sau condition đúng → spam
    #   2. Không có cooldown → mỗi heartbeat (30s) đều có thể trigger alert
    #   3. fetch_dashboard_state poll mỗi 10s → toggle DISCONNECTED liên tục
    #
    # FIX: Thêm cooldown per-state (không gửi cùng state trong vòng N giây)
    #      và luôn update last_alert_state kể cả khi không gửi
    last_notified      = cache.get("last_alert_state", "INIT")
    last_alert_time    = cache.get("last_alert_time", 0)    # timestamp float
    now_ts             = datetime.now().timestamp()

    # Cooldown config: trạng thái nào được gửi lại sau bao nhiêu giây
    ALERT_COOLDOWN = {
        "ACCOUNT_LIQUIDATION": 60,    # SCRAM: 1 phút rồi nhắc lại (rất nguy hiểm)
        "CRITICAL_BREACH":     120,   # 2 phút
        "TURBULENT_FORCE":     300,   # 5 phút — tránh spam cảnh báo liên tục
        "KINETIC_EROSION":     600,   # 10 phút
        "OPTIMAL_FLOW":        0,     # chỉ gửi khi recovery (state khác vào)
        "POSITIVE_LOCK":       0,     # 1 lần
        "ABSOLUTE_ZERO":       0,     # không cần gửi
        "DISCONNECTED":        300,   # 5 phút
        "HIBERNATING":         0,
    }

    state_changed = (auto_state != last_notified)
    cooldown_ok   = (now_ts - last_alert_time) >= ALERT_COOLDOWN.get(auto_state, 300)
    # Điều kiện gửi: state thay đổi VÀ (không phải lần đầu sau INIT, HOẶC state nguy hiểm)
    should_alert = (
        state_changed and
        last_notified != "INIT" and
        auto_state not in ("ABSOLUTE_ZERO", "HIBERNATING")
    ) or (
        # Gửi lại cùng state nếu vẫn nguy hiểm và đã qua cooldown
        not state_changed and
        cooldown_ok and
        auto_state in ("ACCOUNT_LIQUIDATION", "CRITICAL_BREACH", "TURBULENT_FORCE") and
        last_alert_time > 0  # đã gửi ít nhất 1 lần trước rồi mới repeat
    )

    if should_alert:
        trader_name = main_unit_cfg.get("alias", f"Trader {acc_id}")

        if auto_state == "ACCOUNT_LIQUIDATION":
            loss_amount = round(max(0.0, initial_balance - equity), 2)
            fire_async(send_defcon1_scram(
                chat_id=acc_chat_id, trader_name=trader_name,
                loss_amount=loss_amount
            ))
            fire_async(send_defcon3_silent(
                chat_id=acc_chat_id,
                title=f"☢️ ACCOUNT {'TRAILING' if dd_type == 'TRAILING' else 'STATIC'} DD FLOOR BỊ XUYÊN THỦNG",
                message=(
                    f"Trạm {trader_name} — Equity ${equity:,.2f} đã xuyên qua "
                    f"{'Trailing' if dd_type == 'TRAILING' else 'Static'} Floor "
                    f"${account_hard_floor:,.2f} (Max DD {max_dd_pct}%). "
                    f"Hệ thống buộc SCRAM để bảo vệ tài khoản."
                )
            ))
        elif auto_state == "POSITIVE_LOCK":
            fire_async(send_defcon3_silent(
                chat_id=acc_chat_id, title="ĐIỂM BÃO HÒA (POSITIVE LOCK) 🏆",
                message=f"Trạm {trader_name} đã đạt 100% mục tiêu lượng tử (${optimal_target:.2f}). Hệ thống tự động ĐÓNG BĂNG ĐỂ BẢO VỆ THÀNH QUẢ."
            ))
        elif auto_state == "CRITICAL_BREACH":
            loss_amount = start_balance - equity if start_balance > equity else 0
            fire_async(send_defcon1_scram(
                chat_id=acc_chat_id, trader_name=trader_name,
                loss_amount=round(loss_amount, 2)
            ))
        elif auto_state == "TURBULENT_FORCE":
            used_budget = start_balance - equity if start_balance > equity else 0
            fire_async(send_defcon2_warning(
                chat_id=acc_chat_id, trader_name=trader_name,
                used_budget=round(used_budget, 2), max_budget=round(daily_limit_money, 2)
            ))
        elif auto_state == "OPTIMAL_FLOW" and last_notified in ["KINETIC_EROSION", "TURBULENT_FORCE"]:
            fire_async(send_defcon3_silent(
                chat_id=acc_chat_id, title="HỆ THỐNG TRỞ VỀ VÙNG VÀNG ✅",
                message=f"Áp suất của trạm {trader_name} đã giảm an toàn. Tiếp tục vận hành Radar."
            ))

        cache["last_alert_time"] = now_ts

    # Luôn update last_alert_state (kể cả INIT → không spam lần sau)
    if state_changed:
        cache["last_alert_state"] = auto_state

    # ── Chart history ────────────────────────────────────────────────
    now_str = datetime.now().strftime("%H:%M:%S")
    ch = _chart_history[acc_id]
    if len(ch["equity"]) == 0 or now_str != ch["labels"][-1]:
        ch["labels"].append(now_str)
        ch["equity"].append(equity)
        ch["z_pressure"].append(computed_z_pressure)
        if len(ch["labels"]) > 30:
            ch["labels"].pop(0); ch["equity"].pop(0); ch["z_pressure"].pop(0)

    dbu_pct = ((start_balance - equity) / daily_limit_money) * 100.0 if start_balance > equity else 0.0
    # Capital Buffer Remaining: % equity còn lại so với account floor
    cbr_pct = min(100.0, account_buffer_pct)

    cache["computed_physics"] = {
        # ── Core ─────────────────────────────────────────────────────
        "state":            auto_state,
        "adaptive_weights": adaptive_weights,
        "z_pressure":       round(computed_z_pressure, 4),
        "damping_factor":   auto_damping,
        "entropy_tax_rate": tax_rate,
        "velocity":         current_velocity,
        "is_hibernating":   is_hibernating_flag,
        # ── Z-Pressure components ────────────────────────────────────
        "base_pressure":               round(base_pressure, 4),
        "daily_trailing_pressure":     round(daily_trailing_pressure, 4),
        "trailing_pressure":           round(daily_trailing_pressure, 4),   # alias backward compat
        "account_proximity_pressure":  round(account_proximity_pressure, 4),
        # ── TẦNG 2: Daily metrics ────────────────────────────────────
        "daily_peak":              round(daily_peak_equity, 2),
        "peak_equity":             round(daily_peak_equity, 2),          # alias backward compat
        "budget_capacity":         round(daily_limit_money, 2),
        "budget_capacity_cfg":     round(daily_limit_cfg, 2),            # budget user set (trước cap)
        "daily_floor":             round(daily_floor, 2),
        "rem_capacity":            round(dist_to_daily, 2),
        "daily_giveback_pct":      round(daily_giveback_pct, 2),
        "daily_max_profit":        round(daily_max_profit, 2),           # $ lãi đỉnh ngày
        "daily_allowed_giveback":  round(daily_allowed_giveback, 2),     # $ van cho phép giveback
        "dbu_pct":                 round(dbu_pct, 2),
        "fre_pct":                 round(fre_pct, 2),
        "cbr_pct":                 round(cbr_pct, 2),
        # ── TẦNG 1: Account metrics ──────────────────────────────────
        "dd_type":               dd_type,
        "max_dd_pct":            max_dd_pct,
        "initial_balance":       round(initial_balance, 2),
        "account_peak":          round(account_peak_equity, 2),
        "account_hard_floor":    round(account_hard_floor, 2),
        "dist_to_account_floor": round(dist_to_account_floor, 2),
        "account_dd_pct":        round(account_dd_pct, 2),
        "account_buffer_pct":    round(min(100.0, account_buffer_pct), 2),
    }
    cache["processed_positions"] = processed_positions
    cache["total_stl"]  = -round(total_stl, 2)
    cache["total_pnl"]  = round(total_pnl, 2)


# =====================================================================
# WEBHOOK HANDLERS — GIỮ NGUYÊN
# =====================================================================
def update_webhook_heartbeat(data: dict):
    acc_id = str(data.get("account_id"))
    init_acc_cache(acc_id)
    cache = _mt5_cache[acc_id]
    old_profit = cache.get("daily_closed_profit", 0.0)
    new_profit  = float(data.get("daily_closed_profit", 0.0))
    last_hb     = cache["last_heartbeat"]

    cache["last_heartbeat"]      = datetime.now()
    cache["balance"]             = float(data.get("balance", 0))
    cache["equity"]              = float(data.get("equity", 0))
    cache["margin"]              = float(data.get("margin", 0))
    cache["daily_closed_profit"] = new_profit
    evaluate_cloud_physics(acc_id)

    if last_hb is not None and abs(new_profit - old_profit) > 0.01:
        if new_profit != 0:
            diff = new_profit - old_profit
            icon = "🟢 <b>CHỐT LỜI TÍCH CỰC!</b>" if diff > 0 else "🔴 <b>CẮT LỖ BẢO VỆ VỐN!</b>"
            msg  = (
                f"{icon}\n👤 <b>Tài khoản:</b> <code>{acc_id}</code>\n"
                f"💵 <b>Lệnh vừa đóng:</b> <b>{'+' if diff > 0 else ''}${diff:,.2f}</b>\n"
                f"⚖️ <b>Vốn (Balance):</b> ${cache['balance']:,.2f}"
            )
            # CACHE-BYPASS FIX: dùng cached version thay vì get_all_units() trực tiếp
            acc_chat_id = get_units_config_cached().get(acc_id, {}).get("telegram_config", {}).get("chat_id") or None
            safe_telegram_send(msg, chat_id=acc_chat_id)

def update_webhook_positions(account_id: str, positions: list, balance: float = None, equity: float = None):
    acc_id = str(account_id)
    init_acc_cache(acc_id)
    cache = _mt5_cache[acc_id]
    cache["last_heartbeat"] = datetime.now()
    cache["positions"]      = positions

    # FIX: nếu EA gửi kèm balance/equity trong payload positions → cập nhật luôn
    # tránh race condition khi /webhook/positions đến trước /webhook/heartbeat
    if balance is not None and float(balance) > 0:
        cache["balance"] = float(balance)
    if equity is not None and float(equity) > 0:
        cache["equity"] = float(equity)

    # Chỉ evaluate khi đã có balance hợp lệ — tránh tính sai với balance=0
    if cache.get("balance", 0) > 0:
        evaluate_cloud_physics(acc_id)
    else:
        # Balance chưa có (heartbeat chưa đến) — vẫn lưu positions thô
        # processed_positions sẽ được build lần sau khi heartbeat đến
        cache["processed_positions"] = []
        for pos in positions:
            sl_money = pos.get("sl_money", 0)
            tp_money = pos.get("tp_money", 0)
            profit   = float(pos.get("profit", 0))
            cache["processed_positions"].append({
                "ticket": pos.get("ticket"), "symbol": pos.get("symbol"),
                "side": "BUY" if pos.get("type") == 0 else "SELL",
                "lots": float(pos.get("volume") or 0), "entry_price": float(pos.get("open_price") or 0),
                "current_price": float(pos.get("current_price") or pos.get("price_current") or 0),
                "sl": float(pos.get("sl") or 0), "tp": float(pos.get("tp") or 0),
                "profit": profit,
                "swap": float(pos.get("swap") or 0),
                "stl_money": sl_money if sl_money < 0 else 0,
                "tp_money": tp_money,
                "regime_fit_score": 100.0,
                "regime_status": "AWAITING BALANCE"
            })

async def fetch_dashboard_state(account_id: str = ""):
    acc_id = str(account_id) if account_id and account_id != "MainUnit" else "MainUnit"
    init_acc_cache(acc_id)
    cache        = _mt5_cache[acc_id]
    units_config = get_units_config_cached()  # BUG 2 FIX: dùng cache

    bridge_active = cache["last_heartbeat"] and (datetime.now() - cache["last_heartbeat"]).total_seconds() <= 90  # FIX: EA heartbeat 30s, threshold 90s

    if not bridge_active:
        last_notified = cache.get("last_alert_state", "INIT")
        last_alert_time = cache.get("last_alert_time", 0.0)
        now_ts = datetime.now().timestamp()
        disconnected_cooldown_ok = (now_ts - last_alert_time) >= 300

        # BUG 5 FIX: Gộp 2 điều kiện thành 1 rõ ràng
        # Gửi alert khi: (1) vừa mất kết nối lần đầu, hoặc (2) đã DISCONNECTED và cooldown xong
        # FIX: INIT chỉ suppress 30s sau server start; DISCONNECTED cooldown 5 phút
        import time as _t
        _server_up = getattr(fetch_dashboard_state, "_start_ts", None)
        if _server_up is None:
            fetch_dashboard_state._start_ts = _t.time()
            _server_up = fetch_dashboard_state._start_ts
        _warm_up_done = (_t.time() - _server_up) > 30

        should_send_disconnect = (
            last_notified not in ("DISCONNECTED", "INIT")  # lần đầu mất kết nối
            or (last_notified == "INIT" and _warm_up_done)  # sau warm-up, INIT cũng cần alert
        ) or (
            last_notified == "DISCONNECTED" and disconnected_cooldown_ok  # repeat sau 5 phút
        )
        if should_send_disconnect:
            trader_name = units_config.get(acc_id, {}).get("alias", f"Trader {acc_id}")
            acc_chat_id = units_config.get(acc_id, {}).get("telegram_config", {}).get("chat_id") or None
            fire_async(send_defcon3_silent(
                chat_id=acc_chat_id, title="MẤT KẾT NỐI EA MT5 🔌",
                message=f"Radar đã mất tín hiệu từ trạm {trader_name}. Vui lòng kiểm tra lại VPS/MT5."
            ))
            cache["last_alert_state"] = "DISCONNECTED"
            cache["last_alert_time"]  = now_ts
        physics_data = {"state": "DISCONNECTED", "z_pressure": 0.0, "budget_capacity": 150.0}
    else:
        physics_data = cache.get("computed_physics", {"state": "SCANNING", "z_pressure": 0.0, "budget_capacity": 150.0})

    return {
        "global_status": {
            "license_active": True,
            "balance": cache["balance"], "equity": cache["equity"],
            "total_pnl": cache.get("total_pnl", 0.0),
            "total_stl": cache.get("total_stl", 0.0),
            "total_tp_reward": sum(p.get("tp_money", 0) for p in cache.get("processed_positions", [])),
            "open_trades": cache.get("processed_positions", []),
            "physics": physics_data,
            "daily_pnl_money": round(cache["daily_closed_profit"] + cache.get("total_pnl", 0.0), 2),
            "start_balance": round(cache["balance"] - cache["daily_closed_profit"], 2),
            "chart_data": _chart_history[acc_id] if bridge_active else {"labels": [], "equity": [], "z_pressure": []},
            "macro_metrics": {
                "initial_capital":    cache.get("initial_balance", cache["balance"]),
                "account_peak":       physics_data.get("account_peak", cache["balance"]),
                "account_hard_floor": physics_data.get("account_hard_floor", 0),
                "dd_type":            physics_data.get("dd_type", "STATIC"),
                "max_dd_pct":         physics_data.get("max_dd_pct", 10.0),
                "retention_pct":      97.0,
                "max_sys_dd_pct":     physics_data.get("max_dd_pct", 10.0),
            }
        },
        "units_config": units_config
    }


# =====================================================================
# ══ MỚI: AI AGENT ENDPOINT HANDLERS ══════════════════════════════════
# Được gọi từ main.py — các route POST/GET mới thêm vào router
# =====================================================================

# ── 1. LOG TRADE ─────────────────────────────────────────────────────
def api_log_trade(account_id: str, trade_data: dict) -> dict:
    """
    Được gọi bởi: POST /api/log-trade
    Frontend: CockpitPatches.js → useTradeLogger() → logTrade() mỗi khi lệnh mở/đóng
    Xử lý: Upsert (tạo mới nếu chưa có, update nếu đã có — khi lệnh đóng)
    """
    db = SessionLocal()
    try:
        td       = trade_data
        trade_id = td.get("id") or f"trade_{int(datetime.utcnow().timestamp() * 1000)}"

        existing = db.query(TradeHistory).filter_by(id=trade_id).first()
        if existing:
            # Update khi đóng lệnh (updateTradeResult từ frontend)
            existing.result          = td.get("result", existing.result)
            existing.actual_rr       = float(td.get("actual_rr", existing.actual_rr))
            existing.profit          = float(td.get("profit", existing.profit))
            existing.deviation_score = float(td.get("deviation_score", existing.deviation_score))
            existing.closed_at       = td.get("closed_at")
            db.commit()
            return {"status": "updated", "id": trade_id}

        record = TradeHistory(
            id              = trade_id,
            account_id      = str(account_id),
            session_id      = td.get("session_id", ""),
            timestamp       = int(td.get("timestamp", datetime.utcnow().timestamp() * 1000)),
            closed_at       = td.get("closed_at"),
            symbol          = td.get("symbol", ""),
            direction       = td.get("direction", "BUY"),
            result          = td.get("result", "PENDING"),
            risk_amount     = float(td.get("risk_amount", 0)),
            actual_rr       = float(td.get("actual_rr", 0)),
            planned_rr      = float(td.get("planned_rr", 0)),
            profit          = float(td.get("profit", 0)),
            hour_of_day     = int(td.get("hour_of_day", 0)),
            day_of_week     = int(td.get("day_of_week", 0)),
            deviation_score = float(td.get("deviation_score", 0)),
        )
        db.add(record)
        db.commit()
        return {"status": "created", "id": trade_id}
    except Exception as e:
        db.rollback()
        return {"status": "error", "detail": str(e)}
    finally:
        db.close()


# ── 2. CLOSE SESSION ─────────────────────────────────────────────────
def api_close_session(account_id: str, session_data: dict) -> dict:
    """
    Được gọi bởi: POST /api/close-session
    Frontend: CockpitPatches.js → useRolloverDetect() → closeSession() khi đến giờ Rollover
    Xử lý: Upsert session — tạo mới hoặc cập nhật nếu session đã tồn tại
    """
    db = SessionLocal()
    try:
        sd         = session_data
        session_id = sd.get("session_id") or f"session_{int(datetime.utcnow().timestamp() * 1000)}"

        existing = db.query(SessionHistory).filter_by(session_id=session_id).first()
        if existing:
            existing.status            = sd.get("status", "COMPLETED")
            existing.closed_at         = sd.get("closed_at")
            existing.closing_balance   = float(sd.get("closing_balance", existing.closing_balance))
            existing.pnl               = float(sd.get("pnl", existing.pnl))
            existing.actual_wr         = float(sd.get("actual_wr", existing.actual_wr))
            existing.actual_rr_avg     = float(sd.get("actual_rr_avg", existing.actual_rr_avg))
            existing.actual_max_dd_hit = float(sd.get("actual_max_dd_hit", existing.actual_max_dd_hit))
            existing.trades_count      = int(sd.get("trades_count", existing.trades_count))
            existing.wins              = int(sd.get("wins", existing.wins))
            existing.losses            = int(sd.get("losses", existing.losses))
            existing.compliance_score  = int(sd.get("compliance_score", existing.compliance_score))
            existing.violations        = json.dumps(sd.get("violations", []))
            db.commit()
            return {"status": "updated", "session_id": session_id}

        record = SessionHistory(
            session_id        = session_id,
            account_id        = str(account_id),
            date              = sd.get("date", datetime.now().strftime("%Y-%m-%d")),
            opened_at         = sd.get("opened_at"),
            closed_at         = sd.get("closed_at"),
            opening_balance   = float(sd.get("opening_balance", 0)),
            closing_balance   = float(sd.get("closing_balance", 0)),
            pnl               = float(sd.get("pnl", 0)),
            actual_wr         = float(sd.get("actual_wr", 0)),
            actual_rr_avg     = float(sd.get("actual_rr_avg", 0)),
            actual_max_dd_hit = float(sd.get("actual_max_dd_hit", 0)),
            trades_count      = int(sd.get("trades_count", 0)),
            wins              = int(sd.get("wins", 0)),
            losses            = int(sd.get("losses", 0)),
            compliance_score  = int(sd.get("compliance_score", 100)),
            violations        = json.dumps(sd.get("violations", [])),
            contract_json     = json.dumps(sd.get("contract", {})),
            status            = sd.get("status", "COMPLETED"),
        )
        db.add(record)
        db.commit()
        return {"status": "created", "session_id": session_id}
    except Exception as e:
        db.rollback()
        return {"status": "error", "detail": str(e)}
    finally:
        db.close()


# ── 3. LOG AUDIT EVENT ───────────────────────────────────────────────
def api_log_audit(account_id: str, action: str, message: str,
                  severity: str = "INFO", extra: dict = None) -> dict:
    """
    Được gọi bởi: POST /api/log-audit
    Frontend: CockpitPatches.js → writeAuditLog() mỗi khi có event quan trọng
    Nếu action = COMPLIANCE_VIOL và severity HIGH/CRITICAL → gửi Telegram ngay
    """
    db = SessionLocal()
    try:
        now_ms = int(datetime.utcnow().timestamp() * 1000)
        record = AuditLog(
            account_id = str(account_id),
            timestamp  = now_ms,
            date_str   = datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            action     = action,
            message    = message,
            severity   = severity,
            extra_json = json.dumps(extra or {}),
        )
        db.add(record)
        db.commit()

        # Gửi Telegram nếu là vi phạm nghiêm trọng
        if action == "COMPLIANCE_VIOL" and severity in ("HIGH", "CRITICAL"):
            units_config = get_all_units()
            unit         = units_config.get(str(account_id), {})
            chat_id      = unit.get("telegram_config", {}).get("chat_id")
            trader_name  = unit.get("alias", f"Trader {account_id}")
            if chat_id:
                violations = extra.get("violations", [{"type": action, "severity": severity, "detail": message}])
                fire_async(send_compliance_alert(
                    chat_id=chat_id, trader_name=trader_name, violations=violations
                ))

        return {"status": "ok"}
    except Exception as e:
        db.rollback()
        return {"status": "error", "detail": str(e)}
    finally:
        db.close()


# ── 4. GET TRADE HISTORY ─────────────────────────────────────────────
def api_get_trade_history(account_id: str, limit: int = 500) -> dict:
    """
    Được gọi bởi: GET /api/trade-history/{account_id}?limit=500
    Frontend: Khi user login lần đầu → sync về localStorage để AI Agent có data
    """
    db = SessionLocal()
    try:
        records = (
            db.query(TradeHistory)
            .filter_by(account_id=str(account_id))
            .order_by(TradeHistory.timestamp.desc())
            .limit(limit)
            .all()
        )
        trades = [
            {
                "id":              r.id,
                "session_id":      r.session_id,
                "timestamp":       r.timestamp,
                "closed_at":       r.closed_at,
                "symbol":          r.symbol,
                "direction":       r.direction,
                "result":          r.result,
                "risk_amount":     r.risk_amount,
                "actual_rr":       r.actual_rr,
                "planned_rr":      r.planned_rr,
                "profit":          r.profit,
                "hour_of_day":     r.hour_of_day,
                "day_of_week":     r.day_of_week,
                "deviation_score": r.deviation_score,
            }
            for r in records
        ]
        # Đảo thứ tự: cũ → mới để frontend push thẳng vào localStorage
        return {"status": "ok", "account_id": account_id, "trades": list(reversed(trades))}
    except Exception as e:
        return {"status": "error", "detail": str(e), "trades": []}
    finally:
        db.close()


# ── 5. GET SESSION HISTORY ───────────────────────────────────────────
def api_get_session_history(account_id: str, limit: int = 90) -> dict:
    """
    Được gọi bởi: GET /api/session-history/{account_id}?limit=90
    Frontend: Khi user login lần đầu → sync về localStorage
    """
    db = SessionLocal()
    try:
        records = (
            db.query(SessionHistory)
            .filter_by(account_id=str(account_id))
            .order_by(SessionHistory.opened_at.desc())
            .limit(limit)
            .all()
        )
        sessions = [
            {
                "session_id":        r.session_id,
                "date":              r.date,
                "opened_at":         r.opened_at,
                "closed_at":         r.closed_at,
                "opening_balance":   r.opening_balance,
                "closing_balance":   r.closing_balance,
                "pnl":               r.pnl,
                "actual_wr":         r.actual_wr,
                "actual_rr_avg":     r.actual_rr_avg,
                "actual_max_dd_hit": r.actual_max_dd_hit,
                "trades_count":      r.trades_count,
                "wins":              r.wins,
                "losses":            r.losses,
                "compliance_score":  r.compliance_score,
                "violations":        json.loads(r.violations or "[]"),
                "contract":          json.loads(r.contract_json or "{}"),
                "status":            r.status,
            }
            for r in records
        ]
        return {"status": "ok", "account_id": account_id, "sessions": list(reversed(sessions))}
    except Exception as e:
        return {"status": "error", "detail": str(e), "sessions": []}
    finally:
        db.close()


# ── 6. SEND TELEGRAM DEBRIEF ─────────────────────────────────────────
async def api_send_telegram(account_id: str, chat_id: str, message: str) -> dict:
    """
    Được gọi bởi: POST /api/send-telegram
    Frontend: CockpitPatches.js → useRolloverDetect() → fetch() sau closeSession()
    Gọi send_session_debrief từ telegram_engine
    """
    try:
        success = await send_session_debrief(chat_id=chat_id, debrief_text=message)
        return {"status": "ok" if success else "failed"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


# ── 7. SYNC HISTORY (Trades + Sessions trong 1 lần gọi) ──────────────
def api_sync_history(account_id: str) -> dict:
    """
    Được gọi bởi: GET /api/sync-history/{account_id}
    Frontend: Gọi khi user login lần đầu hoặc khi cần restore AI memory từ server.
    Trả về cả trades + sessions trong 1 request duy nhất để giảm latency.
    """
    trades   = api_get_trade_history(account_id, limit=500)
    sessions = api_get_session_history(account_id, limit=90)
    return {
        "status":     "ok",
        "account_id": account_id,
        "trades":     trades.get("trades", []),
        "sessions":   sessions.get("sessions", []),
        "meta": {
            "trade_count":   len(trades.get("trades", [])),
            "session_count": len(sessions.get("sessions", [])),
            "synced_at":     datetime.now().isoformat()
        }
    }