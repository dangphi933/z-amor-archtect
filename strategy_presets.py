# ==============================================================================
# strategy_presets.py — Z-Armor Built-in Strategy Library
# 3 preset chiến lược sẵn có. Trader chọn 1 trong dashboard,
# backend trả về trong heartbeat → EA đọc qua g_profile.
#
# Mỗi preset map 1:1 với StrategyProfile struct trong models.mqh
# ==============================================================================

# ─── 3 Preset Strategies ──────────────────────────────────────────────────────
#
# STRATEGY_ID  PROFILE_NAME          PHONG_CACH
# S1           Gold_Trend_H1         Trend-following XAUUSD H1, RR 1:2, breakout
# S2           FX_Range_H1           Range-trading EURUSD/pairs H1, RR 1:1.5, pullback
# S3           Scalp_Session_M15     Scalping London/NY M15, RR 1:1.2, aggressive
#
# Cấu trúc mỗi preset:
#   profile_name     — tên hiển thị trên panel EA
#   entry_type       — "BREAKOUT_ONLY" | "PULLBACK_ONLY" | "BOTH"
#   min_score_entry  — ngưỡng score tối thiểu để EA vào lệnh
#   session_filter   — bitmask: ASIA=1, LONDON=2, NY=4, WEEKEND=8, ALL=15
#   rr_ratio         — TP/SL ratio
#   max_spread_pct   — max spread tính bằng % ATR
#   trailing_sl      — trailing stop
#   risk_mode        — "CONSERVATIVE" | "NORMAL" | "AGGRESSIVE"
#   symbols_hint     — gợi ý symbols phù hợp (EA vẫn dùng input Symbols của nó)
#   description      — mô tả ngắn cho UI dashboard
# ──────────────────────────────────────────────────────────────────────────────

STRATEGY_PRESETS = {

    "S1": {
        "strategy_id":     "S1",
        "profile_name":    "Gold_Trend_H1",
        "entry_type":      "BREAKOUT_ONLY",
        "min_score_entry": 70,
        "session_filter":  6,          # LONDON(2) | NY(4)
        "rr_ratio":        2.0,
        "max_spread_pct":  0.25,       # XAUUSD spread thường thấp trong giờ London/NY
        "trailing_sl":     True,
        "risk_mode":       "NORMAL",
        "symbols_hint":    ["XAUUSD", "XAUUSDm", "GOLD"],
        "description":     "Trend-following XAUUSD H1. Chỉ vào breakout khi score ≥70, "
                           "chạy London+NY overlap. Trailing SL để bắt sóng dài.",
        "color":           "#F4A261",  # amber — gold
    },

    "S2": {
        "strategy_id":     "S2",
        "profile_name":    "FX_Range_H1",
        "entry_type":      "PULLBACK_ONLY",
        "min_score_entry": 55,
        "session_filter":  6,          # LONDON(2) | NY(4)
        "rr_ratio":        1.5,
        "max_spread_pct":  0.40,
        "trailing_sl":     False,
        "risk_mode":       "CONSERVATIVE",
        "symbols_hint":    ["EURUSD", "GBPUSD", "USDJPY", "EURUSDm", "GBPUSDm"],
        "description":     "Range-trading FX majors H1. Vào pullback về mean, "
                           "RR 1:1.5, risk mode conservative (cap 60%). Phù hợp khi "
                           "thị trường sideways score 55-70.",
        "color":           "#4CC9F0",  # cyan — fx
    },

    "S3": {
        "strategy_id":     "S3",
        "profile_name":    "Scalp_Session_M15",
        "entry_type":      "BOTH",
        "min_score_entry": 65,
        "session_filter":  6,          # LONDON(2) | NY(4) — high liquidity only
        "rr_ratio":        1.2,
        "max_spread_pct":  0.20,       # spread filter chặt hơn vì M15
        "trailing_sl":     False,
        "risk_mode":       "AGGRESSIVE",
        "symbols_hint":    ["EURUSD", "GBPUSD", "XAUUSD", "EURUSDm", "XAUUSDm"],
        "description":     "Scalping M15 trong giờ London/NY. Vào cả breakout và "
                           "pullback, RR 1:1.2, aggressive sizing (up to 125%). "
                           "Cần spread thấp, không trade cuối tuần.",
        "color":           "#06D6A0",  # green — scalp
    },
}


def get_preset(strategy_id: str) -> dict | None:
    """Trả về preset theo ID, None nếu không tìm thấy."""
    return STRATEGY_PRESETS.get(strategy_id)


def get_all_presets() -> list[dict]:
    """Trả về tất cả preset dưới dạng list, kèm strategy_id."""
    return list(STRATEGY_PRESETS.values())


def preset_to_heartbeat_profile(strategy_id: str) -> dict | None:
    """
    Trả về dict sẵn sàng để nhúng vào heartbeat response
    dưới key "strategy_profile". EA's CloudBridge sẽ parse dict này
    thành StrategyProfile struct.

    Loại bỏ các field UI-only (color, description, symbols_hint).
    """
    p = get_preset(strategy_id)
    if not p:
        return None
    return {
        "profile_name":    p["profile_name"],
        "entry_type":      p["entry_type"],
        "min_score_entry": p["min_score_entry"],
        "session_filter":  p["session_filter"],
        "rr_ratio":        p["rr_ratio"],
        "max_spread_pct":  p["max_spread_pct"],
        "trailing_sl":     p["trailing_sl"],
        "risk_mode":       p["risk_mode"],
    }