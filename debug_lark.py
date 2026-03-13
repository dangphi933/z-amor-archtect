"""
DEBUG LARK API
==============
Script kiểm tra kết nối và ghi data vào Lark Base
"""

import os
import asyncio
import httpx
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# Config
LARK_APP_ID = os.environ.get("LARK_APP_ID")
LARK_APP_SECRET = os.environ.get("LARK_APP_SECRET")
LARK_BASE_TOKEN = os.environ.get("LARK_BASE_TOKEN")
LARK_TABLE_ID = os.environ.get("LARK_TABLE_ID")
LARK_LOG_TABLE_ID = os.environ.get("LARK_LOG_TABLE_ID", "tbl9Og6oEtEDzlNb")


async def get_tenant_token():
    """Lấy tenant access token"""
    url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
    payload = {
        "app_id": LARK_APP_ID,
        "app_secret": LARK_APP_SECRET
    }
    
    print(f"[1] Getting tenant token...")
    print(f"    App ID: {LARK_APP_ID}")
    print(f"    App Secret: {LARK_APP_SECRET[:10]}...")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload)
        data = resp.json()
        
        if "tenant_access_token" in data:
            token = data["tenant_access_token"]
            print(f"    ✅ Token: {token[:20]}...")
            return token
        else:
            print(f"    ❌ Error: {data}")
            return None


async def test_create_order_record():
    """Test ghi vào bảng Orders"""
    token = await get_tenant_token()
    if not token:
        return
    
    url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{LARK_BASE_TOKEN}/tables/{LARK_TABLE_ID}/records"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # Test data
    test_order = {
        "fields": {
            "Order ID": "TEST-" + datetime.now().strftime("%H%M%S"),
            "Buyer Name": "Test User",
            "Buyer Email": "test@example.com",
            "Purchased Tier": "STARTER_TRIAL",
            "Amount Paid": 0.0,
            "Payment Status": "PENDING"
        }
    }
    
    print(f"\n[2] Creating test order record...")
    print(f"    Base Token: {LARK_BASE_TOKEN}")
    print(f"    Table ID: {LARK_TABLE_ID}")
    print(f"    URL: {url}")
    print(f"    Payload: {test_order}")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, headers=headers, json=test_order)
        print(f"\n    Response Status: {resp.status_code}")
        print(f"    Response Body: {resp.text}")
        
        if resp.status_code == 200:
            print("    ✅ Order record created successfully!")
            return True
        else:
            print("    ❌ Failed to create order record")
            return False


async def test_create_license_log():
    """Test ghi vào bảng License Log"""
    token = await get_tenant_token()
    if not token:
        return
    
    url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{LARK_BASE_TOKEN}/tables/{LARK_LOG_TABLE_ID}/records"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # Test data
    test_log = {
        "fields": {
            "Thoi gian": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ID Don": "TEST-ORDER-123",
            "Key da cap": "ZARMOR-TEST-12345",
            "Trang thai": "SUCCESS"
        }
    }
    
    print(f"\n[3] Creating test license log...")
    print(f"    Base Token: {LARK_BASE_TOKEN}")
    print(f"    Log Table ID: {LARK_LOG_TABLE_ID}")
    print(f"    URL: {url}")
    print(f"    Payload: {test_log}")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, headers=headers, json=test_log)
        print(f"\n    Response Status: {resp.status_code}")
        print(f"    Response Body: {resp.text}")
        
        if resp.status_code == 200:
            print("    ✅ License log created successfully!")
            return True
        else:
            print("    ❌ Failed to create license log")
            return False


async def list_tables():
    """Liệt kê tất cả tables trong Base"""
    token = await get_tenant_token()
    if not token:
        return
    
    url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{LARK_BASE_TOKEN}/tables"
    headers = {
        "Authorization": f"Bearer {token}"
    }
    
    print(f"\n[4] Listing all tables in Base...")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers=headers)
        data = resp.json()
        
        if resp.status_code == 200 and "data" in data:
            tables = data["data"].get("items", [])
            print(f"    ✅ Found {len(tables)} tables:")
            for table in tables:
                print(f"       - {table.get('name')} (ID: {table.get('table_id')})")
        else:
            print(f"    ❌ Error: {data}")


async def main():
    print("\n" + "="*60)
    print("LARK API DEBUG TOOL")
    print("="*60)
    
    print("\n📋 Configuration:")
    print(f"  LARK_APP_ID: {LARK_APP_ID}")
    print(f"  LARK_APP_SECRET: {LARK_APP_SECRET[:10]}..." if LARK_APP_SECRET else "  ❌ MISSING")
    print(f"  LARK_BASE_TOKEN: {LARK_BASE_TOKEN}")
    print(f"  LARK_TABLE_ID: {LARK_TABLE_ID}")
    print(f"  LARK_LOG_TABLE_ID: {LARK_LOG_TABLE_ID}")
    
    print("\n" + "="*60)
    
    # Test 1: Get token
    token = await get_tenant_token()
    if not token:
        print("\n❌ Cannot proceed without token!")
        return
    
    # Test 2: List tables
    await list_tables()
    
    # Test 3: Create order
    await test_create_order_record()
    
    # Test 4: Create license log
    await test_create_license_log()
    
    print("\n" + "="*60)
    print("DEBUG COMPLETED")
    print("="*60)
    print("\nKiểm tra Lark Base để xem records mới:")
    print(f"https://xjp85em6p2ue.jp.larksuite.com/base/{LARK_BASE_TOKEN}")
    print("\n")


if __name__ == "__main__":
    asyncio.run(main())
