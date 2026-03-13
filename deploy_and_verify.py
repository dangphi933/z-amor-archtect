"""
deploy_and_verify.py
====================
Verify main.py da duoc deploy dung va restart server.
Chay tai: C:\\Users\\Administrator\\Desktop\\Z-ARMOR-CLOUD
"""
import os, sys, time

print("=" * 55)
print("  Z-ARMOR DEPLOY VERIFICATION")
print("=" * 55)

# Check 1: main.py co cac fix chua?
print("\n[1] Checking main.py fixes...")
try:
    c = open("main.py", encoding="utf-8").read()
    fixes = {
        "_last_hb":                   "webhook heartbeat cache update",
        "_init_data_cache":           "init-data 800ms cache",
        "_hb_disconnect_last_alert":  "disconnect debounce 5min",
        "OPTIMAL_FLOW":               "default physics state",
        "Cache 800ms":                "init-data rate limit comment",
    }
    all_ok = True
    for key, label in fixes.items():
        ok = key in c
        print(f"  {'OK  ' if ok else 'MISS'} {label}")
        if not ok:
            all_ok = False

    if not all_ok:
        print("\n  *** main.py CHUA DUOC CAP NHAT ***")
        print("  Copy file main.py moi vao thu muc nay truoc khi chay script")
        sys.exit(1)
    else:
        print("  -> main.py co day du cac fix")
except FileNotFoundError:
    print("  ERROR: main.py not found in", os.getcwd())
    sys.exit(1)

# Check 2: restart pm2
print("\n[2] Restarting pm2...")
ret = os.system("pm2 restart z-armor-core")
if ret != 0:
    print("  WARN: pm2 restart returned", ret)
    print("  Thu chay truc tiep: python ZARMOR_START.py")
else:
    print("  OK: pm2 restart sent")

time.sleep(3)

# Check 3: Check server dang chay
print("\n[3] Checking server status...")
import subprocess
result = subprocess.run(["pm2", "list"], capture_output=True, text=True)
if "z-armor-core" in result.stdout:
    if "online" in result.stdout:
        print("  OK: z-armor-core is ONLINE")
    else:
        print("  WARN: z-armor-core may not be online")
        print(result.stdout[:300])
else:
    print("  ERROR: z-armor-core not found in pm2 list")

# Check 4: Test /api/health
print("\n[4] Testing /api/health...")
try:
    import urllib.request
    with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=5) as r:
        print(f"  OK: HTTP {r.status} - Server responding")
except Exception as e:
    print(f"  FAIL: {e}")

# Check 5: Test /api/webhook/heartbeat manually
print("\n[5] Testing /api/webhook/heartbeat with dummy data...")
try:
    import urllib.request, json
    data = json.dumps({
        "account_id": "413408816",
        "equity": 1037.75,
        "balance": 1043.49,
        "state": "OPTIMAL_FLOW",
        "license_key": "ZARMOR-23F79-5A50D"
    }).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/webhook/heartbeat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        body = r.read().decode()
        print(f"  OK: HTTP {r.status} - {body}")
        print("  -> _last_hb should now be set for 413408816")
except Exception as e:
    print(f"  FAIL: {e}")

print("\n" + "=" * 55)
print("  DONE. Theo doi: pm2 logs z-armor-core --lines 20")
print("  Ket qua mong doi: KHONG con [SENDING] disconnect alert")
print("  Va: [HEARTBEAT] OK | ... account=413408816")
print("=" * 55)
