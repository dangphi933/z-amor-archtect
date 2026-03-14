"""
TELEGRAM ENGINE — Z-Armor Risk Guardian
=========================================
Tinh than: Nguoi Gac Cong Rui Ro.
Moi tin nhan phai tra loi duoc 3 cau hoi:
  1. CHUYEN GI dang xay ra? (so lieu cu the)
  2. NGUY HIEM den dau? (vi tri trong nguong)
  3. PHAI LAM GI? (chi lenh hanh dong)

Alert levels:
  DEFCON 3 (xanh)  — Thong tin / quan sat, silent
  DEFCON 2 (cam)   — Canh bao ap luc, co chuong
  DEFCON 1 (do)    — Gioi han sap vo, urgent
  SCRAM    (trang)  — Vo nguong, lock cung
"""

import os
import httpx
import logging
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# BUG LOG FIX: Dùng absolute path thay vì relative
# Relative path phụ thuộc vào CWD của server → log file bị tạo ở nơi bất ngờ
_LOG_DIR  = os.path.dirname(os.path.abspath(__file__))
_LOG_FILE = os.path.join(_LOG_DIR, "telegram_debug.log")

# Python logger để Audit Log panel trên dashboard cũng thấy
_tg_logger = logging.getLogger("ZArmor_Telegram")


# ─────────────────────────────────────────────
# LUI GUI & LOG
# ─────────────────────────────────────────────

def write_telegram_log(status: str, chat_id: str, message: str, response: str = ""):
    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    short = message.replace('\n', ' ')[:100] + ("..." if len(message) > 100 else "")
    entry = f"[{now}] [{status:7}] CHAT:{chat_id} | {short} | {response}\n"
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        pass  # Không throw — tránh vòng lặp lỗi
    # Luôn in ra stdout và Python logger (Audit Log panel sẽ thấy qua logging)
    print(entry.strip(), flush=True)
    if status in ("FAIL", "NET_ERR"):
        _tg_logger.warning(entry.strip())
    else:
        _tg_logger.info(entry.strip())


async def push_to_telegram(chat_id: str, text: str, disable_notification: bool = False) -> bool:
    if not chat_id:
        write_telegram_log("SKIP", "N/A", text, "no chat_id")
        return False
    if not TELEGRAM_BOT_TOKEN or "THAY_TOKEN" in TELEGRAM_BOT_TOKEN:
        write_telegram_log("SKIP", chat_id, text, "no token")
        return False

    url     = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id":                  chat_id,
        "text":                     text,
        "parse_mode":               "HTML",
        "disable_web_page_preview": True,
        "disable_notification":     disable_notification,
    }
    try:
        write_telegram_log("SEND", chat_id, text, "dispatching...")
        async with httpx.AsyncClient(timeout=10.0) as client:
            r  = await client.post(url, json=payload)
            ok = r.status_code == 200
            write_telegram_log("OK" if ok else "FAIL", chat_id, text,
                               f"HTTP {r.status_code}" + ("" if ok else f" {r.text[:80]}"))
            return ok
    except Exception as e:
        write_telegram_log("NET_ERR", chat_id, text, str(e))
        return False


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _bar(pct: float, length: int = 10) -> str:
    """Progress bar: [pct 0-100] -> blocks."""
    filled = max(0, min(length, round(pct / 100 * length)))
    return "\u2593" * filled + "\u2591" * (length - filled)

def _pressure_icon(pct: float) -> str:
    if pct >= 90: return "\u2622\ufe0f"
    if pct >= 70: return "\U0001f534"
    if pct >= 50: return "\U0001f7e0"
    if pct >= 30: return "\U0001f7e1"
    return "\U0001f7e2"

def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


# ══════════════════════════════════════════════
# 1. SYSTEM NOTICES (DEFCON 3)
# ══════════════════════════════════════════════

async def send_defcon3_silent(chat_id: str, title: str, message: str):
    text = (
        f"\U0001f7e2 <b>[ SYSTEM NOTICE ]</b>  <code>{_ts()}</code>\n"
        f"<b>{title}</b>\n"
        f"&#9141;&#9141;&#9141;&#9141;&#9141;&#9141;&#9141;&#9141;\n"
        f"<i>{message}</i>"
    )
    await push_to_telegram(chat_id, text, disable_notification=True)


async def send_session_armed(chat_id: str, trader_name: str,
                              max_daily_dd_pct: float, max_dd_pct: float,
                              daily_budget: float, rollover_hour: int):
    """EA vua ARM — xac nhan hop dong rui ro dang hieu luc."""
    text = (
        f"\U0001f6e1\ufe0f <b>[ SESSION CONTRACT ARMED ]</b>  <code>{_ts()}</code>\n"
        f"\U0001f464 <code>{trader_name}</code>\n"
        f"══════════════════════\n"
        f"\U0001f4dc <b>Hop dong Rui ro hom nay:</b>\n\n"
        f"  \U0001f4b0 Budget ngay     : <b>${daily_budget:,.0f}</b>\n"
        f"  \U0001f4c9 Max Daily DD    : <b>{max_daily_dd_pct}%</b>  \u2190 dung ngay neu cham\n"
        f"  \u2622\ufe0f Max Total DD    : <b>{max_dd_pct}%</b>  \u2190 SCRAM toan he\n"
        f"  \U0001f504 Rollover luc    : <b>{rollover_hour:02d}:00</b>\n\n"
        f"<i>Radar da khoa thong so. Moi vi pham se bi ghi nhan.</i>"
    )
    await push_to_telegram(chat_id, text, disable_notification=True)


async def send_session_rollover(chat_id: str, trader_name: str,
                                 pnl: float, trades_count: int, compliance_score: int):
    """Rollover tu nhien — reset ngan sach sang ngay moi."""
    result_icon = "\u2705" if pnl >= 0 else "\u274c"
    pnl_str     = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
    score_icon  = "\U0001f7e2" if compliance_score >= 85 else ("\U0001f7e1" if compliance_score >= 60 else "\U0001f534")
    text = (
        f"\U0001f305 <b>[ ROLLOVER COMPLETE ]</b>  <code>{_ts()}</code>\n"
        f"\U0001f464 <code>{trader_name}</code>\n"
        f"══════════════════════\n"
        f"{result_icon} <b>Ket qua phien:</b> <code>{pnl_str}</code>\n"
        f"\U0001f4ca So lenh: <code>{trades_count}</code>\n"
        f"{score_icon} Compliance: <b>{compliance_score}/100</b>\n\n"
        f"<i>Ngan sach da reset. Phien moi bat dau.</i>"
    )
    await push_to_telegram(chat_id, text, disable_notification=True)


# ══════════════════════════════════════════════
# 2. TRADE EVENTS
# ══════════════════════════════════════════════

async def send_trade_opened(chat_id: str, trader_name: str,
                             ticket: str, symbol: str, trade_type: str,
                             volume: float, price: float,
                             daily_dd_used_pct: float = 0.0,
                             daily_budget_used_pct: float = 0.0):
    """Lenh moi — kem context ap luc hien tai."""
    direction_icon = "\U0001f7e2 BUY" if "BUY" in trade_type.upper() else "\U0001f534 SELL"
    pressure_icon  = _pressure_icon(max(daily_dd_used_pct, daily_budget_used_pct))
    dd_bar         = _bar(daily_dd_used_pct)
    budget_bar     = _bar(daily_budget_used_pct)

    text = (
        f"\u26a1 <b>[ ORDER OPENED ]</b>  <code>{_ts()}</code>\n"
        f"\U0001f464 <code>{trader_name}</code>\n"
        f"&#9141;&#9141;&#9141;&#9141;&#9141;&#9141;&#9141;&#9141;\n"
        f"\U0001f3f7  Ticket : <code>#{ticket}</code>\n"
        f"\U0001f4b1  Symbol : <b>{symbol}</b>   {direction_icon}\n"
        f"\u2696\ufe0f  Volume : <code>{volume} lot</code>   @  <code>{price:,.3f}</code>\n"
        f"&#9141;&#9141;&#9141;&#9141;&#9141;&#9141;&#9141;&#9141;\n"
        f"{pressure_icon} <b>Trang thai ap luc hien tai:</b>\n"
        f"  DD ngay  {dd_bar} <code>{daily_dd_used_pct:.1f}%</code>\n"
        f"  Budget   {budget_bar} <code>{daily_budget_used_pct:.1f}%</code>\n"
        f"<i>Radar dang theo doi quy dao lenh nay...</i>"
    )
    await push_to_telegram(chat_id, text, disable_notification=False)


async def send_trade_closed(chat_id: str, trader_name: str,
                             ticket: str, symbol: str, trade_type: str,
                             pnl: float, rr_ratio: float = 0.0,
                             cumulative_pnl: float = 0.0,
                             daily_budget: float = 0.0):
    """Lenh dong — PnL + tong ngay + % budget con lai."""
    is_win    = pnl >= 0
    icon      = "\u2705 WIN" if is_win else "\u274c LOSS"
    pnl_str   = f"+${pnl:,.2f}" if is_win else f"-${abs(pnl):,.2f}"
    cum_str   = f"+${cumulative_pnl:,.2f}" if cumulative_pnl >= 0 else f"-${abs(cumulative_pnl):,.2f}"

    budget_used_pct = min(100.0, abs(cumulative_pnl) / daily_budget * 100) \
                      if daily_budget > 0 and cumulative_pnl < 0 else 0.0
    budget_bar      = _bar(budget_used_pct)
    pressure_icon   = _pressure_icon(budget_used_pct)

    rr_line = f"\U0001f4d0  R:R thuc : <code>1 : {rr_ratio:.2f}</code>\n" if rr_ratio > 0 else ""

    text = (
        f"{icon}  <b>[ ORDER CLOSED ]</b>  <code>{_ts()}</code>\n"
        f"\U0001f464 <code>{trader_name}</code>\n"
        f"&#9141;&#9141;&#9141;&#9141;&#9141;&#9141;&#9141;&#9141;\n"
        f"\U0001f3f7  Ticket : <code>#{ticket}</code>   {symbol} ({trade_type})\n"
        f"\U0001f4b0  PnL    : <b>{pnl_str}</b>\n"
        f"{rr_line}"
        f"&#9141;&#9141;&#9141;&#9141;&#9141;&#9141;&#9141;&#9141;\n"
        f"\U0001f4ca <b>Tong ngay:</b> <code>{cum_str}</code>\n"
        f"{pressure_icon} Budget {budget_bar} <code>{budget_used_pct:.0f}%</code> da dung\n"
        f"<i>Du lieu da nap vao loi phan tich Gibbs.</i>"
    )
    await push_to_telegram(chat_id, text, disable_notification=False)


# ══════════════════════════════════════════════
# 3. CANH BAO TIEM CAN (DEFCON 2 - cam)
# ══════════════════════════════════════════════

async def send_defcon2_warning(chat_id: str, trader_name: str,
                                used_budget: float, max_budget: float,
                                daily_dd_pct: float = 0.0, max_daily_dd_pct: float = 5.0,
                                open_positions: int = 0):
    """
    Canh bao khi ap luc > 50% hoac con < 2 lan risk.
    Cu the: con bao nhieu tien, con bao nhieu % DD.
    """
    budget_pct   = round(used_budget / max_budget * 100, 1)   if max_budget > 0       else 0.0
    budget_left  = max(0.0, max_budget - used_budget)
    dd_used_pct  = round(daily_dd_pct / max_daily_dd_pct * 100, 1) if max_daily_dd_pct > 0 else 0.0
    dd_remaining = max(0.0, max_daily_dd_pct - daily_dd_pct)
    master_pct   = max(budget_pct, dd_used_pct)
    trigger      = "DAILY DD" if dd_used_pct > budget_pct else "BUDGET"
    trigger_val  = f"{daily_dd_pct:.2f}% / {max_daily_dd_pct}%" if trigger == "DAILY DD" \
                   else f"${used_budget:,.0f} / ${max_budget:,.0f}"
    icon         = _pressure_icon(master_pct)

    text = (
        f"\U0001f7e0 <b>[ KINETIC PRESSURE WARNING ]</b>  <code>{_ts()}</code>\n"
        f"\U0001f464 <code>{trader_name}</code>\n"
        f"══════════════════════\n"
        f"{icon}  Trigger : <b>{trigger}</b>  \u2192  <code>{trigger_val}</code>\n\n"
        f"\U0001f4ca <b>Bang ap luc:</b>\n"
        f"  Budget  {_bar(budget_pct)} <b>{budget_pct:.0f}%</b>   (con <code>${budget_left:,.0f}</code>)\n"
        f"  DD ngay {_bar(dd_used_pct)} <b>{dd_used_pct:.0f}%</b>  (con <code>{dd_remaining:.2f}%</code>)\n"
        f"  Lenh mo : <b>{open_positions}</b>\n\n"
        f"\u26a0\ufe0f <b>Lenh cua Gac Cong:</b>\n"
        f"  \u2192 Ngung mo lenh moi\n"
        f"  \u2192 Kiem tra SL tat ca vi the dang chay\n"
        f"  \u2192 Neu thi truong khong ro huong: DONG TRUOC, hoi sau\n\n"
        f"<i>Damping Throttle da kich hoat. Volume tu dong bi giam.</i>"
    )
    await push_to_telegram(chat_id, text, disable_notification=False)


async def send_defcon1_limit_warning(chat_id: str, trader_name: str,
                                      current_dd_pct: float, limit_pct: float,
                                      loss_amount: float, budget_remaining: float,
                                      open_positions: int):
    """
    Sat nguong — chi con buffer < 20% truoc khi SCRAM.
    Cuc ky chi tiet: so tien, %, lenh dang mo.
    """
    buffer_pct = round((limit_pct - current_dd_pct) / limit_pct * 100, 1) if limit_pct > 0 else 0.0
    dd_bar     = _bar(current_dd_pct / limit_pct * 100 if limit_pct > 0 else 0)

    text = (
        f"\U0001f534 <b>[ CRITICAL THRESHOLD ]</b>  <code>{_ts()}</code>\n"
        f"\U0001f464 <code>{trader_name}</code>\n"
        f"══════════════════════\n"
        f"\u2622\ufe0f  Nguong huy diet    : <b>{limit_pct}%</b>\n"
        f"\U0001f4c9  DD hien tai        : <b>{current_dd_pct:.2f}%</b>\n"
        f"    {dd_bar}  <code>{current_dd_pct:.2f}% / {limit_pct}%</code>\n\n"
        f"\u26a0\ufe0f  Buffer con lai     : <b>~{buffer_pct:.0f}%</b>  \u2248 <code>${abs(budget_remaining):,.0f}</code>\n"
        f"\U0001f4b8  Ton that hom nay  : <code>-${abs(loss_amount):,.2f}</code>\n"
        f"\U0001f4cc  Lenh dang mo      : <b>{open_positions}</b>\n\n"
        f"\U0001f6a8 <b>LENH KHAN CAP:</b>\n"
        f"  1. DONG NGAY cac lenh dang lo\n"
        f"  2. Khong mo them BAT KY lenh nao\n"
        f"  3. Them 1 lenh lo nua \u2192 SCRAM tu dong kich hoat\n\n"
        f"<i>Ban dang dung tren ranh gioi. Mot quyet dinh sai se huy ca ngay.</i>"
    )
    await push_to_telegram(chat_id, text, disable_notification=False)


# ══════════════════════════════════════════════
# 4. SCRAM — LOCK CUNG
# ══════════════════════════════════════════════

async def send_defcon1_scram(chat_id: str, trader_name: str, loss_amount: float,
                              trigger: str = "DAILY_DD",
                              daily_dd_pct: float = 0.0,
                              max_daily_dd_pct: float = 5.0,
                              total_dd_pct: float = 0.0,
                              max_total_dd_pct: float = 10.0):
    """
    SCRAM — tai khoan bi lock cung.
    trigger: DAILY_DD | TOTAL_DD | MANUAL
    """
    trigger_map = {
        "DAILY_DD":  ("\U0001f4c9 Daily DD",  f"{daily_dd_pct:.2f}%",  f"gioi han {max_daily_dd_pct}%/ngay"),
        "TOTAL_DD":  ("\u2622\ufe0f Total DD", f"{total_dd_pct:.2f}%",  f"gioi han {max_total_dd_pct}% tu dinh"),
        "MANUAL":    ("\U0001f512 Manual Kill", "\u2014",               "Admin kich hoat thu cong"),
    }
    trig_label, trig_val, trig_desc = trigger_map.get(trigger, trigger_map["DAILY_DD"])

    text = (
        f"\u2622\ufe0f <b>[ SCRAM PROTOCOL ACTIVATED ]</b> \u2622\ufe0f  <code>{_ts()}</code>\n"
        f"\U0001f464 <code>{trader_name}</code>\n"
        f"══════════════════════\n"
        f"<b>PHAN QUYET: ACCOUNT LOCKED</b>\n\n"
        f"\u26a1  Trigger   : {trig_label}\n"
        f"\U0001f4ca  Gia tri   : <b>{trig_val}</b>  ({trig_desc})\n"
        f"\U0001f4b8  Ton that  : <code>-${abs(loss_amount):,.2f}</code>\n\n"
        f"\U0001f512 <b>Trang thai:</b> HARD-LOCKED \u2014 Lenh moi bi chan hoan toan\n\n"
        f"\U0001f4cb <b>Nhat ky su kien:</b>\n"
        f"  \u2022 Daily DD  : <code>{daily_dd_pct:.2f}%</code>  /  limit <code>{max_daily_dd_pct}%</code>\n"
        f"  \u2022 Total DD  : <code>{total_dd_pct:.2f}%</code>  /  limit <code>{max_total_dd_pct}%</code>\n\n"
        f"<b>QUY TRINH PHUC HOI:</b>\n"
        f"  1. Chap nhan ket qua \u2014 khong phan tich trong cam xuc\n"
        f"  2. Nghi ngoi toi thieu 30 phut\n"
        f"  3. Tai khoan tu mo khoa luc Rollover\n"
        f"  4. Tuyet doi khong giao dich tra thu\n\n"
        f"<i>Gac Cong da hoan thanh nhiem vu.</i>"
    )
    await push_to_telegram(chat_id, text, disable_notification=False)


# ══════════════════════════════════════════════
# 5. COMPLIANCE VIOLATIONS
# ══════════════════════════════════════════════

async def send_compliance_alert(chat_id: str, trader_name: str, violations: list):
    """Vi pham ky luat — neu ro: cai gi, ngan quy, phai sua gi."""
    rows = []
    for v in violations:
        sev      = v.get("severity", "HIGH")
        sev_icon = "\U0001f6a8" if sev == "CRITICAL" else ("\U0001f534" if sev == "HIGH" else "\U0001f7e1")
        detail   = v.get("detail", "Vi pham nguyen tac")
        action   = v.get("action", "")
        row      = f"{sev_icon} <b>[{sev}]</b> {detail}"
        if action:
            row += f"\n       \u2192 <i>{action}</i>"
        rows.append(row)

    c_crit = sum(1 for v in violations if v.get("severity") == "CRITICAL")
    c_high = sum(1 for v in violations if v.get("severity") == "HIGH")

    text = (
        f"\U0001f6a8 <b>[ COMPLIANCE VIOLATION ]</b>  <code>{_ts()}</code>\n"
        f"\U0001f464 <code>{trader_name}</code>\n"
        f"══════════════════════\n"
        f"AI Guard phat hien <b>{len(violations)}</b> vi pham "
        f"(<code>{c_crit} CRITICAL</code>  \u00b7  <code>{c_high} HIGH</code>)\n\n"
        f"{chr(10).join(rows)}\n\n"
        f"\u26a1 <b>Hanh dong bat buoc:</b>\n"
        f"  \u2192 Dat lai SL cho tat ca lenh dang mo\n"
        f"  \u2192 Xem lai Compliance Panel tren Radar\n\n"
        f"<i>Audit Log da ghi nhan. Vi pham tich luy anh huong DNA Score.</i>"
    )
    await push_to_telegram(chat_id, text, disable_notification=False)


# ══════════════════════════════════════════════
# 6. AI GUARD OVERRIDE
# ══════════════════════════════════════════════

async def send_aiguard_config_change(chat_id: str, trader_name: str,
                                      param_name: str, old_val: str, new_val: str, reason: str):
    text = (
        f"\U0001f6e1\ufe0f <b>[ AIGUARD OVERRIDE ]</b>  <code>{_ts()}</code>\n"
        f"\U0001f464 <code>{trader_name}</code>\n"
        f"&#9141;&#9141;&#9141;&#9141;&#9141;&#9141;&#9141;&#9141;\n"
        f"\U0001f527 Tham so   : <b>{param_name}</b>\n"
        f"\U0001f4c9 Truoc     : <code>{old_val}</code>\n"
        f"\U0001f4c8 Sau       : <code>{new_val}</code>\n\n"
        f"\U0001f9e0 <b>Phan tich AI:</b>\n"
        f"<i>{reason}</i>\n\n"
        f"<i>Thay doi co hieu luc ngay. Xem MacroModal de chi tiet.</i>"
    )
    await push_to_telegram(chat_id, text, disable_notification=False)


# ══════════════════════════════════════════════
# 7. REGIME / WORST TRADE
# ══════════════════════════════════════════════

async def send_regime_worst_trade(chat_id: str, trader_name: str,
                                   ticket: str, symbol: str,
                                   pnl: float, reason: str,
                                   regime: str = "UNKNOWN",
                                   fit_score: float = 0.0):
    text = (
        f"\U0001f6a8 <b>[ WORST TRADE DETECTED ]</b>  <code>{_ts()}</code>\n"
        f"\U0001f464 <code>{trader_name}</code>\n"
        f"══════════════════════\n"
        f"\U0001f3f7  Lenh     : <code>#{ticket}</code>  {symbol}\n"
        f"\U0001fa78  Ton that : <b>-${abs(pnl):,.2f}</b>\n"
        f"\U0001f300  Regime   : <code>{regime}</code>  |  Fit Score: <b>{fit_score:.0f}/100</b>\n\n"
        f"\U0001f50d <b>Chan doan AI:</b>\n"
        f"<i>\"{reason}\"</i>\n\n"
        f"\U0001f4cc <b>Bai hoc can rut:</b>\n"
        f"  \u2192 Kiem tra lai Market Sensor truoc khi vao lenh\n"
        f"  \u2192 Fit Score < 50 = regime khong ung ho \u2192 KHONG NEN vao\n\n"
        f"<i>Du lieu da dua vao AI training. Sai lam nay se day AI bao ve ban tot hon.</i>"
    )
    await push_to_telegram(chat_id, text, disable_notification=False)


# ══════════════════════════════════════════════
# 8. SESSION DEBRIEF
# ══════════════════════════════════════════════

async def send_session_debrief(chat_id: str, debrief_text: str):
    """Bao cao tong ket phien tu Cockpit.js — legacy wrapper."""
    text = (
        f"\U0001f4ca <b>[ END OF SESSION DEBRIEF ]</b>  <code>{_ts()}</code>\n"
        f"══════════════════════\n"
        f"{debrief_text}\n"
        f"══════════════════════\n"
        f"<i>Radar chuan bi ngu dong. Reset ngan sach luc Rollover.</i>"
    )
    await push_to_telegram(chat_id, text, disable_notification=False)


async def send_detailed_debrief(chat_id: str, trader_name: str,
                                 pnl: float, trades: int, wins: int,
                                 compliance_score: int, violations_count: int,
                                 daily_dd_hit_pct: float, max_daily_dd_pct: float,
                                 avg_rr: float, planned_rr: float):
    """
    Debrief chi tiet — so sanh ke hoach vs thuc te.
    Giup trader thay ngay gap de cai thien phien sau.
    """
    win_rate    = round(wins / trades * 100, 1) if trades > 0 else 0.0
    pnl_str     = f"+${pnl:,.2f}" if pnl >= 0 else f"-${abs(pnl):,.2f}"
    result_icon = "\U0001f3c6" if (pnl > 0 and compliance_score >= 80) else ("\u2705" if pnl > 0 else ("\u26a0\ufe0f" if pnl == 0 else "\u274c"))
    score_icon  = "\U0001f7e2" if compliance_score >= 85 else ("\U0001f7e1" if compliance_score >= 60 else "\U0001f534")
    dd_bar      = _bar(daily_dd_hit_pct / max_daily_dd_pct * 100 if max_daily_dd_pct > 0 else 0)
    rr_delta    = avg_rr - planned_rr
    rr_note     = f"+{rr_delta:.2f} \u2191 vuot ke hoach" if rr_delta >= 0 else f"{rr_delta:.2f} \u2193 duoi ke hoach"

    if compliance_score >= 85 and pnl > 0:
        verdict = "Ky luat xuat sac. Loi nhuan den tu he thong, khong phai may man."
    elif compliance_score >= 85 and pnl <= 0:
        verdict = "Ky luat tot du thua. Thi truong khong phai luc nao cung hop tac. Giu he thong."
    elif compliance_score < 60 and pnl > 0:
        verdict = "Loi nhung pha ky luat. Day la loi nhuan may man \u2014 nguy hiem hon thua lo."
    else:
        verdict = "Vua thua vua pha ky luat. Phien can xem lai toan bo quy trinh."

    text = (
        f"{result_icon} <b>[ SESSION DEBRIEF ]</b>  <code>{_ts()}</code>\n"
        f"\U0001f464 <code>{trader_name}</code>\n"
        f"══════════════════════\n"
        f"\U0001f4b0  P&L ngay      : <b>{pnl_str}</b>\n"
        f"\U0001f4ca  Lenh W/T      : <code>{wins}/{trades}</code>  \u2192  WR <b>{win_rate:.0f}%</b>\n"
        f"\U0001f4d0  R:R thuc/ke   : <code>{avg_rr:.2f}</code> / <code>{planned_rr:.2f}</code>  (<i>{rr_note}</i>)\n\n"
        f"\U0001f6e1\ufe0f  <b>Ky luat:</b>\n"
        f"  {score_icon} Compliance  : <b>{compliance_score}/100</b>\n"
        f"  \U0001f4cb Vi pham      : <code>{violations_count}</code>\n"
        f"  \U0001f4c9 Max DD hit   : {dd_bar}  <code>{daily_dd_hit_pct:.2f}% / {max_daily_dd_pct}%</code>\n\n"
        f"<i>\U0001f4dd {verdict}</i>\n"
        f"<i>Radar di vao Sleep Mode. Hen gap lai luc Rollover.</i>"
    )
    await push_to_telegram(chat_id, text, disable_notification=False)


# ══════════════════════════════════════════════
# 9. SECURITY ALERTS (tu ea_router)
# ══════════════════════════════════════════════

async def send_security_alert(chat_id: str, account_id: str, event: str, detail: str):
    """Canh bao bao mat: CLONE_DETECTED, INVALID_CHALLENGE, RATE_LIMIT_HIT, REVOKE_EXECUTED."""
    event_map = {
        "CLONE_DETECTED":    ("\U0001f575\ufe0f", "EA CLONE DETECTED",    "Co thiet bi la dang nhap cung tai khoan"),
        "INVALID_CHALLENGE": ("\U0001f510",       "CHALLENGE FAILED",     "EA khong xac thuc duoc \u2014 co the bi gia mao"),
        "RATE_LIMIT_HIT":    ("\u26a1",           "RATE LIMIT EXCEEDED",  "EA gui request bat thuong \u2014 kha nang bi lam dung"),
        "REVOKE_EXECUTED":   ("\U0001f512",       "SESSION REVOKED",      "Admin da thu hoi phien ket noi EA"),
        "LICENSE_EXPIRED":   ("\u231b",           "LICENSE EXPIRED",      "Ban quyen het han \u2014 EA bi tu choi ket noi"),
    }
    icon, title, desc = event_map.get(event, ("\u26a0\ufe0f", event, detail))

    text = (
        f"{icon} <b>[ SECURITY: {title} ]</b>  <code>{_ts()}</code>\n"
        f"Account: <code>{account_id}</code>\n"
        f"══════════════════════\n"
        f"\U0001f4cb Su kien  : <b>{desc}</b>\n"
        f"\U0001f4dd Chi tiet : <i>{detail}</i>\n\n"
        f"<i>Security log da ghi nhan. Kiem tra EA va ket noi broker.</i>"
    )
    await push_to_telegram(chat_id, text, disable_notification=False)


# ══════════════════════════════════════════════
# 10. BACKWARD COMPAT
# ══════════════════════════════════════════════
async def send_daily_z_report(*args, **kwargs): pass