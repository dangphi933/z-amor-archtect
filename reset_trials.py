import os, sys
sys.path.insert(0, r"C:\Users\Administrator\Desktop\Z-ARMOR-CLOUD")
os.chdir(r"C:\Users\Administrator\Desktop\Z-ARMOR-CLOUD")

from database import engine
from sqlalchemy import text

with engine.connect() as conn:
    # Xem ten cot thuc te
    cols = conn.execute(text("""
        SELECT column_name FROM information_schema.columns 
        WHERE table_name='license_keys' ORDER BY ordinal_position
    """)).fetchall()
    print("Cot trong license_keys:", [c[0] for c in cols])
    print()

    # Xem du lieu
    rows = conn.execute(text("SELECT * FROM license_keys LIMIT 20")).fetchall()
    print(f"Co {len(rows)} records:")
    for r in rows:
        print(dict(r._mapping))
    print()

confirm = input("Xoa het trial keys? (y/n): ").strip().lower()
if confirm == "y":
    with engine.connect() as conn:
        # Tim cot email va is_trial
        result = conn.execute(text("""
            DELETE FROM license_keys WHERE is_trial = true
        """))
        conn.commit()
        print(f"[OK] Da xoa {result.rowcount} trial keys")
else:
    print("Huy.")