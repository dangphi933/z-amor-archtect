"""
app/routers/ml_router.py
==========================
ML endpoints — extract từ ml/router.py monolith.
"""

import asyncio
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Dict

from ..services.classifier import classify, predict_score, get_model_status, list_models
from ..services.trainer import run_training_job, get_training_status
from ..core.database import SessionLocal, NeuralProfile
from shared.libs.security.jwt_utils import require_jwt

router = APIRouter(tags=["ML"])


class ClassifyRequest(BaseModel):
    features: Dict[str, float]

class PredictScoreRequest(BaseModel):
    features: Dict[str, float]

class NeuralProfileUpdate(BaseModel):
    trader_archetype:    Optional[str]   = None
    historical_win_rate: Optional[float] = None
    historical_rr:       Optional[float] = None
    optimization_bias:   Optional[str]   = None
    notes:               Optional[str]   = None


@router.post("/classify")
async def ml_classify(req: ClassifyRequest):
    """Classify market regime từ feature vector."""
    result = classify(req.features)
    return {"status": "ok", **result}


@router.post("/predict-score")
async def ml_predict_score(req: PredictScoreRequest):
    """Predict radar score (0-100) từ feature vector."""
    result = predict_score(req.features)
    return {"status": "ok", **result}


@router.get("/models")
def ml_list_models():
    """Danh sách models trong MODEL_DIR."""
    return {"models": list_models(), **get_model_status()}


@router.get("/models/status")
def ml_model_status():
    """Current active model status."""
    return get_model_status()


@router.post("/train")
async def ml_train(background_tasks: BackgroundTasks):
    """
    Trigger training job (async background).
    Returns job_id immediately, training runs in background.
    """
    status = get_training_status()
    if status["is_running"]:
        raise HTTPException(409, "Training đang chạy. Theo dõi tại GET /ml/train/status.")

    background_tasks.add_task(_run_training_background)
    return {
        "status":  "accepted",
        "message": "Training job đã được enqueue. Kiểm tra GET /ml/train/status.",
    }


@router.get("/train/status")
def ml_train_status():
    """Training job status."""
    return get_training_status()


async def _run_training_background():
    result = await run_training_job(triggered_by="api")
    if result.get("status") == "ok":
        import logging
        logging.getLogger("zarmor.ml").info(
            f"[ML] Training complete: accuracy={result.get('accuracy_pct')}, n={result.get('n_samples')}"
        )


@router.get("/neural-profile/{account_id}")
async def get_neural_profile(account_id: str):
    """NeuralProfile của 1 trading account."""
    db = SessionLocal()
    try:
        np_ = db.query(NeuralProfile).filter(NeuralProfile.account_id == account_id).first()
        if not np_:
            # Return defaults
            return {
                "account_id":          account_id,
                "trader_archetype":    "SNIPER",
                "historical_win_rate": 40.0,
                "historical_rr":       1.5,
                "optimization_bias":   "HALF_KELLY",
                "is_default":          True,
            }
        return {
            "account_id":          np_.account_id,
            "trader_archetype":    np_.trader_archetype,
            "historical_win_rate": np_.historical_win_rate,
            "historical_rr":       np_.historical_rr,
            "optimization_bias":   np_.optimization_bias,
            "notes":               np_.notes,
            "updated_at":          np_.updated_at.isoformat() if np_.updated_at else None,
            "is_default":          False,
        }
    finally:
        db.close()


@router.post("/neural-profile/{account_id}")
async def update_neural_profile(account_id: str, req: NeuralProfileUpdate, payload: dict = require_jwt):
    """Update NeuralProfile — admin or owner only."""
    db = SessionLocal()
    try:
        np_ = db.query(NeuralProfile).filter(NeuralProfile.account_id == account_id).first()
        if not np_:
            np_ = NeuralProfile(account_id=account_id)
            db.add(np_)

        if req.trader_archetype    is not None: np_.trader_archetype    = req.trader_archetype
        if req.historical_win_rate is not None: np_.historical_win_rate = req.historical_win_rate
        if req.historical_rr       is not None: np_.historical_rr       = req.historical_rr
        if req.optimization_bias   is not None: np_.optimization_bias   = req.optimization_bias
        if req.notes               is not None: np_.notes               = req.notes
        db.commit()
        return {"status": "ok", "account_id": account_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()
