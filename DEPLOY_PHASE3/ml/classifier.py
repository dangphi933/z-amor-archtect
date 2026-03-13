"""
ml/classifier.py — Phase 3 XGBoost Regime Classifier
======================================================
Thay thế rule-based regime classification trong radar/engine.py
bằng ML model được train từ labeled_scans.

Pipeline:
  labeled_scans → features → XGBoost → regime_probability
  
Features (10 total):
  - trend_strength, volatility_quality, session_bias, market_structure (từ engine)
  - adx_live, rsi_live, atr_pct_live (live OHLCV — None → imputed)
  - utc_hour, utc_dow (temporal)
  - score (composite score từ engine)

Target: label ∈ {PROFITABLE_TREND, FALSE_SIGNAL, RANGE_BOUND}

Model storage: models/regime_classifier_{version}.pkl + model_registry table

Fallback: nếu không có model → dùng rule-based từ engine.py (luôn hoạt động)
"""

import os
import json
import pickle
import logging
import hashlib
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from database import SessionLocal

logger = logging.getLogger("zarmor.ml.classifier")

MODEL_DIR = os.path.join(
    os.environ.get("MODEL_DIR", "models"),
)
os.makedirs(MODEL_DIR, exist_ok=True)

# Labels
LABELS     = ["PROFITABLE_TREND", "FALSE_SIGNAL", "RANGE_BOUND"]
LABEL_TO_I = {l: i for i, l in enumerate(LABELS)}
I_TO_LABEL = {i: l for i, l in enumerate(LABELS)}

# Feature columns — thứ tự phải khớp khi train và predict
FEATURE_COLS = [
    "trend_strength", "volatility_quality", "session_bias", "market_structure",
    "adx_live", "rsi_live", "atr_pct_live",
    "utc_hour", "utc_dow", "score",
]

# Default imputation cho missing live features
FEATURE_DEFAULTS = {
    "adx_live":    22.0,   # neutral ADX
    "rsi_live":    50.0,   # neutral RSI
    "atr_pct_live": 0.5,   # typical ATR%
}

# In-memory model cache
_model_cache: dict = {"model": None, "version": None, "loaded_at": None}


# ── Feature Extraction ────────────────────────────────────────────────────────

def extract_features(row: dict) -> list:
    """
    Chuyển một scan record → feature vector [10 floats].
    None values → imputed với defaults.
    """
    vec = []
    for col in FEATURE_COLS:
        val = row.get(col)
        if val is None:
            val = FEATURE_DEFAULTS.get(col, 50.0)
        vec.append(float(val))
    return vec


def load_training_data(min_confidence: float = 0.6, min_samples: int = 30) -> Optional[tuple]:
    """
    Load labeled_scans từ DB → (X, y) arrays.
    Returns None nếu không đủ data.
    """
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT trend_strength, volatility_quality, session_bias, market_structure,
                   adx_live, rsi_live, atr_pct_live,
                   utc_hour, utc_dow, score, label, label_confidence
            FROM labeled_scans
            WHERE label_confidence >= :min_conf
              AND label IN ('PROFITABLE_TREND', 'FALSE_SIGNAL', 'RANGE_BOUND')
            ORDER BY labeled_at DESC
        """), {"min_conf": min_confidence}).fetchall()

        if len(rows) < min_samples:
            logger.warning(f"[CLASSIFIER] Only {len(rows)} samples — need {min_samples} minimum")
            return None

        X = [extract_features(dict(r)) for r in rows]
        y = [LABEL_TO_I[r["label"]] for r in rows]

        logger.info(f"[CLASSIFIER] Loaded {len(X)} training samples")
        label_counts = {LABELS[i]: y.count(i) for i in range(len(LABELS))}
        logger.info(f"[CLASSIFIER] Label distribution: {label_counts}")

        return X, y, label_counts

    except Exception as e:
        logger.error(f"[CLASSIFIER] load_training_data error: {e}")
        return None
    finally:
        db.close()


# ── Training ──────────────────────────────────────────────────────────────────

def train(min_confidence: float = 0.6, min_samples: int = 30) -> Optional[dict]:
    """
    Train XGBoost classifier trên labeled_scans.
    Lưu model vào disk + ghi vào model_registry.
    Returns model metadata dict, hoặc None nếu fail.
    """
    try:
        import xgboost as xgb
        from sklearn.model_selection import cross_val_score
        from sklearn.preprocessing import LabelEncoder
        import numpy as np
    except ImportError as e:
        logger.error(f"[CLASSIFIER] Missing dependency: {e}")
        logger.error("[CLASSIFIER] Run: pip install xgboost scikit-learn numpy")
        return None

    data = load_training_data(min_confidence, min_samples)
    if data is None:
        return None

    X, y, label_counts = data
    X_arr = np.array(X, dtype=np.float32)
    y_arr = np.array(y, dtype=np.int32)

    # XGBoost multiclass
    model = xgb.XGBClassifier(
        n_estimators     = 200,
        max_depth        = 4,
        learning_rate    = 0.1,
        subsample        = 0.8,
        colsample_bytree = 0.8,
        use_label_encoder= False,
        eval_metric      = "mlogloss",
        random_state     = 42,
        n_jobs           = -1,
    )

    # Cross-validation để đánh giá (không leak test data)
    cv_scores = cross_val_score(model, X_arr, y_arr, cv=min(5, len(X)//10 + 1), scoring="accuracy")
    cv_mean   = float(cv_scores.mean())
    cv_std    = float(cv_scores.std())

    # Train trên toàn bộ data
    model.fit(X_arr, y_arr)

    # Feature importance
    fi = dict(zip(FEATURE_COLS, [float(v) for v in model.feature_importances_]))

    # Tạo version string
    version = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    model_path = os.path.join(MODEL_DIR, f"regime_classifier_{version}.pkl")

    # Save model
    model_data = {
        "model":         model,
        "version":       version,
        "feature_cols":  FEATURE_COLS,
        "label_map":     I_TO_LABEL,
        "cv_accuracy":   cv_mean,
        "cv_std":        cv_std,
        "n_samples":     len(X),
        "label_counts":  label_counts,
        "feature_importance": fi,
        "trained_at":    datetime.now(timezone.utc).isoformat(),
    }
    with open(model_path, "wb") as f:
        pickle.dump(model_data, f)

    logger.info(
        f"[CLASSIFIER] Trained v{version} — "
        f"CV accuracy: {cv_mean:.3f} ± {cv_std:.3f} "
        f"n={len(X)} samples"
    )
    logger.info(f"[CLASSIFIER] Feature importance: {fi}")

    # Register in DB
    _register_model(version, model_path, cv_mean, cv_std, len(X), label_counts, fi)

    # Update cache
    _model_cache["model"]     = model_data
    _model_cache["version"]   = version
    _model_cache["loaded_at"] = datetime.now(timezone.utc)

    return {
        "version":       version,
        "cv_accuracy":   round(cv_mean, 4),
        "cv_std":        round(cv_std, 4),
        "n_samples":     len(X),
        "label_counts":  label_counts,
        "feature_importance": {k: round(v, 4) for k, v in fi.items()},
        "model_path":    model_path,
    }


def _register_model(version: str, path: str, cv_acc: float, cv_std: float,
                    n_samples: int, label_counts: dict, fi: dict):
    """Ghi model metadata vào model_registry table."""
    db = SessionLocal()
    try:
        db.execute(text("""
            INSERT INTO model_registry
              (version, model_path, cv_accuracy, cv_std, n_samples,
               label_counts, feature_importance, is_active, trained_at)
            VALUES
              (:version, :path, :cv_acc, :cv_std, :n_samples,
               cast(:label_counts as jsonb), cast(:fi as jsonb), FALSE, NOW())
        """), {
            "version":      version,
            "path":         path,
            "cv_acc":       cv_acc,
            "cv_std":       cv_std,
            "n_samples":    n_samples,
            "label_counts": json.dumps(label_counts),
            "fi":           json.dumps(fi),
        })
        db.commit()
        logger.info(f"[CLASSIFIER] Registered model v{version} in model_registry")
    except Exception as e:
        logger.warning(f"[CLASSIFIER] Registry write failed: {e}")
        db.rollback()
    finally:
        db.close()


# ── Model Loading ─────────────────────────────────────────────────────────────

def load_active_model() -> Optional[dict]:
    """Load active model từ DB registry → disk pkl."""
    # Check cache còn valid không (1h TTL)
    if _model_cache["model"] is not None:
        age = (datetime.now(timezone.utc) - _model_cache["loaded_at"]).total_seconds()
        if age < 3600:
            return _model_cache["model"]

    db = SessionLocal()
    try:
        row = db.execute(text("""
            SELECT version, model_path FROM model_registry
            WHERE is_active = TRUE
            ORDER BY trained_at DESC LIMIT 1
        """)).fetchone()

        if not row:
            # Fallback: lấy model mới nhất dù chưa active
            row = db.execute(text("""
                SELECT version, model_path FROM model_registry
                ORDER BY trained_at DESC LIMIT 1
            """)).fetchone()

        if not row:
            return None

        path = row["model_path"]
        if not os.path.exists(path):
            logger.warning(f"[CLASSIFIER] Model file not found: {path}")
            return None

        with open(path, "rb") as f:
            model_data = pickle.load(f)

        _model_cache["model"]     = model_data
        _model_cache["version"]   = row["version"]
        _model_cache["loaded_at"] = datetime.now(timezone.utc)

        logger.info(f"[CLASSIFIER] Loaded model v{row['version']}")
        return model_data

    except Exception as e:
        logger.error(f"[CLASSIFIER] load_active_model error: {e}")
        return None
    finally:
        db.close()


def activate_model(version: str) -> bool:
    """Promote một model version thành active (dùng sau khi review)."""
    db = SessionLocal()
    try:
        db.execute(text("UPDATE model_registry SET is_active = FALSE"))
        result = db.execute(text("""
            UPDATE model_registry SET is_active = TRUE
            WHERE version = :version
        """), {"version": version})
        db.commit()
        # Invalidate cache
        _model_cache["model"] = None
        logger.info(f"[CLASSIFIER] Activated model v{version}")
        return result.rowcount > 0
    except Exception as e:
        db.rollback()
        logger.error(f"[CLASSIFIER] activate error: {e}")
        return False
    finally:
        db.close()


# ── Prediction ────────────────────────────────────────────────────────────────

def predict_regime(features: dict) -> Optional[dict]:
    """
    Predict regime từ feature dict.
    features = output của radar/engine.py breakdown + live indicators

    Returns:
      {
        "regime":      "PROFITABLE_TREND",
        "probabilities": {"PROFITABLE_TREND": 0.72, "FALSE_SIGNAL": 0.18, "RANGE_BOUND": 0.10},
        "confidence":  "HIGH",   # ≥0.70 = HIGH, ≥0.55 = MEDIUM, else LOW
        "model_version": "20260309_1030",
        "source": "ml"
      }
    Returns None nếu không có model → caller dùng rule-based fallback.
    """
    try:
        import numpy as np
    except ImportError:
        return None

    model_data = load_active_model()
    if model_data is None:
        return None

    model = model_data["model"]
    vec   = extract_features(features)
    X     = np.array([vec], dtype=np.float32)

    proba = model.predict_proba(X)[0]
    pred_idx  = int(proba.argmax())
    pred_label = I_TO_LABEL[pred_idx]
    max_prob   = float(proba[pred_idx])

    # Confidence tier
    confidence = "HIGH" if max_prob >= 0.70 else "MEDIUM" if max_prob >= 0.55 else "LOW"

    return {
        "regime":        pred_label,
        "probabilities": {LABELS[i]: round(float(p), 4) for i, p in enumerate(proba)},
        "confidence":    confidence,
        "model_version": model_data.get("version", "unknown"),
        "source":        "ml",
    }


def is_model_available() -> bool:
    """Quick check — có model active không."""
    return load_active_model() is not None
