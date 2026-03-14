"""
app/jobs/performance_batch.py
================================
Job: Performance attribution batch — mỗi 1 giờ.
Tính win_rate, avg_rr, daily_pnl cho từng account → upsert vào za_performance_summary.
Extract từ performance/scheduler.py monolith.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from shared.libs.database.models import SessionLocal

logger = logging.getLogger("zarmor.scheduler.performance")


def run_performance_batch():
    """Batch compute performance metrics cho tất cả active accounts."""
    db = SessionLocal()
    try:
        _ensure_summary_table(db)

        # Lấy tất cả accounts có trade history trong 30 ngày
        since = datetime.now(timezone.utc) - timedelta(days=30)
        rows = db.execute(text("""
            SELECT DISTINCT account_id FROM trade_history
            WHERE opened_at >= :since
        """), {"since": since}).fetchall()

        accounts = [r.account_id for r in rows]
        logger.info(f"[PERFORMANCE] Processing {len(accounts)} accounts")

        for account_id in accounts:
            try:
                _compute_account_performance(db, account_id, since)
            except Exception as e:
                logger.error(f"[PERFORMANCE] Error for {account_id}: {e}")
                db.rollback()

        db.commit()
        logger.info(f"[PERFORMANCE] Batch complete: {len(accounts)} accounts updated")

    except Exception as e:
        logger.error(f"[PERFORMANCE] Batch failed: {e}")
        db.rollback()
    finally:
        db.close()


def _compute_account_performance(db, account_id: str, since: datetime):
    """Compute + upsert performance summary for 1 account."""
    rows = db.execute(text("""
        SELECT pnl, rr_ratio, opened_at, closed_at
        FROM trade_history
        WHERE account_id = :aid AND closed_at IS NOT NULL AND opened_at >= :since
        ORDER BY closed_at DESC
    """), {"aid": account_id, "since": since}).fetchall()

    if not rows:
        return

    pnls    = [float(r.pnl or 0) for r in rows]
    rrs     = [float(r.rr_ratio or 0) for r in rows if r.rr_ratio]
    winners = [p for p in pnls if p > 0]
    losers  = [p for p in pnls if p <= 0]

    n_total  = len(pnls)
    win_rate = len(winners) / n_total * 100 if n_total > 0 else 0
    avg_rr   = sum(rrs) / len(rrs) if rrs else 0
    net_pnl  = sum(pnls)
    avg_win  = sum(winners) / len(winners) if winners else 0
    avg_loss = sum(losers)  / len(losers)  if losers  else 0
    profit_factor = abs(sum(winners) / sum(losers)) if sum(losers) != 0 else 99.9

    # Today's PnL
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    daily_pnl   = sum(
        float(r.pnl or 0) for r in rows
        if r.closed_at and r.closed_at >= today_start
    )

    db.execute(text("""
        INSERT INTO za_performance_summary
          (account_id, period_start, period_end, n_trades, win_rate, avg_rr,
           net_pnl, daily_pnl, avg_win, avg_loss, profit_factor, updated_at)
        VALUES
          (:aid, :start, :end, :n, :wr, :rr,
           :pnl, :dpnl, :aw, :al, :pf, NOW())
        ON CONFLICT (account_id) DO UPDATE SET
          period_start  = EXCLUDED.period_start,
          period_end    = EXCLUDED.period_end,
          n_trades      = EXCLUDED.n_trades,
          win_rate      = EXCLUDED.win_rate,
          avg_rr        = EXCLUDED.avg_rr,
          net_pnl       = EXCLUDED.net_pnl,
          daily_pnl     = EXCLUDED.daily_pnl,
          avg_win       = EXCLUDED.avg_win,
          avg_loss      = EXCLUDED.avg_loss,
          profit_factor = EXCLUDED.profit_factor,
          updated_at    = NOW()
    """), {
        "aid": account_id, "start": since,
        "end": datetime.now(timezone.utc),
        "n": n_total, "wr": round(win_rate, 2),
        "rr": round(avg_rr, 3), "pnl": round(net_pnl, 2),
        "dpnl": round(daily_pnl, 2), "aw": round(avg_win, 2),
        "al": round(avg_loss, 2), "pf": round(profit_factor, 3),
    })


def _ensure_summary_table(db):
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS za_performance_summary (
            account_id    VARCHAR(50) PRIMARY KEY,
            period_start  TIMESTAMPTZ,
            period_end    TIMESTAMPTZ,
            n_trades      INT DEFAULT 0,
            win_rate      FLOAT DEFAULT 0,
            avg_rr        FLOAT DEFAULT 0,
            net_pnl       FLOAT DEFAULT 0,
            daily_pnl     FLOAT DEFAULT 0,
            avg_win       FLOAT DEFAULT 0,
            avg_loss      FLOAT DEFAULT 0,
            profit_factor FLOAT DEFAULT 0,
            updated_at    TIMESTAMPTZ DEFAULT NOW()
        )
    """))
    db.commit()
