"""
ml/router.py — Phase 3 ML Management API
==========================================

Endpoints:
  GET  /ml/status              — Model + training data status
  POST /ml/train               — Trigger manual retrain
  POST /ml/activate/{version}  — Promote model to active
  GET  /ml/models              — All registered models
  GET  /ml/predict             — One-off prediction (test)
  GET  /ml/dataset-stats       — Labeled dataset statistics
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from sqlalchemy import text

from database import SessionLocal

logger = logging.getLogger("zarmor.ml")
router = APIRouter(tags=["ML"])


# ── GET /ml/status ─────────────────────────────────────────────────────────────
@router.get("/status")
async def ml_status():
    """Overview: active model + dataset stats + system readiness."""
    db = SessionLocal()
    try:
        # Active model
        model_row = db.execute(text("""
            SELECT version, cv_accuracy, cv_std, n_samples,
                   label_counts, feature_importance, is_active, trained_at
            FROM model_registry
            WHERE is_active = TRUE
            ORDER BY trained_at DESC LIMIT 1
        """)).fetchone()

        # Latest model (may differ from active)
        latest_row = db.execute(text("""
            SELECT version, cv_accuracy, trained_at, is_active
            FROM model_registry
            ORDER BY trained_at DESC LIMIT 1
        """)).fetchone()

        # Dataset stats
        label_stats = db.execute(text("""
            SELECT label, COUNT(*) as cnt, AVG(label_confidence) as avg_conf
            FROM labeled_scans
            WHERE label_confidence >= 0.6
            GROUP BY label ORDER BY cnt DESC
        """)).fetchall()

        total_labeled = db.execute(text(
            "SELECT COUNT(*) FROM labeled_scans WHERE label_confidence >= 0.6"
        )).scalar() or 0

        total_scans = db.execute(text(
            "SELECT COUNT(*) FROM radar_scans"
        )).scalar() or 0

        unlabeled = db.execute(text("""
            SELECT COUNT(*) FROM radar_scans rs
            LEFT JOIN labeled_scans ls ON rs.scan_id = ls.scan_id
            WHERE ls.scan_id IS NULL
              AND rs.created_at < NOW() - INTERVAL '3 hours'
        """)).scalar() or 0

        import json as _json
        active_model = None
        if model_row:
            active_model = {
                "version":      model_row["version"],
                "cv_accuracy":  round(model_row["cv_accuracy"] or 0, 4),
                "cv_std":       round(model_row["cv_std"] or 0, 4),
                "n_samples":    model_row["n_samples"],
                "trained_at":   model_row["trained_at"].isoformat() if model_row["trained_at"] else None,
                "label_counts": (
                    _json.loads(model_row["label_counts"])
                    if isinstance(model_row["label_counts"], str)
                    else model_row["label_counts"]
                ),
                "top_features": dict(sorted(
                    (_json.loads(model_row["feature_importance"])
                     if isinstance(model_row["feature_importance"], str)
                     else (model_row["feature_importance"] or {})).items(),
                    key=lambda x: -x[1]
                )[:5]),
            }

        return {
            "active_model":  active_model,
            "latest_version": latest_row["version"] if latest_row else None,
            "dataset": {
                "total_scans":    total_scans,
                "total_labeled":  total_labeled,
                "unlabeled_ready": unlabeled,
                "label_breakdown": [dict(r) for r in label_stats],
                "ready_for_training": total_labeled >= 50,
            },
            "xgboost_available": _check_xgboost(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        db.close()


# ── POST /ml/train ─────────────────────────────────────────────────────────────
@router.post("/train")
async def trigger_training(
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="Skip minimum sample check"),
):
    """
    Trigger manual retrain. Runs in background — returns immediately.
    Check /ml/status for result.
    """
    from ml.trainer import run_training_pipeline

    background_tasks.add_task(_run_and_log, run_training_pipeline, force)
    return {
        "status":  "queued",
        "message": "Training pipeline started in background. Check /ml/status in a few minutes.",
        "force":   force,
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }


async def _run_and_log(fn, *args, **kwargs):
    try:
        result = await fn(*args, **kwargs)
        logger.info(f"[ML API] Training result: status={result.get('status')}")
    except Exception as e:
        logger.error(f"[ML API] Training failed: {e}")


# ── POST /ml/label ─────────────────────────────────────────────────────────────
@router.post("/label")
async def trigger_labeling(
    background_tasks: BackgroundTasks,
    limit: int = Query(500, le=5000),
):
    """Trigger labeling pipeline separately (without full retrain)."""
    from ml.labeler import label_unlabeled_scans

    background_tasks.add_task(_label_bg, label_unlabeled_scans, limit)
    return {
        "status":    "queued",
        "message":   f"Labeling up to {limit} scans in background.",
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }


async def _label_bg(fn, limit):
    try:
        result = fn(limit)
        logger.info(f"[ML API] Labeling: {result}")
    except Exception as e:
        logger.error(f"[ML API] Labeling failed: {e}")


# ── POST /ml/activate/{version} ───────────────────────────────────────────────
@router.post("/activate/{version}")
async def activate_model_version(version: str):
    """Promote a model version to active. Use after manual review."""
    from ml.classifier import activate_model

    ok = activate_model(version)
    if not ok:
        raise HTTPException(404, f"Model version '{version}' not found in registry.")
    return {
        "activated": True,
        "version":   version,
        "message":   f"Model v{version} is now active. New predictions will use this model.",
    }


# ── GET /ml/models ─────────────────────────────────────────────────────────────
@router.get("/models")
async def list_models():
    """All registered model versions."""
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT version, cv_accuracy, cv_std, n_samples,
                   is_active, trained_at
            FROM model_registry
            ORDER BY trained_at DESC
            LIMIT 20
        """)).fetchall()
        return {
            "count":  len(rows),
            "models": [dict(r) for r in rows],
        }
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        db.close()


# ── GET /ml/predict ────────────────────────────────────────────────────────────
@router.get("/predict")
async def ml_predict(
    asset:     str = Query("GOLD",  description="Asset: GOLD|EURUSD|BTC|NASDAQ"),
    timeframe: str = Query("H1",    description="Timeframe: M5|M15|H1"),
):
    """
    One-off ML prediction using current active model.
    Calls radar/engine.py to get features, then runs ML classifier.
    """
    try:
        from radar.engine import compute
        from ml.classifier import predict_regime, is_model_available

        if not is_model_available():
            return {
                "status":  "no_model",
                "message": "No ML model trained yet. Use POST /ml/train to start.",
                "fallback": "Using rule-based engine.",
            }

        # Get current features from engine
        engine_result = compute(asset, timeframe)
        features = {
            **engine_result.breakdown,
            "utc_hour": datetime.now(timezone.utc).hour,
            "utc_dow":  datetime.now(timezone.utc).weekday(),
            "score":    engine_result.score,
        }

        ml_result = predict_regime(features)
        if ml_result is None:
            return {"status": "prediction_failed", "fallback_regime": engine_result.regime}

        return {
            "asset":          asset,
            "timeframe":      timeframe,
            "engine_regime":  engine_result.regime,
            "engine_score":   engine_result.score,
            "ml_regime":      ml_result["regime"],
            "ml_confidence":  ml_result["confidence"],
            "ml_proba":       ml_result["probabilities"],
            "model_version":  ml_result["model_version"],
            "agreement":      engine_result.regime == ml_result["regime"],
        }
    except Exception as e:
        raise HTTPException(500, str(e))


# ── GET /ml/dataset-stats ──────────────────────────────────────────────────────
@router.get("/dataset-stats")
async def dataset_stats():
    """Detailed labeled dataset statistics."""
    from ml.labeler import get_training_stats
    stats = get_training_stats(min_confidence=0.6)

    db = SessionLocal()
    try:
        # By asset breakdown
        by_asset = db.execute(text("""
            SELECT asset, label, COUNT(*) as cnt
            FROM labeled_scans
            WHERE label_confidence >= 0.6
            GROUP BY asset, label ORDER BY asset, cnt DESC
        """)).fetchall()

        # By timeframe
        by_tf = db.execute(text("""
            SELECT timeframe, label, COUNT(*) as cnt
            FROM labeled_scans
            WHERE label_confidence >= 0.6
            GROUP BY timeframe, label ORDER BY timeframe, cnt DESC
        """)).fetchall()

        # By hour of day (signal quality patterns)
        by_hour = db.execute(text("""
            SELECT utc_hour, label, COUNT(*) as cnt
            FROM labeled_scans
            WHERE label_confidence >= 0.6
            GROUP BY utc_hour, label ORDER BY utc_hour
        """)).fetchall()

        return {
            **stats,
            "by_asset":     [dict(r) for r in by_asset],
            "by_timeframe": [dict(r) for r in by_tf],
            "by_hour":      [dict(r) for r in by_hour],
        }
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        db.close()


# ── Helpers ────────────────────────────────────────────────────────────────────
def _check_xgboost() -> bool:
    try:
        import xgboost
        return True
    except ImportError:
        return False
