"""
app/services/classifier.py
============================
Regime classifier — extract từ ml/classifier.py monolith.
Sử dụng scikit-learn RandomForestClassifier.
Feature vector: ADX, ATR%, EMA_slope, volatility_ratio, range_compression, session_score.
Labels: STRONG_TREND, TRENDING, NEUTRAL, MEAN_REVERSION, VOLATILE, BREAKOUT_WATCH
"""

import os
import json
import logging
import pickle
from datetime import datetime, timezone
from typing import Optional

import numpy as np

logger = logging.getLogger("zarmor.ml.classifier")

MODEL_DIR   = os.getenv("MODEL_DIR", "/app/models")
MODEL_FILE  = os.path.join(MODEL_DIR, "regime_classifier.pkl")
SCALER_FILE = os.path.join(MODEL_DIR, "feature_scaler.pkl")

FEATURE_NAMES = ["adx", "atr_pct", "ema_slope", "volatility_ratio", "range_compression", "session_score"]
LABELS        = ["STRONG_TREND", "TRENDING", "NEUTRAL", "MEAN_REVERSION", "VOLATILE", "BREAKOUT_WATCH"]

# In-memory model store
_model  = None
_scaler = None
_model_meta = {}


def warm_models():
    """Load model + scaler từ disk on startup. Fallback to heuristic if not found."""
    global _model, _scaler, _model_meta
    os.makedirs(MODEL_DIR, exist_ok=True)

    if os.path.exists(MODEL_FILE):
        try:
            with open(MODEL_FILE, "rb") as f:
                _model = pickle.load(f)
            _model_meta["loaded_at"] = datetime.now(timezone.utc).isoformat()
            _model_meta["source"]    = "disk"
            logger.info(f"[ML] Classifier loaded from {MODEL_FILE}")
        except Exception as e:
            logger.warning(f"[ML] Failed to load model: {e}")
            _model = None

    if os.path.exists(SCALER_FILE):
        try:
            with open(SCALER_FILE, "rb") as f:
                _scaler = pickle.load(f)
        except Exception as e:
            logger.warning(f"[ML] Failed to load scaler: {e}")

    if _model is None:
        logger.info("[ML] No trained model found — using heuristic fallback")
        _model_meta["source"] = "heuristic"


def classify(features: dict) -> dict:
    """
    Classify regime từ feature vector.
    Returns: {label, confidence, probabilities, source}
    """
    fv = _build_feature_vector(features)

    if _model is not None and _scaler is not None:
        return _ml_classify(fv)
    else:
        return _heuristic_classify(features)


def predict_score(features: dict) -> dict:
    """
    Predict radar score (0-100) từ feature vector.
    Returns: {score, confidence, source}
    """
    adx   = features.get("adx", 20.0)
    atr   = features.get("atr_pct", 0.5)
    slope = features.get("ema_slope", 0.0)
    vr    = features.get("volatility_ratio", 1.0)
    sess  = features.get("session_score", 50.0)

    # Heuristic score (mirrors Layer 2 logic)
    adx_s   = min(100.0, max(0.0, (adx - 10) / 40 * 100))
    atr_s   = 70.0 if 0.7 <= vr <= 1.5 else max(20.0, 60.0 * vr / 1.5)
    slope_s = min(100.0, 50 + slope * 15)
    sess_s  = sess

    score = int(adx_s * 0.35 + atr_s * 0.20 + slope_s * 0.30 + sess_s * 0.15)
    score = max(0, min(100, score))

    return {"score": score, "confidence": "72%", "source": "heuristic"}


def _build_feature_vector(features: dict) -> np.ndarray:
    return np.array([
        features.get("adx",               20.0),
        features.get("atr_pct",            0.5),
        features.get("ema_slope",          0.0),
        features.get("volatility_ratio",   1.0),
        features.get("range_compression",  0.0),
        features.get("session_score",     50.0),
    ]).reshape(1, -1)


def _ml_classify(fv: np.ndarray) -> dict:
    try:
        fv_scaled = _scaler.transform(fv)
        pred_idx  = _model.predict(fv_scaled)[0]
        proba     = _model.predict_proba(fv_scaled)[0]
        label     = LABELS[pred_idx] if isinstance(pred_idx, int) else str(pred_idx)
        confidence = f"{int(max(proba) * 100)}%"
        return {
            "label":         label,
            "confidence":    confidence,
            "probabilities": {LABELS[i]: round(float(p), 3) for i, p in enumerate(proba)},
            "source":        "ml_model",
        }
    except Exception as e:
        logger.error(f"[ML] Classifier error: {e}")
        return _heuristic_classify({})


def _heuristic_classify(features: dict) -> dict:
    """Rule-based fallback khi chưa có trained model."""
    adx  = features.get("adx", 20.0)
    atr  = features.get("atr_pct", 0.5)
    vr   = features.get("volatility_ratio", 1.0)
    rc   = features.get("range_compression", 0.0)

    if adx > 35 and vr < 1.5:           label = "STRONG_TREND"
    elif adx > 25 and vr < 2.0:         label = "TRENDING"
    elif vr > 2.0 or atr > 1.5:         label = "VOLATILE"
    elif rc > 0.4 and adx < 20:         label = "BREAKOUT_WATCH"
    elif adx < 20 and vr < 0.9:         label = "MEAN_REVERSION"
    else:                                label = "NEUTRAL"

    return {
        "label":      label,
        "confidence": "60%",
        "source":     "heuristic",
        "probabilities": {lb: (0.60 if lb == label else 0.08) for lb in LABELS},
    }


def get_model_status() -> dict:
    return {
        "model_loaded":     _model is not None,
        "scaler_loaded":    _scaler is not None,
        "model_source":     _model_meta.get("source", "none"),
        "loaded_at":        _model_meta.get("loaded_at"),
        "feature_names":    FEATURE_NAMES,
        "labels":           LABELS,
        "model_dir":        MODEL_DIR,
        "model_file_exists":os.path.exists(MODEL_FILE),
    }


def list_models() -> list:
    """List model files trong MODEL_DIR."""
    if not os.path.exists(MODEL_DIR):
        return []
    files = []
    for f in os.listdir(MODEL_DIR):
        if f.endswith(".pkl"):
            path = os.path.join(MODEL_DIR, f)
            files.append({
                "name":         f,
                "path":         path,
                "size_kb":      round(os.path.getsize(path) / 1024, 1),
                "is_active":    f == "regime_classifier.pkl",
            })
    return files
