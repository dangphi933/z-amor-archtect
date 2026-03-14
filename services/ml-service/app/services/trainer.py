"""
app/services/trainer.py
=========================
ML training pipeline — extract từ ml/trainer.py monolith.

Pipeline:
  1. Load labeled scans từ DB (radar_labeled_scans)
  2. Feature engineering
  3. Train RandomForestClassifier
  4. Evaluate (accuracy, confusion matrix)
  5. Save model to disk
  6. Update model_registry DB table

Chạy async — training job được trigger qua POST /ml/train.
"""

import os
import json
import pickle
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("zarmor.ml.trainer")

MODEL_DIR   = os.getenv("MODEL_DIR", "/app/models")
MIN_SAMPLES = int(os.getenv("ML_MIN_SAMPLES", "100"))

# Training state
_training_status = {
    "is_running":    False,
    "last_run":      None,
    "last_accuracy": None,
    "last_samples":  None,
    "last_error":    None,
}


def get_training_status() -> dict:
    return dict(_training_status)


async def run_training_job(triggered_by: str = "api") -> dict:
    """
    Async training job — gọi trong background task.
    Returns summary dict.
    """
    global _training_status

    if _training_status["is_running"]:
        return {"status": "already_running", "message": "Training đang chạy. Thử lại sau."}

    _training_status["is_running"] = True
    _training_status["last_error"] = None

    try:
        result = await _train()
        _training_status.update({
            "is_running":    False,
            "last_run":      datetime.now(timezone.utc).isoformat(),
            "last_accuracy": result.get("accuracy"),
            "last_samples":  result.get("n_samples"),
        })
        return result
    except Exception as e:
        _training_status["is_running"]  = False
        _training_status["last_error"]  = str(e)
        logger.error(f"[ML] Training failed: {e}")
        return {"status": "error", "message": str(e)}


async def _train() -> dict:
    """Core training logic — sync-wrapped for CPU work."""
    import asyncio
    return await asyncio.get_event_loop().run_in_executor(None, _train_sync)


def _train_sync() -> dict:
    """Synchronous training — runs in thread pool."""
    try:
        from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
        from sklearn.preprocessing import StandardScaler
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import accuracy_score, classification_report
        import numpy as np
    except ImportError:
        raise RuntimeError("scikit-learn not installed. Add scikit-learn to requirements.txt")

    # Load training data from DB
    X, y = _load_training_data()
    n_samples = len(X)

    if n_samples < MIN_SAMPLES:
        return {
            "status":    "insufficient_data",
            "n_samples": n_samples,
            "min_required": MIN_SAMPLES,
            "message":   f"Cần ít nhất {MIN_SAMPLES} labeled samples. Hiện có: {n_samples}.",
        }

    X_arr = np.array(X)
    y_arr = np.array(y)

    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        X_arr, y_arr, test_size=0.2, random_state=42, stratify=y_arr
    )

    # Scale features
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s  = scaler.transform(X_test)

    # Train RandomForest
    clf = RandomForestClassifier(
        n_estimators=100,
        max_depth=8,
        min_samples_leaf=5,
        class_weight="balanced",
        random_state=42,
    )
    clf.fit(X_train_s, y_train)

    # Evaluate
    y_pred   = clf.predict(X_test_s)
    accuracy = accuracy_score(y_test, y_pred)
    report   = classification_report(y_test, y_pred, output_dict=True)

    # Save
    os.makedirs(MODEL_DIR, exist_ok=True)
    with open(os.path.join(MODEL_DIR, "regime_classifier.pkl"), "wb") as f:
        pickle.dump(clf, f)
    with open(os.path.join(MODEL_DIR, "feature_scaler.pkl"), "wb") as f:
        pickle.dump(scaler, f)

    # Persist to model_registry DB
    _register_model(accuracy, n_samples, report)

    # Reload in-memory classifier
    try:
        from .classifier import warm_models
        warm_models()
    except Exception:
        pass

    logger.info(f"[ML] Training complete: accuracy={accuracy:.3f}, n={n_samples}")

    return {
        "status":        "ok",
        "n_samples":     n_samples,
        "n_train":       len(X_train),
        "n_test":        len(X_test),
        "accuracy":      round(accuracy, 4),
        "accuracy_pct":  f"{accuracy * 100:.1f}%",
        "report":        report,
        "model_saved":   os.path.join(MODEL_DIR, "regime_classifier.pkl"),
    }


def _load_training_data() -> tuple[list, list]:
    """Load labeled scans từ DB. Returns (features_list, labels_list)."""
    from shared.libs.database.models import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    X, y = [], []
    try:
        rows = db.execute(text("""
            SELECT features_json, label
            FROM radar_labeled_scans
            WHERE label IS NOT NULL AND features_json IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 10000
        """)).fetchall()

        for row in rows:
            try:
                features = json.loads(row.features_json) if isinstance(row.features_json, str) else row.features_json
                fv = [
                    float(features.get("adx",               20.0)),
                    float(features.get("atr_pct",            0.5)),
                    float(features.get("ema_slope",          0.0)),
                    float(features.get("volatility_ratio",   1.0)),
                    float(features.get("range_compression",  0.0)),
                    float(features.get("session_score",     50.0)),
                ]
                X.append(fv)
                y.append(row.label)
            except Exception:
                continue
    finally:
        db.close()

    return X, y


def _register_model(accuracy: float, n_samples: int, report: dict):
    """Persist model info vào model_registry."""
    from shared.libs.database.models import SessionLocal, ModelRegistry
    db = SessionLocal()
    try:
        reg = ModelRegistry(
            model_name="regime_classifier",
            version=f"v{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}",
            accuracy=accuracy,
            n_samples=n_samples,
            metrics_json=json.dumps(report),
            model_path=os.path.join(MODEL_DIR, "regime_classifier.pkl"),
            is_active=True,
        )
        # Deactivate previous versions
        db.execute(__import__("sqlalchemy").text(
            "UPDATE model_registry SET is_active = false WHERE model_name = 'regime_classifier'"
        ))
        db.add(reg)
        db.commit()
    except Exception as e:
        logger.warning(f"[ML] Model registry update failed: {e}")
        db.rollback()
    finally:
        db.close()
