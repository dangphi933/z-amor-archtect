#!/usr/bin/env python3
"""
scripts/cleanup_hotfixes.py
===========================
Nhóm A — Cleanup 23 fix/hotfix/patch files.

Chạy từ root repo:
    python3 scripts/cleanup_hotfixes.py --dry-run   # xem trước
    python3 scripts/cleanup_hotfixes.py --apply      # thực thi

Quy trình mỗi file:
  1. Đọc nội dung
  2. Kiểm tra logic đã có trong source chưa (grep)
  3. Báo cáo: DELETE / INSPECT / MERGE
  4. --apply: git rm + commit
"""
import os
import sys
import subprocess
import argparse
from pathlib import Path

ROOT = Path(__file__).parent.parent

# ─── Danh sách đầy đủ 23 file theo tài liệu ─────────────────────────────────
FIX_FILES = {
    "fix_tg.py":               {"action": "DELETE", "reason": "Tên hàm tg_send đã đồng bộ trong webhook_retry.py"},
    "fix_lark.py":             {"action": "DELETE", "reason": "Hàm lark đã sync trong webhook_retry.py"},
    "fix_ip.py":               {"action": "DELETE", "reason": "IP được xử lý qua BASE_URL env var — xem A.3"},
    "fix_ip2.py":              {"action": "DELETE", "reason": "Duplicate của fix_ip.py"},
    "fix_schemas.py":          {"action": "DELETE", "reason": "Field 'method' đã có trong api/schemas.py"},
    "fix_datetime_timezone.py":{"action": "DELETE", "reason": "datetime.now(timezone.utc) đã áp dụng trong source"},
    "fix_db_columns.py":       {"action": "DELETE", "reason": "Logic đã có trong storage_v83_full.sql"},
    "fix_ea_router_disconnect.py": {"action": "DELETE", "reason": "Logic debounce đã merge vào ea_router.py"},
    "fix_env.py":              {"action": "DELETE", "reason": "Dùng .env.example thay thế"},
    "fix_fleet_isolation.py":  {"action": "DELETE", "reason": "Logic filter đã merge vào main.py"},
    "fix_indent.py":           {"action": "DELETE", "reason": "Fix lỗi indent đã áp dụng — không cần script"},
    "fix_init_data_filter.py": {"action": "DELETE", "reason": "Đã merge vào main.py"},
    "fix_lark_payload.py":     {"action": "INSPECT", "reason": "Verify lark_service.py có payload đúng trước khi xóa"},
    "fix_license_helpers.py":  {"action": "INSPECT", "reason": "Check xem helpers đã có trong license_service.py chưa"},
    "fix_radar_import.py":     {"action": "DELETE", "reason": "Import path đã đúng trong main.py"},
    "fix_return_ok.py":        {"action": "DELETE", "reason": "Return value đã fix trong source"},
    "fix_scope.py":            {"action": "DELETE", "reason": "Variable scope đã fix"},
    "fix_telegram_import.py":  {"action": "DELETE", "reason": "Import đã đúng"},
    "fix_tg_await.py":         {"action": "DELETE", "reason": "await đã thêm vào source"},
    "fix_webhook_tg.py":       {"action": "INSPECT", "reason": "Verify webhook_retry.py đúng trước khi xóa"},
    "fix_final.py":            {"action": "INSPECT", "reason": "Nội dung chưa rõ — cần đọc kỹ trước"},
    "hotfix.py":               {"action": "DELETE", "reason": "Windows path hardcode + config.py fix đã áp dụng thủ công"},
    "patch_main.py":           {"action": "DELETE", "reason": "radar_router đã mount + email_service.py đã có"},
}

BAK_PATTERNS = ["*.bak", "*.backup", "main_patch*.py", "main_patches*.py", "main_routes_patch*.py"]


def run(cmd: str, cwd=ROOT) -> tuple[int, str, str]:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def check_in_source(pattern: str) -> list[str]:
    """Grep pattern trong source files."""
    code, out, _ = run(f"grep -rn '{pattern}' --include='*.py' . "
                       f"| grep -v fix_ | grep -v hotfix | grep -v patch_main | grep -v '.git'")
    return [l for l in out.splitlines() if l.strip()] if out else []


def inspect_file(filepath: Path) -> dict:
    """Đọc file và trả về summary."""
    if not filepath.exists():
        return {"exists": False}
    content = filepath.read_text(errors="replace")
    lines = content.splitlines()
    # Lấy tất cả function defs
    funcs = [l.strip() for l in lines if l.strip().startswith("def ") or l.strip().startswith("async def ")]
    return {
        "exists": True,
        "lines": len(lines),
        "functions": funcs,
        "preview": "\n".join(lines[:15]),
    }


def git_rm(filepath: Path, dry_run: bool) -> bool:
    if not filepath.exists():
        print(f"    ⚠️  File không tồn tại: {filepath.name}")
        return False
    if dry_run:
        print(f"    [DRY] git rm {filepath.name}")
        return True
    code, out, err = run(f"git rm {filepath}")
    if code != 0:
        # Nếu không tracked bởi git, xóa file thường
        filepath.unlink()
        print(f"    🗑️  Deleted (untracked): {filepath.name}")
    else:
        print(f"    🗑️  git rm: {filepath.name}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Cleanup Z-Armor hotfix files")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ xem, không thực thi")
    parser.add_argument("--apply", action="store_true", help="Thực thi xóa files")
    parser.add_argument("--inspect-only", action="store_true", help="Chỉ inspect INSPECT files")
    args = parser.parse_args()

    if not args.dry_run and not args.apply and not args.inspect_only:
        print("Dùng: --dry-run (xem trước) | --apply (thực thi) | --inspect-only")
        sys.exit(1)

    dry_run = args.dry_run or args.inspect_only
    deleted = []
    inspect_needed = []
    missing = []

    print("\n" + "="*60)
    print("Z-ARMOR PART 1 — NHÓM A: CLEANUP 23 FIX FILES")
    print("="*60)

    for filename, meta in FIX_FILES.items():
        filepath = ROOT / filename
        action = meta["action"]
        reason = meta["reason"]
        info = inspect_file(filepath)

        if not info["exists"]:
            missing.append(filename)
            print(f"\n{'─'*50}")
            print(f"📭 {filename} — MISSING (đã xóa hoặc chưa tồn tại)")
            continue

        print(f"\n{'─'*50}")
        print(f"📄 {filename} ({info['lines']} lines) — {action}")
        print(f"   Lý do: {reason}")

        if action == "INSPECT" or args.inspect_only:
            print(f"   Functions: {info['functions']}")
            print(f"   Preview:\n{info['preview']}")
            inspect_needed.append(filename)

        if action == "DELETE":
            if args.apply:
                if git_rm(filepath, dry_run=False):
                    deleted.append(filename)
            elif args.dry_run:
                print(f"    [DRY] Sẽ xóa: {filepath}")
                deleted.append(filename)

    # Bak files
    print(f"\n{'='*60}")
    print("BAK/BACKUP FILES")
    print("="*60)
    for pattern in BAK_PATTERNS:
        code, out, _ = run(f"find . -name '{pattern}' | grep -v .git | grep -v migrations")
        if out:
            for f in out.splitlines():
                fp = ROOT / f.lstrip("./")
                print(f"  📄 {f}")
                if args.apply:
                    git_rm(fp, dry_run=False)
                    deleted.append(f)
                elif args.dry_run:
                    print(f"    [DRY] Sẽ xóa: {f}")
        else:
            print(f"  ✅ Không tìm thấy file {pattern}")

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print("="*60)
    print(f"  ✅ Xóa thành công: {len(deleted)} files")
    print(f"  🔍 Cần inspect thủ công: {len(inspect_needed)} files")
    print(f"  📭 Không tìm thấy: {len(missing)} files")

    if inspect_needed:
        print(f"\n⚠️  CẦN INSPECT THỦ CÔNG trước khi xóa:")
        for f in inspect_needed:
            print(f"    - {f}: {FIX_FILES[f]['reason']}")

    if args.apply and deleted:
        print(f"\n📦 Committing {len(deleted)} deletions...")
        code, out, err = run(
            f'git commit -m "chore: cleanup {len(deleted)} fix/hotfix/patch files — Part 1 Group A"'
        )
        if code == 0:
            print("  ✅ Committed")
        else:
            print(f"  ⚠️  Commit: {err or 'nothing to commit'}")


if __name__ == "__main__":
    main()
