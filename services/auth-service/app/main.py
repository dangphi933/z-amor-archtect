"""
auth-service/app/main.py
=========================
Service: Authentication — đăng nhập, JWT, OTP magic link, license bind.

Extract từ monolith:
  - auth.py           → core JWT + OTP logic
  - api/auth_router.py → HTTP endpoints /auth/*
  - api/identity_router.py → /user/me, /user/bind-license (moved here)

Endpoints:
  POST /auth/magic-request    — email → OTP 6 số
  POST /auth/magic-verify     — email + OTP → JWT + refresh
  POST /auth/login            — license_key → JWT (backward-compat)
  POST /auth/logout           — revoke session
  GET  /auth/me               — current user info
  POST /auth/refresh          — rotate refresh token
  POST /auth/bind-license     — bind license key to MT5 account
  GET  /health
"""

import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from .routers.auth_router import router as auth_router
from .routers.identity_router import router as identity_router
from .core.database import engine, Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Base.metadata.create_all(bind=engine)
    print("[AUTH-SERVICE] Started — tables ensured", flush=True)
    yield
    # Shutdown
    print("[AUTH-SERVICE] Shutting down", flush=True)


app = FastAPI(
    title="Z-Armor Auth Service",
    version="2.0.0",
    description="Authentication, JWT, OTP, License bind",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").strip("[]\"").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router,     prefix="/auth")
app.include_router(identity_router, prefix="/auth")


@app.get("/health")
def health():
    return {"status": "ok", "service": "auth-service"}
