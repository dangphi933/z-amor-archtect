"""
ml/trainer.py — Phase 3 Weekly Auto-Retrain Scheduler
======================================================
Orchestrates the full ML training pipeline:
  1. label_unlabeled_scans()    → labeler.py
  2. check training data stats
  3. train() new XGBoost model  → classifier.py
  4. auto-activate if improvement > threshold
  5. log to telegram + audit trail

Integrated vào main.py lifespan — chạy mỗi 7 ngày.

Cũng expose manual trigger:
  POST /ml/train          → trigger manual retrain
  GET  /ml/status         → model + training status
  POST /ml/activate/{ver} → promote model version
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("zarmor.ml.trainer")

_retrain_task: asyncio.Task = None
_running = False

# Threshold: chỉ auto-activate nếu CV accuracy cải thiện ít nhất X%
AUTO_ACTIVATE_IMPROVEMENT = 0.02   # +2%
MIN_SAMPLES_TO_TRAIN      = 50     # Cần ít nhất 50 labeled samples
RETRAIN_INTERVAL_DAYS     = 7      # Retrain mỗi 7 ngày


async def run_training_pipeline(force: bool = False) -> dict:
    """
    Full pipeline: label → check → train → (auto-activate).
    force=True: bỏ qua minimum sample check.
    Returns result dict.
    """
    started_at = datetime.now(timezone.utc)
    result = {
        "started_at":    started_at.isoformat(),
        "labeling":      None,
        "training":      None,
        "activated":     False,
        "status":        "started",
        "error":         None,
    }

    try:
        # ── Step 1: Label new scans ────────────────────────────────────────
        logger.info("[TRAINER] Step 1/3: Labeling unlabeled scans...")
        from .labeler import label_unlabeled_scans, get_training_stats
        label_result = label_unlabeled_scans(limit=1000)
        result["labeling"] = label_result
        logger.info(f"[TRAINER] Labeling: {label_result}")

        # ── Step 2: Check if enough data ──────────────────────────────────
        stats = get_training_stats(min_confidence=0.6)
        result["data_stats"] = stats

        if not force and not stats.get("ready_for_training"):
            total = stats.get("total", 0)
            msg = f"Not enough labeled data: {total} samples (need {MIN_SAMPLES_TO_TRAIN})"
            logger.warning(f"[TRAINER] {msg}")
            result["status"] = "skipped_insufficient_data"
            result["message"] = msg
            return result

        # ── Step 3: Train new model ────────────────────────────────────────
        logger.info(f"[TRAINER] Step 2/3: Training XGBoost on {stats.get('total', 0)} samples...")
        from .classifier import train, activate_model, load_active_model

        train_result = await asyncio.get_event_loop().run_in_executor(
            None,  # threadpool
            lambda: train(min_confidence=0.6, min_samples=MIN_SAMPLES_TO_TRAIN if not force else 10)
        )

        if train_result is None:
            result["status"] = "training_failed"
            result["error"]  = "train() returned None — check logs for details"
            return result

        result["training"] = train_result
        new_version  = train_result["version"]
        new_accuracy = train_result["cv_accuracy"]

        # ── Step 4: Auto-activate if improvement ──────────────────────────
        logger.info(f"[TRAINER] Step 3/3: Evaluating model v{new_version}...")
        current = load_active_model()
        current_acc = current.get("cv_accuracy", 0) if current else 0

        should_activate = (
            current_acc == 0  # No active model yet
            or (new_accuracy - current_acc) >= AUTO_ACTIVATE_IMPROVEMENT
        )

        if should_activate:
            activated = activate_model(new_version)
            result["activated"] = activated
            if activated:
                logger.info(
                    f"[TRAINER] ✅ Auto-activated v{new_version} "
                    f"(acc {current_acc:.3f} → {new_accuracy:.3f})"
                )
        else:
            logger.info(
                f"[TRAINER] ℹ New model v{new_version} not auto-activated "
                f"(acc {new_accuracy:.3f} vs current {current_acc:.3f}, "
                f"need +{AUTO_ACTIVATE_IMPROVEMENT:.0%} improvement)"
            )

        result["status"] = "success"

        # ── Notify via Telegram ────────────────────────────────────────────
        await _notify_training_result(result)

    except Exception as e:
        logger.error(f"[TRAINER] Pipeline error: {e}", exc_info=True)
        result["status"] = "error"
        result["error"]  = str(e)

    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    result["duration_sec"] = (
        datetime.now(timezone.utc) - started_at
    ).total_seconds()

    return result


async def _notify_training_result(result: dict):
    """Gửi Telegram notification về training result."""
    try:
        from telegram_engine import push_to_telegram
        training = result.get("training", {})
        if not training:
            return

        version  = training.get("version", "?")
        accuracy = training.get("cv_accuracy", 0)
        n        = training.get("n_samples", 0)
        activated = result.get("activated", False)

        msg = (
            f"🤖 <b>ML RETRAIN COMPLETE</b>\n"
            f"Version: <code>{version}</code>\n"
            f"CV Accuracy: <b>{accuracy:.1%}</b> ± {training.get('cv_std',0):.1%}\n"
            f"Samples: {n}\n"
            f"Status: {'✅ ACTIVATED' if activated else '⏸ Pending review'}\n\n"
            f"Top features:\n"
        )
        fi = training.get("feature_importance", {})
        top3 = sorted(fi.items(), key=lambda x: -x[1])[:3]
        for feat, imp in top3:
            msg += f"  • {feat}: {imp:.1%}\n"

        await push_to_telegram(msg)
    except Exception as e:
        logger.debug(f"[TRAINER] Telegram notify failed: {e}")


# ── Background Scheduler ──────────────────────────────────────────────────────

async def _trainer_loop():
    """Chạy weekly retrain loop."""
    global _running
    _running = True
    logger.info(f"[TRAINER] Auto-retrain scheduler started ({RETRAIN_INTERVAL_DAYS}d interval)")

    # Chạy lần đầu sau 30 phút (server vừa start)
    await asyncio.sleep(30 * 60)

    while _running:
        try:
            logger.info("[TRAINER] Starting scheduled retrain cycle...")
            await run_training_pipeline()
        except Exception as e:
            logger.error(f"[TRAINER] Scheduled cycle error: {e}")

        # Chờ N ngày, kiểm tra _running mỗi giờ
        for _ in range(RETRAIN_INTERVAL_DAYS * 24):
            if not _running:
                break
            await asyncio.sleep(3600)


def start_trainer():
    global _retrain_task
    if _retrain_task is None or _retrain_task.done():
        _retrain_task = asyncio.create_task(_trainer_loop())
        logger.info("[TRAINER] Task created.")


def stop_trainer():
    global _running, _retrain_task
    _running = False
    if _retrain_task and not _retrain_task.done():
        _retrain_task.cancel()
    logger.info("[TRAINER] Stopped.")
