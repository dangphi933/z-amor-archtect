"""
performance/scheduler.py — Phase 2 Auto-Compute Scheduler
==========================================================
Chạy mỗi 6h: tính performance cho tất cả active accounts.
Ghi kết quả vào performance_snapshots.

Tích hợp vào main.py lifespan:
    from performance.scheduler import start_scheduler, stop_scheduler

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        start_scheduler()
        yield
        stop_scheduler()

Feedback loop:
  Sau khi tính metrics → ghi thêm vào feedback_log
  (Phase 3 ML trainer sẽ đọc từ bảng này để retrain)
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

logger = logging.getLogger("zarmor.perf_scheduler")

_task: asyncio.Task = None
_running = False


async def _run_performance_cycle():
    """Lấy tất cả active account_ids → tính performance → log feedback."""
    from database import SessionLocal, TradingAccount
    from performance.service import compute_performance

    db = SessionLocal()
    try:
        accounts = db.query(TradingAccount.account_id).all()
        account_ids = [a.account_id for a in accounts]
    except Exception as e:
        logger.error(f"[SCHED] DB read failed: {e}")
        return
    finally:
        db.close()

    if not account_ids:
        logger.info("[SCHED] No accounts found — skip.")
        return

    logger.info(f"[SCHED] Computing performance for {len(account_ids)} accounts...")

    for acc in account_ids:
        try:
            for period in (7, 30, 90):
                result = compute_performance(acc, period)
                if "error" not in result:
                    _write_feedback_log(acc, period, result)
                await asyncio.sleep(0.1)   # avoid thundering herd
        except Exception as e:
            logger.error(f"[SCHED] Error for {acc}: {e}")

    logger.info("[SCHED] Performance cycle done.")


def _write_feedback_log(account_id: str, period_days: int, metrics: dict):
    """
    Ghi vào feedback_log — Phase 3 ML trainer đọc bảng này.

    Mỗi row = một snapshot metrics tại một thời điểm.
    ML trainer dùng metrics (sharpe, max_dd, win_rate...) làm features
    để dự đoán regime nào tốt nhất cho account này.
    """
    from database import SessionLocal
    db = SessionLocal()
    try:
        db.execute(text("""
            INSERT INTO feedback_log
              (account_id, period_days, sharpe, sortino, calmar,
               max_drawdown, win_rate, profit_factor, total_trades,
               total_pnl, symbol_breakdown, logged_at)
            VALUES
              (:acc, :pd, :sharpe, :sortino, :calmar,
               :max_dd, :wr, :pf, :tt, :tp, :sb::jsonb, NOW())
        """), {
            "acc":     account_id,
            "pd":      period_days,
            "sharpe":  metrics.get("sharpe"),
            "sortino": metrics.get("sortino"),
            "calmar":  metrics.get("calmar"),
            "max_dd":  metrics.get("max_drawdown"),
            "wr":      metrics.get("win_rate"),
            "pf":      metrics.get("profit_factor"),
            "tt":      metrics.get("total_trades"),
            "tp":      metrics.get("total_pnl"),
            "sb":      json.dumps(metrics.get("symbol_breakdown", {})),
        })
        db.commit()
    except Exception as e:
        logger.debug(f"[FEEDBACK] log write failed (table may not exist yet): {e}")
        db.rollback()
    finally:
        db.close()


async def _scheduler_loop():
    """Chạy mỗi 6h — không dừng cho tới khi stop_scheduler() được gọi."""
    global _running
    _running = True
    logger.info("[SCHED] Performance scheduler started (6h interval)")
    while _running:
        try:
            await _run_performance_cycle()
        except Exception as e:
            logger.error(f"[SCHED] Cycle error: {e}")
        # Chờ 6h
        for _ in range(6 * 60):   # check _running mỗi phút
            if not _running:
                break
            await asyncio.sleep(60)


def start_scheduler():
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_scheduler_loop())
        logger.info("[SCHED] Task created.")


def stop_scheduler():
    global _running, _task
    _running = False
    if _task and not _task.done():
        _task.cancel()
    logger.info("[SCHED] Stopped.")


# ── Migration helper cho feedback_log ─────────────────────────────────────────
FEEDBACK_LOG_SQL = """
-- Chạy sau migration_performance.sql
CREATE TABLE IF NOT EXISTS feedback_log (
    id               SERIAL PRIMARY KEY,
    account_id       VARCHAR(50) NOT NULL,
    period_days      INT         NOT NULL,
    sharpe           FLOAT,
    sortino          FLOAT,
    calmar           FLOAT,
    max_drawdown     FLOAT,
    win_rate         FLOAT,
    profit_factor    FLOAT,
    total_trades     INT,
    total_pnl        FLOAT,
    symbol_breakdown JSONB,
    logged_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_feedback_account ON feedback_log (account_id, logged_at DESC);

-- Đây là "feature store" Phase 3:
-- SELECT * FROM feedback_log WHERE account_id = 'X' ORDER BY logged_at DESC LIMIT 100
-- → feed vào ML trainer để retrain regime classifier
"""
