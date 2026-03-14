"""
user-service/app/main.py
==========================
Service: User Portal — billing, profile, strategy, compliance.

Extract từ monolith:
  - api/billing_router.py    → /billing/*
  - api/strategy_router.py   → /strategy/*
  - api/compliance_router.py → /compliance/*
  - api/growth_router.py     → /user/growth/*
  - remarketing_scheduler.py → background job

Endpoints:
  GET  /user/profile            — user profile + license summary
  GET  /billing/portal          — billing overview
  GET  /billing/invoices        — invoice history
  POST /billing/upgrade         — request upgrade
  POST /billing/cancel          — cancel flow
  GET  /strategy/presets        — danh sách strategy presets
  GET  /strategy/active         — strategy đang active của license
  POST /strategy/select         — chọn strategy
  GET  /compliance/audit-log    — audit history
  GET  /compliance/data-export  — GDPR export
  GET  /health
"""

import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from .routers.user_router     import router as user_router
from .routers.billing_router  import router as billing_router
from .routers.strategy_router import router as strategy_router
from .routers.compliance_router import router as compliance_router
from .core.database import engine, Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    print("[USER-SERVICE] Started", flush=True)
    yield
    print("[USER-SERVICE] Shutting down", flush=True)


app = FastAPI(
    title="Z-Armor User Service",
    version="2.0.0",
    description="User portal — billing, strategy, compliance",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").strip("[]\"").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(user_router,       prefix="/user")
app.include_router(billing_router,    prefix="/billing")
app.include_router(strategy_router,   prefix="/strategy")
app.include_router(compliance_router, prefix="/compliance")


@app.get("/health")
def health():
    return {"status": "ok", "service": "user-service"}
