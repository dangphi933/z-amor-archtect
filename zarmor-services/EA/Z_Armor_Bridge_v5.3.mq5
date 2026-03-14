//+------------------------------------------------------------------+
//|                                              Z_Armor_Bridge.mq5  |
//|                        Z-ARMOR CLOUD - XÚC TU THỰC THI (MQL5 EA) |
//|                     Phiên bản: 5.3 (Advisory Mode + Radar Display)|
//+------------------------------------------------------------------+
// R-02 CHANGES vs v5.2:
//   - ParseRadarContext()   — đọc trường "radar" từ heartbeat response
//   - ParseJsonDouble()     — helper lấy số từ JSON string
//   - ParseJsonString()     — helper lấy string từ JSON string
//   - ProcessAICommands()   — thêm hiển thị radar advisory panel
//   - Comment panel: score, market_state, ea_position_pct, ea_allow_trade
//   NOTE: Vẫn là Advisory Mode — KHÔNG tự mở/đóng lệnh
#property copyright "Phi - Z-Armor Commander"
#property link      "https://z-armor.cloud"
#property version   "5.30"
#property description "Cầu nối Webhook - Chế độ quan sát + Radar Advisory Panel"

#include <Trade\Trade.mqh>
CTrade trade;

// 🌐 ĐỊA CHỈ MÁY CHỦ
input string ServerURL    = "http://47.129.1.31:8000";
input string LicenseKey   = "";          // Điền license key để kích hoạt radar
input string AccountSymbol = "XAUUSD";  // Symbol chính — dùng cho radar lookup

// ── Radar advisory state (hiển thị trên chart) ──────────────────
string g_radar_score       = "—";
string g_radar_state       = "—";
string g_radar_regime      = "—";
string g_radar_allow       = "—";
string g_radar_position_pct= "—";
string g_radar_sl_mult     = "—";
string g_radar_transition  = "—";
datetime g_radar_updated   = 0;

//+------------------------------------------------------------------+
//| KHỞI TẠO
//+------------------------------------------------------------------+
int OnInit() {
    Print("🚀 [Z-ARMOR v5.3] BRIDGE KHỞI ĐỘNG. Server: ", ServerURL);
    trade.SetExpertMagicNumber(999999);
    trade.SetDeviationInPoints(10);
    EventSetTimer(1);
    DrawAdvisoryPanel();
    return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason) {
    EventKillTimer();
    ObjectsDeleteAll(0, "ZA_");
    Print("🛑 [Z-ARMOR] BRIDGE NGẮT KẾT NỐI.");
}

void OnTimer() {
    if (!TerminalInfoInteger(TERMINAL_CONNECTED)) return;
    SendHeartbeat();
    SendPositions();
    // Refresh panel mỗi 10 giây
    if (TimeCurrent() % 10 == 0) DrawAdvisoryPanel();
}

//+------------------------------------------------------------------+
//| 1. HEARTBEAT
//+------------------------------------------------------------------+
void SendHeartbeat() {
    string url = ServerURL + "/ea/heartbeat";

    long   account_id = AccountInfoInteger(ACCOUNT_LOGIN);
    double balance    = AccountInfoDouble(ACCOUNT_BALANCE);
    double equity     = AccountInfoDouble(ACCOUNT_EQUITY);
    double margin     = AccountInfoDouble(ACCOUNT_MARGIN);

    double daily_pnl = 0;
    datetime today = TimeCurrent() - (TimeCurrent() % 86400);
    HistorySelect(today, TimeCurrent());
    for (int i = 0; i < HistoryDealsTotal(); i++) {
        ulong ticket = HistoryDealGetTicket(i);
        long  dtype  = HistoryDealGetInteger(ticket, DEAL_TYPE);
        if (dtype == DEAL_TYPE_BUY || dtype == DEAL_TYPE_SELL) {
            daily_pnl += HistoryDealGetDouble(ticket, DEAL_PROFIT)
                       + HistoryDealGetDouble(ticket, DEAL_COMMISSION)
                       + HistoryDealGetDouble(ticket, DEAL_SWAP);
        }
    }

    // R-02: include session_token (empty on first call — server will re-handshake)
    string json = StringFormat(
        "{\"account_id\":\"%I64d\",\"balance\":%f,\"equity\":%f,"
        "\"margin\":%f,\"daily_closed_profit\":%f,"
        "\"symbols\":\"%s\",\"tf\":\"H1\"}",
        account_id, balance, equity, margin, daily_pnl, AccountSymbol
    );

    char req[], res[]; string hdrs;
    StringToCharArray(json, req, 0, StringLen(json), CP_UTF8);

    int code = WebRequest("POST", url, "Content-Type: application/json\r\n",
                          5000, req, res, hdrs);
    if (code == 200) {
        string body = CharArrayToString(res);
        ProcessAICommands(body);
    } else {
        if (GetLastError() != 5203)
            Print("⚠️ [HEARTBEAT] HTTP: ", code, " ERR: ", GetLastError());
    }
}

//+------------------------------------------------------------------+
//| 2. POSITIONS
//+------------------------------------------------------------------+
void SendPositions() {
    string url = ServerURL + "/ea/positions";
    long   account_id = AccountInfoInteger(ACCOUNT_LOGIN);

    string json = "{\"account_id\":\"" + IntegerToString(account_id) + "\",\"positions\":[";
    int total = PositionsTotal();
    for (int i = 0; i < total; i++) {
        ulong  ticket = PositionGetTicket(i);
        string symbol = PositionGetString(POSITION_SYMBOL);
        long   ptype  = PositionGetInteger(POSITION_TYPE);
        double vol    = PositionGetDouble(POSITION_VOLUME);
        double oprice = PositionGetDouble(POSITION_PRICE_OPEN);
        double sl     = PositionGetDouble(POSITION_SL);
        double tp     = PositionGetDouble(POSITION_TP);
        double profit = PositionGetDouble(POSITION_PROFIT);

        double tv    = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
        double ts    = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
        double sl_$  = (sl > 0 && ts > 0) ? -(MathAbs(oprice - sl) / ts) * tv * vol : 0;
        double tp_$  = (tp > 0 && ts > 0) ?  (MathAbs(tp - oprice) / ts) * tv * vol : 0;

        json += StringFormat(
            "{\"ticket\":%I64u,\"symbol\":\"%s\",\"type\":%d,\"volume\":%f,"
            "\"open_price\":%f,\"sl\":%f,\"tp\":%f,\"profit\":%f,"
            "\"sl_money\":%f,\"tp_money\":%f}",
            ticket, symbol, ptype, vol, oprice, sl, tp, profit, sl_$, tp_$
        );
        if (i < total - 1) json += ",";
    }
    json += "]}";

    char req[], res[]; string hdrs;
    StringToCharArray(json, req, 0, StringLen(json), CP_UTF8);
    int code = WebRequest("POST", url, "Content-Type: application/json\r\n",
                          5000, req, res, hdrs);
    if (code != 200 && GetLastError() != 5203)
        Print("⚠️ [POSITIONS] HTTP: ", code, " ERR: ", GetLastError());
}

//+------------------------------------------------------------------+
//| 3. PROCESS AI COMMANDS + R-02: RADAR PARSE
//+------------------------------------------------------------------+
void ProcessAICommands(string response) {
    // ── Risk kill-switch (unchanged) ──────────────────────────────
    if (StringFind(response, "SCRAM") >= 0) {
        Print("🆘 [SCRAM] TÀI KHOẢN CHẠM TRẦN TỬ THỦ! EA ở Advisory Mode — vui lòng tự xử lý.");
    }

    int kill_idx = StringFind(response, "KILL_");
    while (kill_idx >= 0) {
        string sub = StringSubstr(response, kill_idx + 5);
        string tkt_str = "";
        for (int i = 0; i < StringLen(sub); i++) {
            ushort c = StringGetCharacter(sub, i);
            if (c >= '0' && c <= '9') tkt_str += ShortToString(c);
            else break;
        }
        if (StringLen(tkt_str) > 0) {
            ulong tkt = StringToInteger(tkt_str);
            if (PositionSelectByTicket(tkt))
                Print("⚠️ [ADVISOR] Lệnh #", tkt, " VI PHẠM RỦI RO — xem xét đóng tay.");
        }
        kill_idx = StringFind(response, "KILL_", kill_idx + 5);
    }

    // ── R-02: Parse radar context từ heartbeat response ───────────
    ParseRadarContext(response);
}

//+------------------------------------------------------------------+
//| R-02: PARSE RADAR CONTEXT
//| ZCloud heartbeat response chứa: {"radar":{"XAUUSD:H1":{...}}}
//+------------------------------------------------------------------+
void ParseRadarContext(string response) {
    // Tìm trường "radar" trong JSON response
    int radar_idx = StringFind(response, "\"radar\":");
    if (radar_idx < 0) return;

    // Tìm symbol key: AccountSymbol + ":H1" (hoặc tf được gửi)
    string symbol_key = AccountSymbol + ":H1";
    // Cũng thử map MT5 symbol → internal (XAUUSD → GOLD)
    if (AccountSymbol == "XAUUSD" || AccountSymbol == "XAUUSDM")
        symbol_key = "GOLD:H1";
    else if (AccountSymbol == "BTCUSD" || AccountSymbol == "BTCUSDM")
        symbol_key = "BTC:H1";
    else if (AccountSymbol == "NAS100" || AccountSymbol == "NAS100M")
        symbol_key = "NASDAQ:H1";

    int key_idx = StringFind(response, "\"" + symbol_key + "\"", radar_idx);
    if (key_idx < 0) return;  // Symbol not in radar map

    // Extract block từ key_idx đến next top-level key
    int block_start = StringFind(response, "{", key_idx);
    if (block_start < 0) return;

    // Count braces to get full object
    int depth = 0; int block_end = block_start;
    for (int i = block_start; i < StringLen(response); i++) {
        ushort c = StringGetCharacter(response, i);
        if (c == '{') depth++;
        else if (c == '}') { depth--; if (depth == 0) { block_end = i; break; } }
    }

    string block = StringSubstr(response, block_start, block_end - block_start + 1);

    // Extract fields
    double score     = ParseJsonDouble(block, "score");
    string state     = ParseJsonString(block, "market_state");
    string regime    = ParseJsonString(block, "regime");
    string allow_raw = ParseJsonString(block, "ea_allow_trade");
    double pos_pct   = ParseJsonDouble(block, "ea_position_pct");
    double sl_mult   = ParseJsonDouble(block, "ea_sl_multiplier");
    string trans     = ParseJsonString(block, "transition_type");

    // Update global advisory state
    g_radar_score        = IntegerToString((int)score);
    g_radar_state        = state != "" ? state : "—";
    g_radar_regime       = regime != "" ? regime : "—";
    g_radar_allow        = (allow_raw == "true" || allow_raw == "True") ? "✅ ALLOW" : "🚫 BLOCK";
    g_radar_position_pct = IntegerToString((int)pos_pct) + "%";
    g_radar_sl_mult      = DoubleToString(sl_mult, 1) + "×";
    g_radar_transition   = trans != "" ? trans : "STABLE";
    g_radar_updated      = TimeCurrent();

    // Log to journal
    Print(StringFormat(
        "[RADAR] %s | Score:%s | State:%s | Allow:%s | Pos:%s | SL:%s | Trans:%s",
        symbol_key, g_radar_score, g_radar_state,
        g_radar_allow, g_radar_position_pct, g_radar_sl_mult, g_radar_transition
    ));

    // Cảnh báo nếu radar block
    if (allow_raw == "false" || allow_raw == "False")
        Print("🔴 [RADAR BLOCK] Score=", g_radar_score,
              " — Radar khuyến nghị KHÔNG giao dịch. (Advisory only)");

    // Cảnh báo volatility shock
    if (state == "VOLATILITY_SHOCK")
        Print("⚡ [VOLATILITY SHOCK] Market state = VOLATILITY_SHOCK — nới stop hoặc đứng ngoài.");

    // Cảnh báo transition
    if (trans != "STABLE" && trans != "")
        Print("📡 [TRANSITION] ", trans, " detected — xem xét điều chỉnh sizing.");
}

//+------------------------------------------------------------------+
//| JSON HELPERS
//+------------------------------------------------------------------+
double ParseJsonDouble(string json, string key) {
    string search = "\"" + key + "\":";
    int idx = StringFind(json, search);
    if (idx < 0) return 0.0;
    int start = idx + StringLen(search);
    // Skip whitespace
    while (start < StringLen(json)) {
        ushort c = StringGetCharacter(json, start);
        if (c != ' ' && c != '\t') break;
        start++;
    }
    string num = "";
    for (int i = start; i < StringLen(json); i++) {
        ushort c = StringGetCharacter(json, i);
        if ((c >= '0' && c <= '9') || c == '.' || c == '-') num += ShortToString(c);
        else break;
    }
    return StringToDouble(num);
}

string ParseJsonString(string json, string key) {
    string search = "\"" + key + "\":\"";
    int idx = StringFind(json, search);
    if (idx < 0) {
        // Try bool value (true/false without quotes)
        string search2 = "\"" + key + "\":";
        int idx2 = StringFind(json, search2);
        if (idx2 < 0) return "";
        int start2 = idx2 + StringLen(search2);
        string val = "";
        for (int i = start2; i < MathMin(start2 + 10, StringLen(json)); i++) {
            ushort c = StringGetCharacter(json, i);
            if (c == ',' || c == '}' || c == ' ') break;
            val += ShortToString(c);
        }
        return val;
    }
    int start = idx + StringLen(search);
    string result = "";
    for (int i = start; i < StringLen(json); i++) {
        ushort c = StringGetCharacter(json, i);
        if (c == '"') break;
        result += ShortToString(c);
    }
    return result;
}

//+------------------------------------------------------------------+
//| ADVISORY PANEL — hiển thị radar data trên chart
//+------------------------------------------------------------------+
void DrawAdvisoryPanel() {
    string updated_str = (g_radar_updated > 0)
        ? TimeToString(g_radar_updated, TIME_MINUTES)
        : "chưa có dữ liệu";

    string color_score = "clrGray";
    int    score_val   = (int)StringToInteger(g_radar_score);
    if (score_val >= 85)      color_score = "clrLime";
    else if (score_val >= 70) color_score = "clrDeepSkyBlue";
    else if (score_val >= 50) color_score = "clrOrange";
    else if (score_val >= 30) color_score = "clrOrangeRed";
    else if (score_val > 0)   color_score = "clrRed";

    string allow_color = (StringFind(g_radar_allow, "ALLOW") >= 0) ? "clrLimeGreen" : "clrRed";
    string trans_color = (g_radar_transition == "STABLE" || g_radar_transition == "—")
                         ? "clrGray" : "clrOrange";

    // Lines to display
    string lines[] = {
        "═══ Z-ARMOR RADAR ADVISORY ═══",
        "Score:    " + g_radar_score + " / 100",
        "State:    " + g_radar_state,
        "Regime:   " + g_radar_regime,
        "Pos Size: " + g_radar_position_pct,
        "SL Mult:  " + g_radar_sl_mult,
        "Transition: " + g_radar_transition,
        "Status:   " + g_radar_allow,
        "Updated:  " + updated_str,
        "═══════════════════════════════",
    };

    int x = 15, y = 30;
    for (int i = 0; i < ArraySize(lines); i++) {
        string obj = "ZA_L" + IntegerToString(i);
        if (ObjectFind(0, obj) < 0)
            ObjectCreate(0, obj, OBJ_LABEL, 0, 0, 0);
        ObjectSetInteger(0, obj, OBJPROP_CORNER,    CORNER_RIGHT_UPPER);
        ObjectSetInteger(0, obj, OBJPROP_XDISTANCE, 220);
        ObjectSetInteger(0, obj, OBJPROP_YDISTANCE, y + i * 18);
        ObjectSetInteger(0, obj, OBJPROP_FONTSIZE,  9);
        ObjectSetString(0,  obj, OBJPROP_FONT,      "Courier New");
        ObjectSetString(0,  obj, OBJPROP_TEXT,       lines[i]);

        // Color logic per line
        color line_color = clrSilver;
        if (i == 0 || i == 9)              line_color = clrSteelBlue;
        else if (i == 1)                   line_color = (color)StringToInteger(color_score);
        else if (i == 7)                   line_color = (color)StringToInteger(allow_color);
        else if (i == 6)                   line_color = (color)StringToInteger(trans_color);
        ObjectSetInteger(0, obj, OBJPROP_COLOR, line_color);
    }
    ChartRedraw();
}

void OnChartEvent(const int id, const long& lparam,
                  const double& dparam, const string& sparam) {
    // Redraw panel on chart zoom/scroll
    if (id == CHARTEVENT_CHART_CHANGE) DrawAdvisoryPanel();
}
