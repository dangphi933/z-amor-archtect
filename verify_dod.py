#!/usr/bin/env python3
"""
scripts/verify_dod.py
=====================
Kiểm tra tất cả 10 điều kiện Definition of Done của Part 1.

Chạy: python3 scripts/verify_dod.py

Exit 0 = tất cả pass | Exit 1 = có item fail
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "

results = []


def check(label: str, fn) -> bool:
    try:
        ok, detail = fn()
        icon = PASS if ok else FAIL
        print(f"  {icon} {label}")
        if detail:
            for line in detail.splitlines():
                print(f"      {line}")
        results.append(ok)
        return ok
    except Exception as e:
        print(f"  {FAIL} {label}")
        print(f"      Error: {e}")
        results.append(False)
        return False


def run(cmd, cwd=ROOT):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


print("\n" + "="*60)
print("Z-ARMOR PART 1 — DEFINITION OF DONE VERIFICATION")
print("="*60 + "\n")

# DoD 1: Không còn fix/hotfix/patch_main files
def dod1():
    code, out, _ = run("git ls-files | grep -E 'fix_|hotfix|patch_main' | wc -l")
    count = int(out.strip()) if out.strip().isdigit() else -1
    if count == 0:
        return True, None
    code2, files, _ = run("git ls-files | grep -E 'fix_|hotfix|patch_main'")
    return False, f"{count} files còn lại:\n{files}"

check("DoD 1: git ls-files | grep fix_|hotfix|patch_main → 0 files", dod1)

# DoD 2: Không còn .bak files
def dod2():
    code, out, _ = run("git ls-files | grep -E '\\.bak|\\.backup' | wc -l")
    count = int(out.strip()) if out.strip().isdigit() else -1
    return count == 0, f"{count} bak files" if count != 0 else None

check("DoD 2: Không còn .bak/.backup files", dod2)

# DoD 3: Không còn hardcoded IPs
def dod3():
    code, out, _ = run("grep -rn '47\\.129\\.' --include='*.py' --include='*.js' --include='*.html' . | grep -v .git | grep -v test_")
    if out:
        return False, f"Hardcoded IPs:\n{out[:500]}"
    return True, None

check("DoD 3: grep 47.129. → 0 matches", dod3)

# DoD 4: main.py import sạch
def dod4():
    code, out, err = run("python3 -c 'from main import app; print(\"OK\")'")
    if code == 0 and "OK" in out:
        return True, None
    return False, f"Error: {err[:300]}"

check("DoD 4: python3 -c 'from main import app' → no errors", dod4)

# DoD 5: /health endpoint tồn tại trong main.py
def dod5():
    content = (ROOT / "main.py").read_text(errors="replace") if (ROOT / "main.py").exists() else ""
    has_health = "@app.get(\"/health\")" in content or "@app.get('/health')" in content
    has_checks = "checks[" in content or 'checks["database"]' in content
    if has_health and has_checks:
        return True, None
    return False, f"health={has_health}, checks={has_checks}"

check("DoD 5: /health endpoint với DB+Redis checks", dod5)

# DoD 6: alembic.ini tồn tại
def dod6():
    has_ini = (ROOT / "alembic.ini").exists()
    has_env = (ROOT / "migrations" / "env.py").exists()
    has_versions = (ROOT / "migrations" / "versions").exists()
    migrations = list((ROOT / "migrations" / "versions").glob("*.py")) if has_versions else []
    ok = has_ini and has_env and len(migrations) >= 9
    return ok, f"alembic.ini={has_ini}, env.py={has_env}, migrations={len(migrations)}/9"

check("DoD 6: Alembic setup với 9 migrations", dod6)

# DoD 7: GitHub Actions files tồn tại
def dod7():
    pr = (ROOT / ".github" / "workflows" / "pr.yml").exists()
    deploy = (ROOT / ".github" / "workflows" / "deploy.yml").exists()
    ok = pr and deploy
    return ok, f"pr.yml={pr}, deploy.yml={deploy}"

check("DoD 7: GitHub Actions pr.yml + deploy.yml", dod7)

# DoD 8: Test files tồn tại
def dod8():
    tests_dir = ROOT / "tests"
    test_files = list(tests_dir.glob("test_*.py")) if tests_dir.exists() else []
    ok = len(test_files) >= 3
    return ok, f"{len(test_files)} test files: {[f.name for f in test_files]}"

check("DoD 8: Test suite với ≥3 test files", dod8)

# DoD 9: .env.example tồn tại và không chứa real secrets
def dod9():
    env_example = ROOT / ".env.example"
    if not env_example.exists():
        return False, ".env.example không tồn tại"
    content = env_example.read_text()
    # Check các keys quan trọng có mặt
    required = ["BASE_URL", "DATABASE_URL", "JWT_SECRET_KEY", "TELEGRAM_BOT_TOKEN"]
    missing = [k for k in required if k not in content]
    if missing:
        return False, f"Thiếu keys: {missing}"
    # Check không có real values trong example
    suspicious = ["AAF0ay119c", "Zarmor%402025", "ZA2026@xK9"]
    found = [s for s in suspicious if s in content]
    if found:
        return False, f"⚠️  Có thể có real credentials trong .env.example: {found}"
    return True, None

check("DoD 9: .env.example tồn tại với tất cả keys", dod9)

# DoD 10: .gitignore chặn .env và dead code
def dod10():
    gitignore = ROOT / ".gitignore"
    if not gitignore.exists():
        return False, ".gitignore không tồn tại"
    content = gitignore.read_text()
    required = [".env", "*.bak", "fix_*.py", "Z-Armor.db"]
    missing = [k for k in required if k not in content]
    if missing:
        return False, f"Thiếu rules: {missing}"
    return True, None

check("DoD 10: .gitignore chặn .env, *.bak, fix_*.py", dod10)

# ─── Summary ──────────────────────────────────────────────────────────────────
passed = sum(results)
total = len(results)
print(f"\n{'='*60}")
print(f"RESULT: {passed}/{total} checks passed")
print("="*60)

if passed == total:
    print(f"\n🎉 PART 1 DEFINITION OF DONE: COMPLETE")
    print("   Có thể bắt đầu Part 2 (tách microservices)")
    sys.exit(0)
else:
    failed = total - passed
    print(f"\n⚠️  {failed} checks còn fail — hoàn thành trước khi bắt đầu Part 2")
    sys.exit(1)
