import os
import json
import threading
from datetime import datetime
from database import SessionLocal, TradeHistory, SessionHistory
from api.config_manager import get_yaml_configs

# BUG I FIX: Lock để tránh race condition khi nhiều request ghi đồng thời
_behavior_lock = threading.Lock()

# ==========================================
# 1. QUẢN LÝ DỮ LIỆU ĐA NGƯỜI DÙNG — GIỮ NGUYÊN
# ==========================================
def load_guard_rules():
    configs = get_yaml_configs()
    return configs.get("neural", {})

def load_behavioral_profile(account_id):
    path = 'Z-Armor_behavior.json'
    with _behavior_lock:
        data = {}
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                try: data = json.load(f)
                except: data = {}

    acc_id_str = str(account_id)
    if acc_id_str not in data:
        data[acc_id_str] = {
            "trade_history_scores": [],
            "trust_status": "NORMAL",
            "probation_until": None,
            "last_updated": str(datetime.now().date())
        }
    return data[acc_id_str]

def save_behavioral_profile(account_id, profile_data):
    path = 'Z-Armor_behavior.json'
    with _behavior_lock:
        data = {}
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                try: data = json.load(f)
                except: data = {}
        data[str(account_id)] = profile_data
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)

# ==========================================
# 2. ĐỘNG CƠ CHẤM ĐIỂM REGIME FIT — GIỮ NGUYÊN
# ==========================================
def calculate_regime_fit_score(trade, regime, physics_data, baselines):
    score = 100.0
    mismatch_msg = ""
    tax_rate = physics_data.get("entropy_tax_rate", 0.0)

    if tax_rate > 0.0:
        score -= (tax_rate * 40.0)

    tp         = trade.get("tp", 0.0)
    open_price = trade.get("open_price", 0.0)

    if regime in ["TURBULENT FORCE", "CRITICAL BREACH"]:
        if tp == 0.0 or abs(tp - open_price) > 0.005:
            score -= 40.0
            mismatch_msg = "Kỳ vọng quá xa so với bối cảnh Hỗn loạn."
    elif regime == "STRUCTURAL EROSION":
        if tp == 0.0:
            score -= 20.0
            mismatch_msg = "Thiếu mục tiêu chốt lời (TP) trong bối cảnh rò rỉ năng lượng."

    if "BREACH" in regime:
        score = 0.0
        mismatch_msg = "Hành vi tự hủy: Lệnh đi ngược lại quy luật sinh tồn."

    return max(0.0, min(100.0, score)), mismatch_msg

# ==========================================
# 3. TỐI ƯU HÓA HÀNH VI DÀI HẠN — GIỮ NGUYÊN
# ==========================================
def update_behavioral_trust(account_id, current_scores, rules):
    if not current_scores:
        return "NORMAL", []

    profile = load_behavioral_profile(account_id)
    avg_current_score = sum(current_scores) / len(current_scores)

    profile["trade_history_scores"].append(avg_current_score)
    if len(profile["trade_history_scores"]) > 50:
        profile["trade_history_scores"].pop(0)

    recent_history  = profile["trade_history_scores"][-10:]
    moving_avg_score = sum(recent_history) / len(recent_history)

    status_msgs = []
    new_status  = "NORMAL"

    if moving_avg_score >= 80.0 and len(recent_history) >= 10:
        new_status = "TRUSTED_OPERATOR"
        status_msgs.append("🏆 Đã xác thực Kỷ luật Dài hạn.")
    elif moving_avg_score <= 30.0 and len(recent_history) >= 5:
        new_status = "PROBATION_LOCK"
        status_msgs.append("🚨 Vi phạm Kỷ luật Mãn tính. Kích hoạt PROBATION_LOCK.")

    profile["trust_status"] = new_status
    save_behavioral_profile(account_id, profile)
    return new_status, status_msgs

# ==========================================
# 4. TRẠM CHẨN ĐOÁN TỔNG HỢP — GIỮ NGUYÊN
# ==========================================
def diagnose_context_mismatch(account_id, regime, current_trades, physics_data, current_daily_profit_pct):
    rules    = load_guard_rules()
    baselines = rules.get("regime_fit_baselines", {})

    findings          = []
    is_mismatch       = False
    action_directive  = "MAINTAIN"
    target_pct        = 3.0

    if current_daily_profit_pct >= target_pct:
        return {
            "is_mismatch": True, "is_positive_lock": True,
            "verdict": [f"🌟 Đạt kỳ vọng {target_pct}%. Tự động Niêm phong."],
            "allowed_action": "LOCK_TERMINAL", "trust_status": "NORMAL"
        }

    trade_scores = []
    for trade in current_trades:
        score, msg = calculate_regime_fit_score(trade, regime, physics_data, baselines)
        trade_scores.append(score)
        trade["fit_score"] = round(score, 1)
        if score < 50.0:
            is_mismatch = True
            if msg not in findings:
                findings.append(f"⚠️ [Lệnh #{trade.get('ticket')}] {msg} (Điểm: {score}%)")

    trust_status, trust_msgs = update_behavioral_trust(account_id, trade_scores, rules)
    if trust_msgs:
        findings.extend(trust_msgs)

    if "BREACH" in regime or "TURBULENT" in regime or trust_status == "PROBATION_LOCK":
        action_directive = "RESTRICT"

    return {
        "is_mismatch": is_mismatch, "is_positive_lock": False,
        "verdict": findings, "allowed_action": action_directive,
        "trust_status": trust_status
    }


# ==========================================
# 5. MỚI: DNA SCORE — TÍNH TỪ DB SERVER-SIDE
# Dùng làm backup khi localStorage bị xóa
# Gọi từ: GET /api/ai-analysis/{account_id}
# ==========================================
def calculate_dna_score(account_id: str) -> dict:
    """
    Tính Strategy DNA Score từ dữ liệu session_history và trade_history trong DB.
    Kết quả khớp với logic calcDNA() trong MacroModal.js / AiGuardCenter_NEW.js.
    """
    db = SessionLocal()
    try:
        sessions = (
            db.query(SessionHistory)
            .filter_by(account_id=str(account_id))
            .order_by(SessionHistory.opened_at.desc())
            .limit(30)
            .all()
        )
        trades = (
            db.query(TradeHistory)
            .filter_by(account_id=str(account_id))
            .order_by(TradeHistory.timestamp.desc())
            .limit(500)
            .all()
        )

        if not sessions:
            return {"available": False, "reason": "Chưa có dữ liệu session"}

        # ── Consistency: độ lệch chuẩn R:R (thấp = nhất quán) ──────
        rr_list = [t.actual_rr for t in trades if t.actual_rr > 0]
        if len(rr_list) > 1:
            avg_rr = sum(rr_list) / len(rr_list)
            variance = sum((r - avg_rr) ** 2 for r in rr_list) / len(rr_list)
            std_rr = variance ** 0.5
            consistency = max(0, min(100, 100 - std_rr * 20))
        else:
            consistency = 60.0

        # ── Discipline: trung bình compliance score ──────────────────
        discipline = sum(s.compliance_score for s in sessions) / len(sessions)

        # ── Risk Control: % phiên không vượt Max DD ──────────────────
        # Lấy max_dd từ contract_json của từng session
        safe_sessions = 0
        for s in sessions:
            contract = json.loads(s.contract_json or "{}")
            max_dd   = float(contract.get("max_dd", 10))
            if (s.actual_max_dd_hit or 0) < max_dd:
                safe_sessions += 1
        risk_control = (safe_sessions / len(sessions)) * 100

        # ── Edge Strength: trung bình Kelly factor ───────────────────
        kelly_list = []
        for s in sessions:
            wr = (s.actual_wr or 0) / 100
            rr = s.actual_rr_avg or 1.5
            if wr > 0 and rr > 0:
                kelly_list.append(wr - (1 - wr) / rr)
        avg_kelly     = sum(kelly_list) / len(kelly_list) if kelly_list else 0
        edge_strength = max(0, min(100, avg_kelly * 200))

        # ── Recovery: khả năng lấy lại sau phiên lỗ ─────────────────
        recovery = 75.0
        for i in range(1, len(sessions)):
            prev = sessions[i]   # truy vấn desc nên index i = phiên cũ hơn
            curr = sessions[i-1]
            if prev.pnl < 0:
                recovery += 5.0 if curr.pnl > 0 else -5.0
        recovery = max(0, min(100, recovery))

        # ── Timing: phương sai WR theo giờ ──────────────────────────
        hour_map = {}
        for t in trades:
            h = t.hour_of_day or 0
            if h not in hour_map:
                hour_map[h] = {"wins": 0, "total": 0}
            hour_map[h]["total"] += 1
            if t.result == "WIN":
                hour_map[h]["wins"] += 1
        wr_by_hour = [v["wins"] / v["total"] for v in hour_map.values() if v["total"] > 0]
        if len(wr_by_hour) > 1:
            timing = min(100, (max(wr_by_hour) - min(wr_by_hour)) * 100 + 50)
        else:
            timing = 60.0

        overall = round((consistency + discipline + risk_control + edge_strength + recovery + timing) / 6)

        # Win stats
        wins_total   = sum(1 for t in trades if t.result == "WIN")
        actual_wr    = (wins_total / len(trades) * 100) if trades else 0
        avg_rr_final = sum(rr_list) / len(rr_list) if rr_list else 0

        return {
            "available":      True,
            "overall":        overall,
            "consistency":    round(consistency, 1),
            "discipline":     round(discipline, 1),
            "risk_control":   round(risk_control, 1),
            "edge_strength":  round(edge_strength, 1),
            "recovery":       round(recovery, 1),
            "timing":         round(timing, 1),
            "actual_wr":      round(actual_wr, 1),
            "avg_rr":         round(avg_rr_final, 2),
            "session_count":  len(sessions),
            "trade_count":    len(trades),
        }
    except Exception as e:
        return {"available": False, "reason": str(e)}
    finally:
        db.close()


# ==========================================
# 6. MỚI: BAD HABITS DETECTION
# Gọi từ: GET /api/ai-analysis/{account_id}
# ==========================================
def detect_bad_habits(account_id: str) -> list:
    """
    Phát hiện 3 bad habits từ trade_history.
    Khớp với logic phát hiện trong AiGuardCenter_NEW.js.
    """
    db = SessionLocal()
    try:
        trades = (
            db.query(TradeHistory)
            .filter_by(account_id=str(account_id))
            .order_by(TradeHistory.timestamp.asc())
            .limit(500)
            .all()
        )
        if not trades:
            return []

        habits = []
        closed = [t for t in trades if t.result in ("WIN", "LOSS", "BE")]

        # ── 1. REVENGE TRADING: 2+ lỗ liên tiếp → risk tăng >130% ──
        avg_risk = sum(t.risk_amount for t in closed) / len(closed) if closed else 0
        revenge_count = 0
        consecutive_losses = 0
        for t in closed:
            if t.result == "LOSS":
                consecutive_losses += 1
            else:
                if consecutive_losses >= 2:
                    # Kiểm tra lệnh kế tiếp có risk > 130% không
                    idx = closed.index(t)
                    if idx > 0 and closed[idx].risk_amount > avg_risk * 1.3:
                        revenge_count += 1
                consecutive_losses = 0

        if revenge_count >= 2:
            habits.append({
                "type":        "REVENGE_TRADING",
                "label":       "Giao dịch trả thù",
                "description": f"Phát hiện {revenge_count} lần tăng risk sau ≥2 lỗ liên tiếp.",
                "severity":    "HIGH",
                "count":       revenge_count
            })

        # ── 2. OVERTRADING: TB >7 lệnh/session ───────────────────────
        sessions = (
            db.query(SessionHistory)
            .filter_by(account_id=str(account_id))
            .order_by(SessionHistory.opened_at.desc())
            .limit(30)
            .all()
        )
        if sessions:
            avg_trades_per_session = sum(s.trades_count for s in sessions) / len(sessions)
            if avg_trades_per_session > 7:
                habits.append({
                    "type":        "OVERTRADING",
                    "label":       "Giao dịch quá nhiều",
                    "description": f"Trung bình {avg_trades_per_session:.1f} lệnh/phiên (ngưỡng an toàn ≤7).",
                    "severity":    "MEDIUM",
                    "count":       round(avg_trades_per_session, 1)
                })

        # ── 3. MOVING TP EARLY: actual_rr < planned_rr ×0.7 ─────────
        tp_moved = [
            t for t in closed
            if t.result == "WIN"
            and t.planned_rr > 0
            and t.actual_rr < t.planned_rr * 0.7
        ]
        tp_moved_pct = len(tp_moved) / len(closed) * 100 if closed else 0
        if tp_moved_pct > 30:
            habits.append({
                "type":        "MOVING_TP_EARLY",
                "label":       "Chốt lời quá sớm",
                "description": f"{tp_moved_pct:.0f}% số lệnh thắng có R:R thực tế thấp hơn 30% so với kế hoạch.",
                "severity":    "MEDIUM",
                "count":       len(tp_moved)
            })

        return habits
    except Exception as e:
        return [{"type": "ERROR", "label": "Lỗi phân tích", "description": str(e), "severity": "INFO", "count": 0}]
    finally:
        db.close()


# ==========================================
# 7. MỚI: AI RECOMMENDATIONS
# Gọi từ: GET /api/ai-analysis/{account_id}
# ==========================================
def generate_recommendations(account_id: str, dna: dict = None, habits: list = None) -> list:
    """
    Tạo danh sách gợi ý tối ưu dựa trên DNA + Bad Habits.
    Khớp với Directives Panel trong AiGuardCenter_NEW.js.
    """
    if dna is None:
        dna = calculate_dna_score(account_id)
    if habits is None:
        habits = detect_bad_habits(account_id)

    if not dna.get("available"):
        return []

    recs = []

    # WR vượt kế hoạch → nâng Kelly
    # (so sánh với NeuralProfile từ config)
    try:
        from api.config_manager import get_all_units
        unit     = get_all_units().get(str(account_id), {})
        planned_wr = float(unit.get("neural_profile", {}).get("historical_win_rate", 55))
        planned_rr = float(unit.get("neural_profile", {}).get("historical_rr", 2.0))

        if dna.get("actual_wr", 0) > planned_wr * 1.08:
            recs.append({
                "type":        "UPGRADE_KELLY",
                "priority":    "HIGH",
                "title":       "Nâng cấp Kelly Budget",
                "description": f"WR thực tế {dna['actual_wr']}% vượt kế hoạch {planned_wr}%. Có thể tăng budget an toàn.",
                "action":      f"Cân nhắc tăng Daily Budget lên ~${round(planned_rr * planned_wr / 100 * 200, 0)}"
            })

        if dna.get("avg_rr", 0) > 0 and dna["avg_rr"] < planned_rr * 0.8:
            recs.append({
                "type":        "FIX_RR_DRIFT",
                "priority":    "HIGH",
                "title":       "Sửa R:R Drift",
                "description": f"R:R thực tế {dna['avg_rr']} thấp hơn 20% so với kế hoạch {planned_rr}.",
                "action":      "Kiểm tra lại vị trí đặt TP. Không chốt lời sớm hơn mức R:R đã cam kết."
            })
    except Exception:
        pass

    # Giờ tệ nhất từ heatmap
    db = SessionLocal()
    try:
        trades = (
            db.query(TradeHistory)
            .filter_by(account_id=str(account_id))
            .filter(TradeHistory.result.in_(["WIN", "LOSS"]))
            .all()
        )
        hour_map = {}
        for t in trades:
            h = t.hour_of_day or 0
            if h not in hour_map:
                hour_map[h] = {"wins": 0, "total": 0}
            hour_map[h]["total"] += 1
            if t.result == "WIN":
                hour_map[h]["wins"] += 1

        bad_hours = [
            h for h, v in hour_map.items()
            if v["total"] >= 3 and v["wins"] / v["total"] < 0.35
        ]
        if bad_hours:
            recs.append({
                "type":        "AVOID_HOURS",
                "priority":    "MEDIUM",
                "title":       "Tránh giờ nguy hiểm",
                "description": f"WR dưới 35% trong giờ: {', '.join(str(h)+'h' for h in sorted(bad_hours))}.",
                "action":      "Không mở lệnh trong các khung giờ này. Xem Pattern Heatmap để biết chi tiết."
            })
    except Exception:
        pass
    finally:
        db.close()

    # Bad habits → recommendations
    habit_types = [h["type"] for h in (habits or [])]
    if "REVENGE_TRADING" in habit_types:
        recs.append({
            "type":        "STOP_REVENGE",
            "priority":    "CRITICAL",
            "title":       "Dừng ngay giao dịch trả thù",
            "description": "AI phát hiện mẫu tăng risk sau lỗ liên tiếp. Nguy cơ cháy tài khoản cao.",
            "action":      "Sau 2 lỗ liên tiếp → đóng máy, nghỉ tối thiểu 30 phút."
        })
    if "MOVING_TP_EARLY" in habit_types:
        recs.append({
            "type":        "HOLD_YOUR_TP",
            "priority":    "MEDIUM",
            "title":       "Giữ TP đúng kế hoạch",
            "description": "Hơn 30% lệnh thắng bị chốt sớm hơn mục tiêu R:R.",
            "action":      "Đặt TP cố định và không di chuyển sau khi vào lệnh."
        })

    return recs


# ==========================================
# 8. MỚI: MASTER AI ANALYSIS ENDPOINT
# Gọi từ: GET /api/ai-analysis/{account_id}
# Trả về toàn bộ dữ liệu cho AiGuardCenter trong 1 request
# ==========================================
def api_get_ai_analysis(account_id: str) -> dict:
    dna      = calculate_dna_score(account_id)
    habits   = detect_bad_habits(account_id)
    recs     = generate_recommendations(account_id, dna=dna, habits=habits)
    return {
        "status":          "ok",
        "account_id":      account_id,
        "dna_score":       dna,
        "bad_habits":      habits,
        "recommendations": recs,
        "analyzed_at":     datetime.now().isoformat()
    }
