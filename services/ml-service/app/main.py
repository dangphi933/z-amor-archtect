"""
ml-service/app/main.py
========================
Service: ML Intelligence — classifier, trainer, neural profile manager.

Extract từ monolith:
  - ml/classifier.py  → regime classification
  - ml/trainer.py     → model training pipeline
  - ml/router.py      → /ml/* endpoints

Endpoints:
  POST /ml/classify             — classify current regime from features
  POST /ml/predict-score        — predict radar score from feature vector
  GET  /ml/models               — list available models
  GET  /ml/model/{name}/status  — model status, metrics
  POST /ml/train                — trigger training job (async)
  GET  /ml/neural-profile/{id}  — NeuralProfile for 1 account
  POST /ml/neural-profile/{id}  — update NeuralProfile params
  GET  /health
"""

import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from .routers.ml_router import router as ml_router
from .core.database import engine, Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    # Load models into memory
    try:
        from .services.classifier import warm_models
        warm_models()
    except Exception as e:
        print(f"[ML-SERVICE] Model warm warning: {e}", flush=True)
    print("[ML-SERVICE] Started", flush=True)
    yield
    print("[ML-SERVICE] Shutting down", flush=True)


app = FastAPI(
    title="Z-Armor ML Service",
    version="2.0.0",
    description="ML Intelligence — regime classifier, neural profile manager",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").strip("[]\"").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ml_router, prefix="/ml")


@app.get("/health")
def health():
    return {"status": "ok", "service": "ml-service"}
