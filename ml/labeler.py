"""
ml/labeler.py — Phase 3 Auto-Labeling Pipeline
================================================
Tự động gán nhãn cho radar_scans bằng cách join với trade_history.

Logic:
  - Sau mỗi radar scan, nếu có trade nào open trong ±2h:
      trade WON  + scan.score ≥ 60 → label = PROFITABLE_TREND
      trade WON  + scan.score <  60 → label = LUCKY_WIN (loại bỏ khi train)
      trade LOST + scan.score ≥ 60 → label = FALSE_SIGNAL
      no trade                      → label = NO_TRADE (dùng làm neutral)
      no live data in DB            → label = NULL (bỏ qua)

  - Sau khi label xong → ghi vào bảng labeled_scans
  - labeled_scans là training data cho XGBoost classifier

Schema labeled_scans:
  scan_id, asset, timeframe, utc_hour, utc_dow,
  trend_strength, volatility_quality, session_bias, market_structure,
  adx_live, rsi_live, atr_pct_live,          ← live OHLCV features (nếu có)
  score, regime, confidence,
  label,                                      ← TARGET: PROFITABLE_TREND / FALSE_SIGNAL / RANGE_BOUND
  label_confidence,                           ← 0.0–1.0 (dựa trên strength của outcome)
  labeled_at
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import text

from database import SessionLocal

logger = logging.getLogger("zarmor.ml.labeler")

# Cửa sổ thời gian: trade phải mở trong vòng bao lâu sau khi scan
TRADE_WINDOW_HOURS = 2

# Score threshold: scan dưới mức này = bearish/unfavorable
SCORE_HIGH_THRESHOLD = 65
SCORE_LOW_THRESHOLD  = 40


def label_unlabeled_scans(limit: int = 500) -> dict:
    """
    Tìm các radar_scans chưa được label → gán nhãn → ghi vào labeled_scans.
    Chạy trong background scheduler (weekly/daily).
    Returns: {"labeled": int, "skipped": int, "errors": int}
    """
    db = SessionLocal()
    stats = {"labeled": 0, "skipped": 0, "errors": 0}

    try:
        # Lấy scans chưa label (không có trong labeled_scans)
        rows = db.execute(text("""
            SELECT rs.scan_id, rs.asset, rs.timeframe,
                   rs.utc_hour, rs.utc_dow, rs.score, rs.regime,
                   rs.confidence, rs.breakdown, rs.created_at, rs.user_email
            FROM radar_scans rs
            LEFT JOIN labeled_scans ls ON rs.scan_id = ls.scan_id
            WHERE ls.scan_id IS NULL
              AND rs.created_at < NOW() - INTERVAL '3 hours'  -- đủ thời gian để trade có outcome
            ORDER BY rs.created_at DESC
            LIMIT :limit
        """), {"limit": limit}).mappings().fetchall()

        logger.info(f"[LABELER] Found {len(rows)} unlabeled scans")

        for row in rows:
            try:
                label_info = _label_scan(db, row)
                if label_info is None:
                    stats["skipped"] += 1
                    continue

                _save_label(db, row, label_info)
                stats["labeled"] += 1

            except Exception as e:
                logger.error(f"[LABELER] Error labeling {row['scan_id']}: {e}")
                stats["errors"] += 1

        db.commit()

    except Exception as e:
        logger.error(f"[LABELER] Pipeline error: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

    logger.info(f"[LABELER] Done: labeled={stats['labeled']} skipped={stats['skipped']} errors={stats['errors']}")
    return stats


def _label_scan(db, row) -> Optional[dict]:
    """
    Tìm trade nào gần với scan này và gán nhãn.
    Returns None nếu không đủ data để label.
    """
    scan_time = row["created_at"]
    if scan_time is None:
        return None

    asset      = row["asset"]
    # Map asset → MT5 symbol patterns
    symbol_map = {
        "GOLD":   ["XAUUSD", "GOLD", "XAU"],
        "EURUSD": ["EURUSD", "EUR/USD"],
        "BTC":    ["BTCUSD", "BTC", "BTCUSDT"],
        "NASDAQ": ["NAS100", "NASDAQ", "US100", "QQQ"],
    }
    symbols = symbol_map.get(asset, [asset])

    window_start = scan_time
    window_end   = scan_time + timedelta(hours=TRADE_WINDOW_HOURS)

    # Tìm trades opened trong cửa sổ thời gian, cùng symbol
    symbol_conditions = " OR ".join([f"UPPER(t.symbol) LIKE '%{s}%'" for s in symbols])

    trades = db.execute(text(f"""
        SELECT t.pnl, t.actual_rr, t.rr_ratio, t.symbol,
               t.opened_at, t.closed_at
        FROM trade_history t
        WHERE t.opened_at BETWEEN :start AND :end
          AND ({symbol_conditions})
        ORDER BY t.opened_at ASC
        LIMIT 5
    """), {
        "start": window_start,
        "end":   window_end,
    }).mappings().fetchall()

    score = row["score"] or 50

    if not trades:
        # Không có trade → RANGE_BOUND (thị trường không có cơ hội)
        # Chỉ dùng nếu score thấp (consistent: thị trường xấu, không ai trade)
        if score < SCORE_LOW_THRESHOLD:
            return {"label": "RANGE_BOUND", "confidence": 0.6, "trade_count": 0}
        return None  # Score cao mà không trade → ambiguous, skip

    # Có trades → classify dựa trên outcome
    total_pnl = sum(float(t["pnl"] or 0) for t in trades)
    avg_rr    = sum(float(t["actual_rr"] or t["rr_ratio"] or 0) for t in trades) / len(trades)
    wins      = sum(1 for t in trades if float(t["pnl"] or 0) > 0)
    win_rate  = wins / len(trades)

    if win_rate >= 0.6 and avg_rr >= 1.0:
        # Trades profitable, RR decent → PROFITABLE_TREND
        label_conf = min(1.0, 0.5 + win_rate * 0.3 + min(avg_rr, 3.0) * 0.07)
        return {
            "label":      "PROFITABLE_TREND",
            "confidence": round(label_conf, 3),
            "trade_count": len(trades),
            "avg_rr":     round(avg_rr, 2),
            "win_rate":   round(win_rate, 2),
        }
    elif win_rate <= 0.4 or total_pnl < 0:
        # Trades losing → FALSE_SIGNAL
        label_conf = min(1.0, 0.5 + (1 - win_rate) * 0.3)
        return {
            "label":      "FALSE_SIGNAL",
            "confidence": round(label_conf, 3),
            "trade_count": len(trades),
            "avg_rr":     round(avg_rr, 2),
            "win_rate":   round(win_rate, 2),
        }
    else:
        # Mixed results → RANGE_BOUND
        return {
            "label":      "RANGE_BOUND",
            "confidence": 0.5,
            "trade_count": len(trades),
            "avg_rr":     round(avg_rr, 2),
            "win_rate":   round(win_rate, 2),
        }


def _save_label(db, row, label_info: dict):
    """Ghi label vào bảng labeled_scans."""
    # Parse breakdown JSON
    bd_raw = row["breakdown"] or "{}"
    if isinstance(bd_raw, str):
        bd = json.loads(bd_raw)
    else:
        bd = bd_raw or {}

    db.execute(text("""
        INSERT INTO labeled_scans
          (scan_id, asset, timeframe, utc_hour, utc_dow,
           trend_strength, volatility_quality, session_bias, market_structure,
           adx_live, rsi_live, atr_pct_live,
           score, regime, confidence,
           label, label_confidence, trade_count,
           labeled_at)
        VALUES
          (:scan_id, :asset, :tf, :hour, :dow,
           :trend, :vol, :bias, :struct,
           :adx, :rsi, :atr,
           :score, :regime, :conf,
           :label, :label_conf, :trade_count,
           NOW())
        ON CONFLICT (scan_id) DO UPDATE SET
          label            = EXCLUDED.label,
          label_confidence = EXCLUDED.label_confidence,
          labeled_at       = NOW()
    """), {
        "scan_id":     row["scan_id"],
        "asset":       row["asset"],
        "tf":          row["timeframe"],
        "hour":        row["utc_hour"] or 0,
        "dow":         row["utc_dow"] or 0,
        "trend":       bd.get("trend_strength"),
        "vol":         bd.get("volatility_quality"),
        "bias":        bd.get("session_bias"),
        "struct":      bd.get("market_structure"),
        "adx":         bd.get("adx_live"),
        "rsi":         bd.get("rsi_live"),
        "atr":         bd.get("atr_pct_live"),
        "score":       row["score"],
        "regime":      row["regime"],
        "conf":        row["confidence"],
        "label":       label_info["label"],
        "label_conf":  label_info["confidence"],
        "trade_count": label_info.get("trade_count", 0),
    })


def get_training_stats(min_confidence: float = 0.6) -> dict:
    """Thống kê training data hiện có."""
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT label, COUNT(*) as cnt,
                   AVG(label_confidence) as avg_conf,
                   AVG(score) as avg_score
            FROM labeled_scans
            WHERE label_confidence >= :min_conf
            GROUP BY label ORDER BY cnt DESC
        """), {"min_conf": min_confidence}).mappings().fetchall()

        total = sum(r["cnt"] for r in rows)
        return {
            "total":          total,
            "min_confidence": min_confidence,
            "by_label": [dict(r) for r in rows],
            "ready_for_training": total >= 100,   # Cần ít nhất 100 samples
        }
    except Exception as e:
        return {"error": str(e), "total": 0, "ready_for_training": False}
    finally:
        db.close()