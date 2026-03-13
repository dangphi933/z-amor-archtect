# -*- coding: utf-8 -*-
"""
ZARMOR_START.py — Fixed for Windows cp1252 UnicodeEncodeError
"""
import sys
import os
import subprocess

# FIX: Force UTF-8 stdout/stderr trước mọi thứ — tránh UnicodeEncodeError trên Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Set env PYTHONIOENCODING trước khi import bất kỳ module nào
os.environ['PYTHONIOENCODING'] = 'utf-8'

# Safe print wrapper — không crash dù terminal không hiểu Unicode
def safe_print(text):
    try:
        print(text, flush=True)
    except (UnicodeEncodeError, UnicodeDecodeError):
        print(text.encode('ascii', errors='replace').decode('ascii'), flush=True)

safe_print("\n" + "="*50)
safe_print("   Z-ARMOR CLOUD - SMART START")
safe_print("="*50)

# Check files
required = ['main.py', 'database.py', 'schemas.py']
safe_print("\n[1/5] Checking required files...")
for f in required:
    if os.path.exists(f):
        safe_print(f"  OK  {f}")
    else:
        safe_print(f"  MISSING: {f}")

safe_print("\n[2/5] Checking Python version...")
safe_print(f"  Python {sys.version}")

safe_print("\n[3/5] Checking dependencies...")
try:
    import fastapi, uvicorn, sqlalchemy
    safe_print("  OK fastapi, uvicorn, sqlalchemy")
except ImportError as e:
    safe_print(f"  MISSING: {e}")
    safe_print("  Run: pip install -r requirements.txt")

safe_print("\n[4/5] Checking database connection...")
try:
    from database import engine
    with engine.connect() as conn:
        safe_print("  OK PostgreSQL connected")
except Exception as e:
    safe_print(f"  WARN: DB check failed: {str(e)[:80]}")

safe_print("\n[5/5] Starting Z-Armor Cloud server...")
safe_print("  Host: 0.0.0.0:8000")
safe_print("  Workers: 1 (single-process for Windows)")
safe_print("="*50 + "\n")

# Start uvicorn
import uvicorn
uvicorn.run(
    "main:app",
    host="0.0.0.0",
    port=8000,
    reload=False,
    log_level="info",
    access_log=True,
)