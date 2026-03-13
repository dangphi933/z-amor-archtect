"""
ml/labeler.py
=============
Auto-labeler: JOIN radar_scans + trade_history trong ±2h window
→ INSERT vào labeled_scans.

Chạy:
  - Tự động: từ ml/trainer.py trước mỗi lần retrain
  - Manual:  python -m ml.labeler
  - API:     POST /ml/label (từ ml/router.py)

Labels:
  PROFITABLE_TREND  — PnL > 0 và RR >= 1.0
  FALSE_SIGNAL      — PnL < 0 (signal sai)
  RANGE_BOUND       — PnL ~ 0 hoặc RR < 0.5 (entry đúng hướng nhưng không có trend)

JOIN window: ±2 giờ giữa radar_scan.created_at và trade_history.opened_at
"""

from sqlalchemy import text
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("zarmor.ml.labeler")


# ── Label thresholds ──────────────────────────────────────────────────────────
MIN_RR_TREND   = 1.0    # PnL > 0 và RR >= này → PROFITABLE_TREND
MIN_RR_RANGE   = 0.0    # PnL ~ 0 → RANGE_BOUND
JOIN_WINDOW_H  = 2      # ±2 giờ


def _classify_label(pnl: float, rr: float) -> tuple[str, float]:
    """
    Trả về (label, confidence).
    pnl: realized PnL của trade
    rr:  risk-reward ratio thực tế (|pnl| / risk)
    """
    if pnl > 0 and rr >= MIN_RR_TREND:
        conf = min(1.0, 0.6 + rr * 0.1)
        return "PROFITABLE_TREND", round(conf, 3)

    if pnl < 0:
        conf = min(1.0, 0.5 + abs(pnl) / 100 * 0.05)
        return "FALSE_SIGNAL", round(conf, 3)

    # PnL ~ 0 hoặc RR thấp
    return "RANGE_BOUND", 0.55


def run_labeler(db, limit: int = 1000) -> dict:
    """
    Main entry point.
    JOIN radar_scans ↔ trade_history trong ±2h → INSERT labeled_scans.
    Bỏ qua các cặp đã được label (ON CONFLICT DO NOTHING).

    Trả về: {labeled: int, skipped: int, errors: int}
    """
    labeled = skipped = errors = 0

    try:
        # Tìm tất cả trades có PnL đã xác định
        trades = db.execute(text("""
            SELECT
                th.id           AS trade_id,
                th.account_id,
                th.symbol,
                th.opened_at,
                th.pnl,
                th.rr_ratio
            FROM trade_history th
            WHERE th.pnl IS NOT NULL
              AND th.opened_at IS NOT NULL
            ORDER BY th.opened_at DESC
            LIMIT :limit
        """), {"limit": limit}).fetchall()

        logger.info(f"[LABELER] Found {len(trades)} trades to label")

        for trade in trades:
            try:
                trade_id = trade["trade_id"]
                symbol   = trade["symbol"]
                opened   = trade["opened_at"]
                pnl      = float(trade["pnl"] or 0)
                rr       = float(trade["rr_ratio"] or 0)

                # Normalize symbol → asset
                asset = _symbol_to_asset(symbol)
                if not asset:
                    skipped += 1
                    continue

                # Tìm scan gần nhất trong ±2h trước khi trade open
                scan = db.execute(text("""
                    SELECT
                        scan_id, score, regime,
                        breakdown->>'trend_strength'     AS trend_strength,
                        breakdown->>'volatility_quality' AS vol_quality,
                        breakdown->>'session_bias'       AS session_bias,
                        breakdown->>'market_structure'   AS mkt_structure,
                        breakdown->>'adx_live'           AS adx_live,
                        breakdown->>'rsi_live'           AS rsi_live,
                        breakdown->>'atr_pct_live'       AS atr_pct_live,
                        utc_hour, utc_dow
                    FROM radar_scans
                    WHERE asset = :asset
                      AND created_at BETWEEN :t_start AND :t_end
                    ORDER BY ABS(EXTRACT(EPOCH FROM (created_at - :opened_at)))
                    LIMIT 1
                """), {
                    "asset":     asset,
                    "t_start":   opened,
                    "t_end":     opened,
                    "opened_at": opened,
                }).fetchone()

                # Dùng parameterized interval
                scan = db.execute(text("""
                    SELECT
                        scan_id, score, regime,
                        (breakdown->>'trend_strength')::numeric     AS trend_strength,
                        (breakdown->>'volatility_quality')::numeric AS vol_quality,
                        (breakdown->>'session_bias')::numeric       AS session_bias,
                        (breakdown->>'market_structure')::numeric   AS mkt_structure,
                        (breakdown->>'adx_live')::numeric           AS adx_live,
                        (breakdown->>'rsi_live')::numeric           AS rsi_live,
                        (breakdown->>'atr_pct_live')::numeric       AS atr_pct_live,
                        utc_hour, utc_dow
                    FROM radar_scans
                    WHERE asset = :asset
                      AND created_at BETWEEN
                            :opened_at - INTERVAL '2 hours'
                        AND :opened_at + INTERVAL '2 hours'
                    ORDER BY ABS(EXTRACT(EPOCH FROM (created_at - :opened_at)))
                    LIMIT 1
                """), {"asset": asset, "opened_at": opened}).fetchone()

                if not scan:
                    skipped += 1
                    continue

                label, confidence = _classify_label(pnl, rr)

                db.execute(text("""
                    INSERT INTO labeled_scans
                      (scan_id, trade_id, asset, timeframe,
                       score, regime,
                       trend_strength, vol_quality, session_bias, mkt_structure,
                       adx_live, rsi_live, atr_pct_live,
                       utc_hour, utc_dow,
                       label, label_confidence,
                       trade_pnl, trade_rr,
                       labeled_at, label_method)
                    VALUES
                      (:scan_id, :trade_id, :asset, 'H1',
                       :score, :regime,
                       :trend, :vol, :session, :mkt,
                       :adx, :rsi, :atr,
                       :hour, :dow,
                       :label, :conf,
                       :pnl, :rr,
                       NOW(), 'auto')
                    ON CONFLICT (scan_id, trade_id) DO NOTHING
                """), {
                    "scan_id":  scan["scan_id"],
                    "trade_id": trade_id,
                    "asset":    asset,
                    "score":    scan["score"],
                    "regime":   scan["regime"],
                    "trend":    scan["trend_strength"],
                    "vol":      scan["vol_quality"],
                    "session":  scan["session_bias"],
                    "mkt":      scan["mkt_structure"],
                    "adx":      scan["adx_live"],
                    "rsi":      scan["rsi_live"],
                    "atr":      scan["atr_pct_live"],
                    "hour":     scan["utc_hour"],
                    "dow":      scan["utc_dow"],
                    "label":    label,
                    "conf":     confidence,
                    "pnl":      pnl,
                    "rr":       rr,
                })
                labeled += 1

            except Exception as row_err:
                logger.warning(f"[LABELER] Row error trade_id={trade.get('trade_id')}: {row_err}")
                errors += 1

        db.commit()
        logger.info(f"[LABELER] Done: labeled={labeled} skipped={skipped} errors={errors}")

    except Exception as e:
        logger.error(f"[LABELER] Fatal error: {e}")
        db.rollback()
        errors += 1

    return {"labeled": labeled, "skipped": skipped, "errors": errors}


def get_training_data(db, min_samples: int = 100) -> Optional[dict]:
    """
    Lấy tất cả labeled_scans để feed vào ml/trainer.py.
    Trả về dict với features + labels, hoặc None nếu không đủ data.
    """
    try:
        rows = db.execute(text("""
            SELECT
                score, regime,
                trend_strength, vol_quality, session_bias, mkt_structure,
                adx_live, rsi_live, atr_pct_live,
                utc_hour, utc_dow,
                label
            FROM labeled_scans
            WHERE label IS NOT NULL
              AND score IS NOT NULL
            ORDER BY labeled_at DESC
        """)).fetchall()

        if len(rows) < min_samples:
            logger.warning(f"[LABELER] Insufficient data: {len(rows)} < {min_samples}")
            return None

        features = []
        labels   = []
        for r in rows:
            features.append({
                "score":           float(r["score"] or 0),
                "trend_strength":  float(r["trend_strength"] or 0),
                "vol_quality":     float(r["vol_quality"] or 0),
                "session_bias":    float(r["session_bias"] or 0),
                "mkt_structure":   float(r["mkt_structure"] or 0),
                "adx_live":        float(r["adx_live"] or 0),
                "rsi_live":        float(r["rsi_live"] or 50),
                "atr_pct_live":    float(r["atr_pct_live"] or 0),
                "utc_hour":        int(r["utc_hour"] or 0),
                "utc_dow":         int(r["utc_dow"] or 0),
            })
            labels.append(r["label"])

        label_counts = {l: labels.count(l) for l in set(labels)}
        logger.info(f"[LABELER] Training data: {len(rows)} samples | {label_counts}")

        return {
            "features":      features,
            "labels":        labels,
            "sample_count":  len(rows),
            "label_counts":  label_counts,
        }

    except Exception as e:
        logger.error(f"[LABELER] get_training_data error: {e}")
        return None


# ── Helpers ───────────────────────────────────────────────────────────────────

_SYMBOL_MAP = {
    # GOLD
    "XAUUSD": "GOLD", "XAUUSDm": "GOLD", "GOLD": "GOLD", "GOLDm": "GOLD",
    # EURUSD
    "EURUSD": "EURUSD", "EURUSDm": "EURUSD",
    # BTC
    "BTCUSD": "BTC", "BTCUSDm": "BTC", "BTCUSDT": "BTC",
    # NASDAQ
    "NAS100": "NASDAQ", "NAS100m": "NASDAQ", "NASDAQ": "NASDAQ", "USTEC": "NASDAQ",
}

def _symbol_to_asset(symbol: str) -> Optional[str]:
    if not symbol:
        return None
    s = symbol.upper().strip()
    return _SYMBOL_MAP.get(s) or _SYMBOL_MAP.get(s.rstrip("M").rstrip("_"))


if __name__ == "__main__":
    """Chạy manual: python -m ml.labeler"""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from database import SessionLocal
    db = SessionLocal()
    try:
        result = run_labeler(db, limit=5000)
        print(f"Labeling complete: {result}")
    finally:
        db.close()


# ── Functions required by trainer.py ──────────────────────────────────────────

def label_unlabeled_scans(db, limit: int = 500) -> dict:
    """
    Gán outcome_label cho radar_scans chưa được label bằng heuristic.
    Dùng khi chưa có đủ trade_history để JOIN thật.
    Trainer.py gọi function này trước mỗi lần retrain.
    """
    labeled = 0
    skipped = 0
    try:
        rows = db.execute(text("""
            SELECT scan_id, asset, timeframe, score, regime, allow_trade, position_pct
            FROM radar_scans
            WHERE outcome_label IS NULL
            ORDER BY created_at DESC
            LIMIT :limit
        """), {"limit": limit}).fetchall()

        for row in rows:
            try:
                score  = float(row["score"] or 0)
                allow  = bool(row["allow_trade"])
                if not allow or score < 20:
                    label, conf = "AVOID", 0.85
                elif score >= 70:
                    label, conf = "STRONG_ENTRY", min(0.95, score / 100.0)
                elif score >= 50:
                    label, conf = "ENTRY", 0.70
                elif score >= 30:
                    label, conf = "WEAK_ENTRY", 0.55
                else:
                    label, conf = "AVOID", 0.65

                db.execute(text("""
                    UPDATE radar_scans
                    SET outcome_label = :label, outcome_confidence = :conf
                    WHERE scan_id = :sid
                """), {"label": label, "conf": conf, "sid": row["scan_id"]})
                labeled += 1
            except Exception:
                skipped += 1

        db.commit()
    except Exception as e:
        db.rollback()
        return {"labeled": 0, "skipped": 0, "error": str(e)}
    return {"labeled": labeled, "skipped": skipped}


def get_training_stats(db) -> dict:
    """
    Thống kê training data (labeled_scans + radar_scans).
    Trainer.py dùng để quyết định có đủ data để retrain không.
    """
    try:
        # Đếm từ labeled_scans (production labels từ trade_history JOIN)
        total_ls = db.execute(text(
            "SELECT COUNT(*) FROM labeled_scans WHERE label IS NOT NULL"
        )).scalar() or 0

        by_label = db.execute(text("""
            SELECT label, COUNT(*) as cnt
            FROM labeled_scans
            WHERE label IS NOT NULL
            GROUP BY label
        """)).fetchall()

        # Đếm radar_scans có heuristic outcome_label
        total_rs = db.execute(text(
            "SELECT COUNT(*) FROM radar_scans WHERE outcome_label IS NOT NULL"
        )).scalar() or 0

        unlabeled_rs = db.execute(text(
            "SELECT COUNT(*) FROM radar_scans WHERE outcome_label IS NULL"
        )).scalar() or 0

        return {
            "labeled_scans_count":  int(total_ls),
            "radar_heuristic_count": int(total_rs),
            "total_unlabeled":      int(unlabeled_rs),
            "by_label":             {r["label"]: int(r["cnt"]) for r in by_label},
            "ready_for_training":   (total_ls + total_rs) >= 50,
        }
    except Exception as e:
        return {
            "labeled_scans_count": 0, "radar_heuristic_count": 0,
            "total_unlabeled": 0, "by_label": {},
            "error": str(e), "ready_for_training": False
        }
