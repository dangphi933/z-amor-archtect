"""
performance/service.py — Phase 2 Performance Attribution
=========================================================
Tính Sharpe, Sortino, Calmar, Max DD, Win Rate từ trade_history + session_history.
Output được lưu vào bảng performance_snapshots → khép vòng feedback loop:

  trade_history + session_history
        ↓
  performance/service.py  (tính metrics)
        ↓
  performance_snapshots (PostgreSQL)
        ↓
  /api/performance/{account_id}  (dashboard)
        ↓
  [Phase 3] Feature store → ML retrain

Deploy:
  1. Chạy migration_performance.sql trước
  2. Import router trong main.py:
       from performance.router import router as perf_router
       app.include_router(perf_router, prefix="/performance")
  3. Background task tự động tính mỗi 6h (xem scheduler bên dưới)
"""

import math
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import text
from database import SessionLocal, SessionHistory, TradeHistory

logger = logging.getLogger("zarmor.performance")

# Risk-free rate năm (approximation — dùng Fed Funds Rate ~5.25%)
RISK_FREE_DAILY = 0.0525 / 252   # ~0.000208/ngày


# ── Core Metric Calculators ────────────────────────────────────────────────────

def _daily_returns(sessions: list) -> list[float]:
    """Tính daily return % từ list session records đã sắp xếp cũ → mới."""
    rets = []
    for s in sessions:
        ob = s.get("opening_balance") or s.get("opening_balance")
        pnl = s.get("pnl") or 0
        if ob and ob > 0:
            rets.append(pnl / ob * 100)   # return %
    return rets


def calc_sharpe(daily_returns: list[float]) -> Optional[float]:
    """
    Sharpe = (mean_return - risk_free) / std_return × sqrt(252)
    daily_returns: list of daily % returns (e.g. 0.5 = 0.5%)
    Returns None nếu không đủ data.
    """
    if len(daily_returns) < 5:
        return None
    n   = len(daily_returns)
    mu  = sum(daily_returns) / n
    rf  = RISK_FREE_DAILY * 100   # convert to %
    var = sum((r - mu) ** 2 for r in daily_returns) / max(n - 1, 1)
    std = math.sqrt(var)
    if std < 1e-9:
        return None
    return round((mu - rf) / std * math.sqrt(252), 3)


def calc_sortino(daily_returns: list[float]) -> Optional[float]:
    """
    Sortino = (mean_return - risk_free) / downside_std × sqrt(252)
    Chỉ tính std của các ngày âm (downside deviation).
    """
    if len(daily_returns) < 5:
        return None
    mu    = sum(daily_returns) / len(daily_returns)
    rf    = RISK_FREE_DAILY * 100
    downs = [r for r in daily_returns if r < 0]
    if len(downs) < 2:
        return None   # không có ngày lỗ → Sortino vô nghĩa
    down_var = sum(r ** 2 for r in downs) / max(len(downs) - 1, 1)
    down_std = math.sqrt(down_var)
    if down_std < 1e-9:
        return None
    return round((mu - rf) / down_std * math.sqrt(252), 3)


def calc_max_drawdown(sessions: list) -> Optional[float]:
    """
    Max Drawdown = (peak_equity - trough_equity) / peak_equity × 100 (%)
    Dùng closing_balance qua các session.
    """
    if not sessions:
        return None
    balances = [s.get("closing_balance") or 0 for s in sessions]
    balances = [b for b in balances if b > 0]
    if len(balances) < 2:
        return None
    peak = balances[0]
    max_dd = 0.0
    for b in balances:
        if b > peak:
            peak = b
        dd = (peak - b) / peak * 100
        if dd > max_dd:
            max_dd = dd
    return round(max_dd, 2)


def calc_calmar(annual_return_pct: float, max_dd: float) -> Optional[float]:
    """
    Calmar = Annualized Return / Max Drawdown
    Calmar > 1 = acceptable, > 3 = excellent.
    """
    if max_dd is None or max_dd < 1e-6:
        return None
    return round(annual_return_pct / max_dd, 3)


def calc_profit_factor(trades: list) -> Optional[float]:
    """
    Profit Factor = gross_profit / gross_loss
    PF > 1.5 = good, > 2.0 = excellent.
    """
    gross_win  = sum(t.get("profit", 0) or 0 for t in trades if (t.get("profit") or 0) > 0)
    gross_loss = sum(abs(t.get("profit", 0) or 0) for t in trades if (t.get("profit") or 0) < 0)
    if gross_loss < 1e-6:
        return None
    return round(gross_win / gross_loss, 3)


def calc_win_rate(trades: list) -> Optional[float]:
    """Win Rate % từ closed trades."""
    closed = [t for t in trades if t.get("result") in ("WIN", "LOSS", "win", "loss")
              or t.get("profit") is not None]
    if not closed:
        return None
    wins = sum(1 for t in closed if (t.get("result", "").upper() == "WIN") or (t.get("profit", 0) or 0) > 0)
    return round(wins / len(closed) * 100, 1)


def calc_avg_rr(trades: list) -> Optional[float]:
    """Avg R:R ratio từ closed trades có actual_rr."""
    rr_vals = [t.get("actual_rr") or t.get("rr_ratio") for t in trades]
    rr_vals = [r for r in rr_vals if r and r > 0]
    if not rr_vals:
        return None
    return round(sum(rr_vals) / len(rr_vals), 2)


def calc_expectancy(trades: list) -> Optional[float]:
    """
    Expectancy = (Win% × Avg_Win) - (Loss% × Avg_Loss)
    Dương = profitable strategy, âm = ruin strategy.
    """
    profits = [t.get("profit", 0) or 0 for t in trades if t.get("profit") is not None]
    if len(profits) < 3:
        return None
    wins  = [p for p in profits if p > 0]
    losses = [abs(p) for p in profits if p < 0]
    if not wins or not losses:
        return None
    wr = len(wins) / len(profits)
    avg_win  = sum(wins)   / len(wins)
    avg_loss = sum(losses) / len(losses)
    return round(wr * avg_win - (1 - wr) * avg_loss, 2)


# ── Main Attribution Function ──────────────────────────────────────────────────

def compute_performance(account_id: str, period_days: int = 30) -> dict:
    """
    Tính full performance attribution cho account trong period_days ngày gần nhất.
    Trả về dict đầy đủ để lưu vào performance_snapshots.
    """
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)

        # Sessions
        sess_records = (
            db.query(SessionHistory)
            .filter(SessionHistory.account_id == str(account_id))
            .filter(SessionHistory.created_at >= cutoff)
            .order_by(SessionHistory.created_at.asc())
            .all()
        )
        sessions = [
            {
                "opening_balance": r.opening_balance,
                "closing_balance": r.closing_balance,
                "pnl":             r.pnl,
                "trade_count":     r.trade_count,
                "win_count":       r.win_count,
                "loss_count":      r.loss_count,
            }
            for r in sess_records
        ]

        # Trades
        trade_records = (
            db.query(TradeHistory)
            .filter(TradeHistory.account_id == str(account_id))
            .filter(TradeHistory.created_at >= cutoff)
            .order_by(TradeHistory.created_at.asc())
            .all()
        )
        trades = [
            {
                "profit":    r.pnl,
                "result":    getattr(r, "result", None),
                "actual_rr": r.actual_rr,
                "rr_ratio":  r.rr_ratio,
                "symbol":    r.symbol,
            }
            for r in trade_records
        ]

        # ── Compute metrics ────────────────────────────────────────────────────
        daily_rets = _daily_returns(sessions)

        sharpe     = calc_sharpe(daily_rets)
        sortino    = calc_sortino(daily_rets)
        max_dd     = calc_max_drawdown(sessions)
        win_rate   = calc_win_rate(trades)
        avg_rr     = calc_avg_rr(trades)
        pf         = calc_profit_factor(trades)
        expectancy = calc_expectancy(trades)

        # Total PnL và annualized return
        total_pnl   = sum(s.get("pnl") or 0 for s in sessions)
        start_bal   = sessions[0]["opening_balance"] if sessions else None
        end_bal     = sessions[-1]["closing_balance"] if sessions else None

        ann_return = None
        if start_bal and start_bal > 0 and len(sessions) >= 3:
            total_ret_pct = (end_bal - start_bal) / start_bal * 100
            ann_return    = round(total_ret_pct * 365 / period_days, 2)

        calmar = calc_calmar(ann_return or 0, max_dd)

        # Total trade count
        total_trades = len(trades)
        total_wins   = sum(1 for t in trades if (t.get("profit") or 0) > 0)
        total_losses = total_trades - total_wins

        # ── Symbol breakdown ───────────────────────────────────────────────────
        symbol_stats = {}
        for t in trades:
            sym = t.get("symbol") or "UNKNOWN"
            if sym not in symbol_stats:
                symbol_stats[sym] = {"trades": 0, "pnl": 0.0, "wins": 0}
            symbol_stats[sym]["trades"] += 1
            symbol_stats[sym]["pnl"]    += t.get("profit") or 0
            if (t.get("profit") or 0) > 0:
                symbol_stats[sym]["wins"] += 1

        for sym in symbol_stats:
            n = symbol_stats[sym]["trades"]
            symbol_stats[sym]["win_rate"] = round(symbol_stats[sym]["wins"] / max(n, 1) * 100, 1)

        result = {
            "account_id":    account_id,
            "period_days":   period_days,
            "computed_at":   datetime.now(timezone.utc).isoformat(),

            # Core metrics
            "sharpe":        sharpe,
            "sortino":       sortino,
            "calmar":        calmar,
            "max_drawdown":  max_dd,
            "win_rate":      win_rate,
            "avg_rr":        avg_rr,
            "profit_factor": pf,
            "expectancy":    expectancy,
            "annual_return": ann_return,

            # Volume
            "total_sessions": len(sessions),
            "total_trades":   total_trades,
            "total_wins":     total_wins,
            "total_losses":   total_losses,
            "total_pnl":      round(total_pnl, 2),
            "start_balance":  round(start_bal, 2) if start_bal else None,
            "end_balance":    round(end_bal, 2)   if end_bal   else None,

            # By symbol
            "symbol_breakdown": symbol_stats,

            # Grades
            "grades": _grade_metrics(sharpe, sortino, calmar, max_dd, win_rate, pf),

            # Raw daily returns for chart
            "daily_returns": [round(r, 4) for r in daily_rets],
        }

        # Lưu snapshot vào DB
        _save_snapshot(db, account_id, period_days, result)

        logger.info(
            f"[PERF] {account_id} Sharpe={sharpe} Sortino={sortino} "
            f"Calmar={calmar} MaxDD={max_dd}% WR={win_rate}%"
        )
        return result

    except Exception as e:
        logger.error(f"[PERF] compute_performance error: {e}", exc_info=True)
        return {"error": str(e), "account_id": account_id}
    finally:
        db.close()


def _grade_metrics(sharpe, sortino, calmar, max_dd, win_rate, pf) -> dict:
    """Chấm điểm A-F cho từng metric — dùng để hiển thị dashboard."""
    def grade(val, thresholds):
        """thresholds: [(value, grade), ...] sorted HIGH to LOW"""
        if val is None:
            return "N/A"
        for thresh, g in thresholds:
            if val >= thresh:
                return g
        return "F"

    return {
        "sharpe":        grade(sharpe,   [(2.0,"A"), (1.5,"B"), (1.0,"C"), (0.5,"D"), (0,"F")]),
        "sortino":       grade(sortino,  [(3.0,"A"), (2.0,"B"), (1.5,"C"), (0.8,"D"), (0,"F")]),
        "calmar":        grade(calmar,   [(3.0,"A"), (2.0,"B"), (1.0,"C"), (0.5,"D"), (0,"F")]),
        "max_drawdown":  grade(100 - (max_dd or 100), [(95,"A"), (90,"B"), (85,"C"), (75,"D"), (0,"F")]),
        "win_rate":      grade(win_rate, [(65,"A"), (55,"B"), (50,"C"), (45,"D"), (0,"F")]),
        "profit_factor": grade(pf,       [(2.0,"A"), (1.8,"B"), (1.5,"C"), (1.2,"D"), (0,"F")]),
    }


def _save_snapshot(db, account_id: str, period_days: int, data: dict):
    """Upsert vào performance_snapshots."""
    try:
        db.execute(text("""
            INSERT INTO performance_snapshots
              (account_id, period_days, sharpe, sortino, calmar, max_drawdown,
               win_rate, avg_rr, profit_factor, expectancy, annual_return,
               total_trades, total_pnl, symbol_breakdown, daily_returns,
               grades, computed_at)
            VALUES
              (:account_id, :period_days, :sharpe, :sortino, :calmar, :max_dd,
               :win_rate, :avg_rr, :pf, :expectancy, :ann_return,
               :total_trades, :total_pnl, :sym_bd::jsonb, :daily_rets::jsonb,
               :grades::jsonb, NOW())
            ON CONFLICT (account_id, period_days)
            DO UPDATE SET
              sharpe           = EXCLUDED.sharpe,
              sortino          = EXCLUDED.sortino,
              calmar           = EXCLUDED.calmar,
              max_drawdown     = EXCLUDED.max_drawdown,
              win_rate         = EXCLUDED.win_rate,
              avg_rr           = EXCLUDED.avg_rr,
              profit_factor    = EXCLUDED.profit_factor,
              expectancy       = EXCLUDED.expectancy,
              annual_return    = EXCLUDED.annual_return,
              total_trades     = EXCLUDED.total_trades,
              total_pnl        = EXCLUDED.total_pnl,
              symbol_breakdown = EXCLUDED.symbol_breakdown,
              daily_returns    = EXCLUDED.daily_returns,
              grades           = EXCLUDED.grades,
              computed_at      = NOW()
        """), {
            "account_id":   account_id,
            "period_days":  period_days,
            "sharpe":       data.get("sharpe"),
            "sortino":      data.get("sortino"),
            "calmar":       data.get("calmar"),
            "max_dd":       data.get("max_drawdown"),
            "win_rate":     data.get("win_rate"),
            "avg_rr":       data.get("avg_rr"),
            "pf":           data.get("profit_factor"),
            "expectancy":   data.get("expectancy"),
            "ann_return":   data.get("annual_return"),
            "total_trades": data.get("total_trades"),
            "total_pnl":    data.get("total_pnl"),
            "sym_bd":       json.dumps(data.get("symbol_breakdown", {})),
            "daily_rets":   json.dumps(data.get("daily_returns", [])),
            "grades":       json.dumps(data.get("grades", {})),
        })
        db.commit()
    except Exception as e:
        logger.warning(f"[PERF] snapshot save failed: {e}")
        db.rollback()


def get_latest_snapshot(account_id: str, period_days: int = 30) -> Optional[dict]:
    """Lấy snapshot mới nhất từ DB — không tính lại."""
    db = SessionLocal()
    try:
        row = db.execute(text("""
            SELECT * FROM performance_snapshots
            WHERE account_id = :acc AND period_days = :pd
            ORDER BY computed_at DESC LIMIT 1
        """), {"acc": account_id, "pd": period_days}).fetchone()
        return dict(row._mapping) if row else None
    except Exception:
        return None
    finally:
        db.close()
