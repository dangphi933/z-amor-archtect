"""
engine-service/app/main.py
============================
Service: EA Engine — heartbeat, handshake, risk-check, trade events.

Extract từ monolith:
  - api/ea_router.py          → tất cả /ea/* endpoints
  - api/config_manager.py     → unit config management
  - api/dashboard_service.py  → in-memory cache + state

Endpoints:
  POST /ea/handshake    — EA xác thực lần đầu
  POST /ea/heartbeat    — EA ping mỗi 60s
  POST /ea/risk-check   — tính DD, trả KILL nếu vi phạm
  POST /ea/trade-event  — báo cáo lệnh mở/đóng
  GET  /ea/config/{id}  — lấy config mới nhất
  POST /ea/revoke       — admin revoke session
  GET  /health
"""

import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from .routers.ea_router import router as ea_router
from .core.database import engine, Base
from .consumers.event_persister import start_persister_thread

_persister_shutdown = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _persister_shutdown
    Base.metadata.create_all(bind=engine)
    # Start event_persister background thread (FIX 2)
    _persister_shutdown = start_persister_thread()
    print("[ENGINE-SERVICE] Started + event_persister running", flush=True)
    yield
    if _persister_shutdown:
        _persister_shutdown.set()
    print("[ENGINE-SERVICE] Shutting down", flush=True)


app = FastAPI(
    title="Z-Armor Engine Service",
    version="2.0.0",
    description="EA Engine — heartbeat, risk management, trade events",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").strip("[]\"").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ea_router, prefix="/ea")


@app.get("/health")
def health():
    return {"status": "ok", "service": "engine-service"}
