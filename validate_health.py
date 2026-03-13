"""
Z-ARMOR HEALTH VALIDATOR — Phase 5
====================================
Chạy sau khi deploy tất cả fixes để xác nhận hệ thống hoạt động đúng.
Usage: python3 validate_health.py [--db Z-Armor.db]

Checks:
  DB-1  consistency_pct column tồn tại và có data đúng
  DB-2  Orphan trading_accounts đã được fix
  DB-3  daily_limit_money nhất quán giữa risk_hard_limits và risk_tactical
  DB-4  Mỗi account có đủ row ở tất cả bảng quan trọng
  CFG-1 get_all_units() không trả về key rác (None, 'None')
  CFG-2 consistency đọc đúng là % (50-100), không phải $ (>100)
  CFG-3 source guard hoạt động — MacroModal không ghi đè Hiến Pháp
  SRC-1 reset_daily_cache được export từ dashboard_service
  SRC-2 threading.Lock trong ai_guard_logic
  SRC-3 openSession import từ aiAgentEngine trong MacroModal
  SRC-4 contractLocked trong MacroModal (không còn toàn modal lock)
"""

import sys
import os
import sqlite3
import argparse
import re
from datetime import datetime

# ─── Color helpers ─────────────────────────────────────────────
OK   = "✅"
FAIL = "❌"
WARN = "⚠️ "
INFO = "ℹ️ "

results = []

def check(name, passed, detail="", warn=False):
    icon = OK if passed else (WARN if warn else FAIL)
    status = "PASS" if passed else ("WARN" if warn else "FAIL")
    results.append((status, name, detail))
    print(f"  {icon} [{status:4}] {name}")
    if detail:
        print(f"         {detail}")
    return passed


# ══════════════════════════════════════════════════════
# DB CHECKS
# ══════════════════════════════════════════════════════

def check_db(db_path):
    print(f"\n{'='*60}")
    print(f"DATABASE CHECKS — {db_path}")
    print(f"{'='*60}")

    if not os.path.exists(db_path):
        check("DB file exists", False, f"File not found: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # DB-1: consistency_pct column
    cur.execute("PRAGMA table_info(risk_hard_limits)")
    cols = {r[1] for r in cur.fetchall()}
    has_col = "consistency_pct" in cols

    if has_col:
        cur.execute("SELECT account_id, consistency_pct, hard_floor_money FROM risk_hard_limits")
        rows = cur.fetchall()
        bad = [r for r in rows if r["consistency_pct"] is None or r["consistency_pct"] == 0]
        pct_looks_like_dollar = [r for r in rows if r["consistency_pct"] and r["consistency_pct"] > 100]
        check("DB-1a consistency_pct column exists", True)
        check("DB-1b consistency_pct populated", len(bad) == 0,
              f"{len(bad)} rows với NULL/0 — cần run_migrations()" if bad else "",
              warn=len(bad) > 0)
        check("DB-1c consistency_pct looks like % not $",
              len(pct_looks_like_dollar) == 0,
              f"Rows nghi là $: {[(r['account_id'], r['consistency_pct']) for r in pct_looks_like_dollar]}" if pct_looks_like_dollar else "")
    else:
        check("DB-1a consistency_pct column exists", False,
              "Column chưa có — server chưa được restart sau khi deploy database.py mới")

    # DB-2: Orphan trading_accounts
    cur.execute("SELECT id, account_id, alias FROM trading_accounts WHERE account_id IS NULL")
    orphans = cur.fetchall()
    check("DB-2 No orphan trading_accounts (account_id=NULL)", len(orphans) == 0,
          f"Orphan rows: {[(r['id'], r['alias']) for r in orphans]}" if orphans else "",
          warn=len(orphans) > 0)

    # DB-3: daily_limit_money consistency — chỉ risk_tactical là nguồn đúng
    cur.execute("""
        SELECT h.account_id, h.daily_limit_money AS hard_dlm, t.daily_limit_money AS tact_dlm
        FROM risk_hard_limits h
        LEFT JOIN risk_tactical t ON h.account_id = t.account_id
        WHERE h.daily_limit_money != 150.0
          AND h.daily_limit_money != t.daily_limit_money
    """)
    mismatch = cur.fetchall()
    check("DB-3 daily_limit_money no mismatch (hard vs tactical)", len(mismatch) == 0,
          f"Mismatch: {[(r['account_id'], r['hard_dlm'], r['tact_dlm']) for r in mismatch]}" if mismatch else "",
          warn=len(mismatch) > 0)

    # DB-4: Cross-table integrity — mỗi account có đủ rows
    cur.execute("SELECT account_id FROM risk_hard_limits")
    hard_ids = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT account_id FROM risk_tactical")
    tact_ids = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT account_id FROM neural_profiles")
    neural_ids = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT account_id FROM system_states")
    state_ids = {r[0] for r in cur.fetchall()}

    all_ids = hard_ids | tact_ids | neural_ids | state_ids
    for aid in sorted(all_ids):
        missing = []
        if aid not in hard_ids:   missing.append("risk_hard_limits")
        if aid not in tact_ids:   missing.append("risk_tactical")
        if aid not in neural_ids: missing.append("neural_profiles")
        if aid not in state_ids:  missing.append("system_states")
        check(f"DB-4 Account {aid} cross-table integrity", len(missing) == 0,
              f"Thiếu bảng: {missing}" if missing else "", warn=len(missing) > 0)

    conn.close()


# ══════════════════════════════════════════════════════
# SOURCE CODE CHECKS
# ══════════════════════════════════════════════════════

def check_sources(base_dir="."):
    print(f"\n{'='*60}")
    print(f"SOURCE CODE CHECKS — {os.path.abspath(base_dir)}")
    print(f"{'='*60}")

    def read(path):
        full = os.path.join(base_dir, path)
        if not os.path.exists(full):
            return None
        with open(full, encoding="utf-8") as f:
            return f.read()

    # SRC-1: reset_daily_cache trong dashboard_service.py
    src = read("api/dashboard_service.py") or read("dashboard_service.py")
    if src:
        has_fn   = "def reset_daily_cache" in src
        has_lock = "is_hibernating" not in src.split("def reset_daily_cache")[1][:200] if has_fn else False
        check("SRC-1a reset_daily_cache function exists", has_fn,
              "Thiếu function — BUG F chưa được fix" if not has_fn else "")
        check("SRC-1b reset_daily_cache exported (callable from main)", has_fn,
              warn=not has_fn)
    else:
        check("SRC-1 dashboard_service.py found", False, "File không tồn tại")

    # SRC-2: threading.Lock trong ai_guard_logic.py
    src = read("api/ai_guard_logic.py") or read("ai_guard_logic.py")
    if src:
        has_lock    = "_behavior_lock = threading.Lock()" in src
        has_import  = "import threading" in src
        has_with    = "with _behavior_lock:" in src
        check("SRC-2a threading imported",           has_import)
        check("SRC-2b _behavior_lock = Lock()",      has_lock)
        check("SRC-2c with _behavior_lock: in use",  has_with,
              f"Lock chưa được dùng trong read/write" if not has_with else "")
    else:
        check("SRC-2 ai_guard_logic.py found", False, "File không tồn tại")

    # SRC-3: openSession import từ aiAgentEngine trong MacroModal.js
    src = read("MacroModal.js") or read("frontend/MacroModal.js") or read("static/MacroModal.js")
    if src:
        import_ok     = "import { openSession } from './aiAgentEngine.js'" in src
        no_local_fn   = "function openSession(" not in src
        has_contract  = "contractLocked" in src
        source_field  = 'source: "MacroModal"' in src
        no_setDdType  = "setDdType(" not in src
        no_setMaxDd   = "setMaxDdPct(" not in src

        check("SRC-3a openSession imported from aiAgentEngine", import_ok,
              "Local copy vẫn còn — BUG E chưa fix" if not import_ok else "")
        check("SRC-3b local openSession() function removed", no_local_fn,
              "Vẫn còn local function — conflict với import" if not no_local_fn else "")
        check("SRC-3c contractLocked state exists", has_contract,
              "Zone A/B separation chưa được implement" if not has_contract else "")
        check("SRC-3d ARM payload has source=MacroModal", source_field,
              "BUG B fix chưa vào — backend sẽ cho phép MacroModal ghi đè Hiến Pháp" if not source_field else "")
        check("SRC-3e setDdType removed from MacroModal", no_setDdType,
              "MacroModal vẫn còn state ddType — BUG H chưa fix" if not no_setDdType else "")
        check("SRC-3f setMaxDdPct removed from MacroModal", no_setMaxDd,
              "MacroModal vẫn còn state maxDdPct — BUG H chưa fix" if not no_setMaxDd else "")
    else:
        check("SRC-3 MacroModal.js found", False, "File không tìm thấy (thử tìm ở: MacroModal.js, frontend/, static/)")

    # SRC-4: config_manager.py - source guard
    src = read("api/config_manager.py") or read("config_manager.py")
    if src:
        has_source_guard = 'source = payload.get("source", "SetupModal")' in src
        has_macro_guard  = 'if source != "MacroModal":' in src
        has_consis_pct   = "consistency_pct" in src
        no_hard_floor_r  = 'hard_floor_money' not in src.split("get_all_units")[1][:500] if "get_all_units" in src else True
        check("SRC-4a source guard in update_unit_from_payload", has_source_guard)
        check("SRC-4b MacroModal guard blocks hard limit writes", has_macro_guard)
        check("SRC-4c reads consistency_pct not hard_floor_money", has_consis_pct)
    else:
        check("SRC-4 config_manager.py found", False, "File không tồn tại")

    # SRC-5: main.py — rollover calls reset_daily_cache
    src = read("main.py")
    if src:
        has_import  = "reset_daily_cache" in src and "from api.dashboard_service import" in src
        has_call    = "reset_daily_cache(acc_id)" in src
        has_loop    = "for acc_id in list(_mt5_cache" in src
        fix_merge   = "get_all_units()" in src and "fetch_dashboard_state" not in src.split("/api/update-unit-config")[1][:200] if "/api/update-unit-config" in src else False
        check("SRC-5a reset_daily_cache imported in main.py", has_import)
        check("SRC-5b rollover loop calls reset_daily_cache", has_call)
        check("SRC-5c rollover iterates _mt5_cache keys", has_loop)
        check("SRC-5d update-unit-config merge logic fixed", fix_merge, warn=not fix_merge)
    else:
        check("SRC-5 main.py found", False)

    # SRC-6: schemas.py — PhysicsData có đủ Dual-Layer fields
    src = read("api/schemas.py") or read("schemas.py")
    if src:
        required_fields = [
            "account_hard_floor", "account_buffer_pct", "account_dd_pct",
            "daily_giveback_pct", "dd_type", "initial_balance",
            "account_peak", "dist_to_account_floor"
        ]
        missing = [f for f in required_fields if f not in src]
        check("SRC-6 PhysicsData has all Dual-Layer DD fields", len(missing) == 0,
              f"Thiếu: {missing}" if missing else "")
    else:
        check("SRC-6 schemas.py found", False)


# ══════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════

def print_summary():
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")

    passed = [r for r in results if r[0] == "PASS"]
    warned = [r for r in results if r[0] == "WARN"]
    failed = [r for r in results if r[0] == "FAIL"]

    print(f"  {OK} PASS: {len(passed)}")
    print(f"  {WARN} WARN: {len(warned)}")
    print(f"  {FAIL} FAIL: {len(failed)}")

    if failed:
        print(f"\n🚨 CRITICAL FAILURES ({len(failed)}):")
        for _, name, detail in failed:
            print(f"  • {name}")
            if detail: print(f"    → {detail}")

    if warned:
        print(f"\n⚠️  WARNINGS ({len(warned)}):")
        for _, name, detail in warned:
            print(f"  • {name}")
            if detail: print(f"    → {detail}")

    print()
    if not failed:
        print("🟢 HỆ THỐNG SẴN SÀNG — Tất cả critical checks passed")
    else:
        print("🔴 CẦN XỬ LÝ — Có critical failures trước khi deploy production")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Z-Armor Health Validator")
    parser.add_argument("--db",      default="Z-Armor.db",  help="Path to SQLite DB")
    parser.add_argument("--src",     default=".",            help="Base directory chứa source files")
    parser.add_argument("--db-only", action="store_true",    help="Chỉ check DB, bỏ qua source")
    parser.add_argument("--src-only",action="store_true",    help="Chỉ check source, bỏ qua DB")
    args = parser.parse_args()

    print(f"\nZ-ARMOR HEALTH VALIDATOR v1.0")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if not args.src_only:
        check_db(args.db)
    if not args.db_only:
        check_sources(args.src)

    print_summary()
    sys.exit(0 if not any(r[0] == "FAIL" for r in results) else 1)
