import asyncio
from datetime import datetime
from api.dashboard_service import safe_telegram_send
from api.config_manager import get_all_units

async def scheduled_daily_briefing():
    morning_sent, evening_sent = False, False
    last_day, last_heartbeat_hour = None, None 
    print("✅ [QUANT DESK] Scheduler Giao ban Cloud V7.0 đã kích hoạt!")

    while True:
        try:
            now = datetime.now()
            current_day = now.date()

            if last_day != current_day:
                morning_sent, evening_sent = False, False
                last_day = current_day

            # 💡 V7.0: Lấy danh sách tài khoản trực tiếp từ SQLite Database
            units_config = get_all_units()
            
            # Kiểm tra nếu có ít nhất 1 tài khoản đang active Telegram
            has_active_tg = any(
                cfg.get("telegram_config", {}).get("is_active", False) 
                for cfg in units_config.values()
            )
            
            if not has_active_tg:
                await asyncio.sleep(60)
                continue

            # MORNING (7:00 AM)
            if now.hour == 7 and now.minute == 0 and not morning_sent:
                safe_telegram_send("🌅 <b>[QUANT DESK] MỞ PHIÊN CLOUD:</b> Hệ thống đã sẵn sàng bảo vệ vốn.")
                morning_sent = True

            # HEARTBEAT (Báo cáo sinh tồn các khung giờ chẵn)
            if now.minute == 0 and now.hour in [3, 11, 15, 19] and last_heartbeat_hour != now.hour:
                safe_telegram_send("💓 <b>[SYSTEM STATUS] ONLINE:</b> Đám mây Z-Armor đang trực ban.")
                last_heartbeat_hour = now.hour

            # EVENING (11:55 PM)
            if now.hour == 23 and now.minute == 55 and not evening_sent:
                safe_telegram_send("🌙 <b>[QUANT DESK] CHỐT PHIÊN:</b> Đã đóng băng dữ liệu ngày và reset ngân sách.")
                evening_sent = True

        except Exception as e: 
            print(f"❌ Lỗi Daily Briefing: {e}")
            
        await asyncio.sleep(30)