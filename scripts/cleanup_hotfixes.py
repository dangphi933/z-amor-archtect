import os, sys, subprocess
from pathlib import Path

ROOT = Path("C:/Users/Administrator/Desktop/Z-ARMOR-CLOUD")

FIX_FILES = [
    "fix_tg.py", "fix_lark.py", "fix_ip.py", "fix_ip2.py",
    "fix_schemas.py", "fix_datetime_timezone.py", "fix_db_columns.py",
    "fix_ea_router_disconnect.py", "fix_env.py", "fix_fleet_isolation.py",
    "fix_indent.py", "fix_init_data_filter.py", "fix_lark_payload.py",
    "fix_license_helpers.py", "fix_radar_import.py", "fix_return_ok.py",
    "fix_scope.py", "fix_telegram_import.py", "fix_tg_await.py",
    "fix_tg_await.py", "fix_webhook_tg.py", "fix_final.py",
    "hotfix.py", "patch_main.py",
]

BAK_PATTERNS = ["*.bak", "*.backup", "main_patch*.py", "main_patches*.py", "main_routes_patch*.py"]

dry_run = "--apply" not in sys.argv

print("\n" + "="*60)
print("Z-ARMOR PART 1 — CLEANUP FIX FILES")
print("MODE:", "DRY RUN (safe)" if dry_run else "APPLY (deleting!)")
print("="*60)

found = []
missing = []
for fname in FIX_FILES:
    fp = ROOT / fname
    if fp.exists():
        found.append(fp)
        print(f"  FOUND: {fname}")
    else:
        missing.append(fname)
        print(f"  MISSING (already gone): {fname}")

import glob
for pattern in BAK_PATTERNS:
    for fp in ROOT.glob(pattern):
        found.append(fp)
        print(f"  FOUND (bak): {fp.name}")

print(f"\nSummary: {len(found)} files to delete, {len(missing)} already gone")

if not dry_run and found:
    confirm = input(f"\nDelete {len(found)} files? (yes/no): ")
    if confirm == "yes":
        for fp in found:
            fp.unlink()
            print(f"  DELETED: {fp.name}")
        print("Done!")
    else:
        print("Cancelled.")
elif dry_run:
    print("\nRun with --apply to actually delete.")
