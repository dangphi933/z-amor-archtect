import os
import time
import requests
import re

# Bộ nhớ đệm (Cache) để lưu hàng ngàn danh sách sàn vào RAM
_cached_brokers = []
_cached_time = 0

def get_broker_suggestions(q: str):
    global _cached_brokers, _cached_time
    
    if len(q) < 2:
        return []
        
    try:
        current_time = time.time()
        # Chỉ gọi API lên Cloud nếu Cache đã quá hạn 24h hoặc đang rỗng
        if not _cached_brokers or current_time - _cached_time > 86400:
            token = os.getenv("META_API_TOKEN")
            
            # TRẢ LẠI URL GỐC CỦA META-API (Có lặp chữ agiliumtrade)
            url = "https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai/api/v1/brokerServers"
            
            headers = {"Accept": "application/json"}
            if token:
                headers["auth-token"] = token
                
            # Tăng timeout lên 15 giây vì file danh sách sàn của MetaApi rất nặng
            res = requests.get(url, headers=headers, timeout=15)
            
            if res.status_code == 200:
                _cached_brokers = res.json()
                _cached_time = current_time
            else:
                print(f"❌ Lỗi lấy dữ liệu Sàn: {res.status_code} - {res.text}")
                return []

        # THUẬT TOÁN SMART SEARCH
        search_tokens = [t.strip() for t in re.split(r'[\s\-]+', q.lower()) if t.strip()]
        
        matched = []
        for s in _cached_brokers:
            server_name = s.get('name', '')
            normalized_name = server_name.lower()
            
            if all(token in normalized_name for token in search_tokens):
                matched.append({"name": server_name})
                
        # Sắp xếp ưu tiên: Tên ngắn nhất (sát nghĩa nhất) hiển thị trên cùng
        matched.sort(key=lambda x: len(x['name']))
        
        return matched[:15]
        
    except requests.exceptions.Timeout:
        print("❌ Lỗi Timeout: Máy chủ MetaApi tải danh sách quá chậm. Vui lòng thử lại.")
        return []
    except Exception as e:
        print(f"❌ Lỗi tìm kiếm broker: {e}")
        return []