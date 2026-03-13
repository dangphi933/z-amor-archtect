# 🧠 ZARMOR AI AGENT SYSTEM — KIẾN TRÚC TÁI THIẾT KẾ TOÀN DIỆN

---

## TRIẾT LÝ HỆ THỐNG MỚI

> **"Không phải 3 modal riêng lẻ — mà là 1 AI Agent duy nhất với 3 lớp nhận thức."**

```
┌─────────────────────────────────────────────────────────────┐
│                    ZARMOR AI AGENT CORE                      │
│                                                             │
│  [LAYER 1: IDENTITY]     SetupModal                         │
│  "Tôi là ai, tôi giao dịch ở đâu, giới hạn vật lý của tôi" │
│           ↓ feeds into                                       │
│  [LAYER 2: COGNITION]    MacroModal                         │
│  "Tôi đã làm gì, đang làm gì, sẽ làm gì"                   │
│           ↓ learned by                                       │
│  [LAYER 3: CONSCIENCE]   AiGuardCenter                      │
│  "AI học từ lịch sử, cảnh báo lệch chuẩn, tối ưu hóa Edge" │
└─────────────────────────────────────────────────────────────┘
```

---

## I. SETUPMODAL — "IDENTITY LAYER" (GIỮ NGUYÊN PHẦN LỚN)

### Vấn đề hiện tại
SetupModal đang làm tốt vai trò Identity. Chỉ cần thêm **1 cơ chế quan trọng**:

### Thêm mới: `SESSION_CONTRACT` — Bản khế ước đầu phiên

Khi user Save Setup, ngoài việc lock config, hệ thống cần lưu thêm **Session Snapshot**:

```json
// localStorage key: `zarmor_session_${accountId}_${date}`
{
  "session_id": "uuid",
  "opened_at": "2025-01-15T07:00:00",
  "setup_contract": {
    "daily_budget": 150,
    "max_dd": 10.0,
    "dd_type": "STATIC",
    "consistency": 97,
    "rollover_hour": 0
  },
  "status": "ACTIVE"  // ACTIVE | COMPLETED | VIOLATED
}
```

**Tác động**: MacroModal và AiGuardCenter sẽ đọc `session_contract` này để **kiểm tra tuân thủ theo thời gian thực**.

### UI Change (nhỏ): Thêm "Session Health Bar" vào header SetupModal

```
┌──────────────────────────────────────────────────┐
│ [QUANTUM SECURE CALIBRATION V7.5]                │
│ ████████████░░░░ SESSION #47 | 6h12m active      │
│ CONTRACT: HONORED ✅  |  VIOLATIONS: 0           │
└──────────────────────────────────────────────────┘
```

---

## II. MACROMODAL — "COGNITION LAYER" (TÁI THIẾT KẾ LỚN)

### Triết lý mới: Không gian 3 chiều thời gian

MacroModal phải trở thành nơi trader **nhìn thấy toàn bộ hành trình của mình** — không chỉ là form nhập mục tiêu.

```
┌──────────────────────────────────────────────────────────────────┐
│  WAR ROOM: MACRO STRATEGY BUILDER                    [X]         │
│  ─────────────────────────────────────────────────────────────── │
│                                                                  │
│  [STATUS BAR] Armed/Disarmed | Session Contract | AI Health     │
│                                                                  │
│  ┌─────────────────┐  ┌──────────────────────────────────────┐  │
│  │                 │  │                                      │  │
│  │  LEFT PANEL     │  │  RIGHT PANEL: THE CONTINUUM          │  │
│  │  (Control)      │  │  (3 Temporal Zones)                  │  │
│  │                 │  │                                      │  │
│  │  [1] THE GOAL   │  │  ┌─────────┬──────────┬──────────┐   │  │
│  │  [2] THE EDGE   │  │  │  PAST   │ PRESENT  │  FUTURE  │   │  │
│  │  [3] VALIDATOR  │  │  │ HISTORY │  TODAY   │ FORECAST │   │  │
│  │                 │  │  └─────────┴──────────┴──────────┘   │  │
│  │  [METRICS]      │  │                                      │  │
│  │  4 KPI Cards    │  │  [A] Edge Matrix                     │  │
│  │                 │  │  [B] Monte Carlo (scrollable)        │  │
│  │                 │  │  [C] The Continuum (enhanced)        │  │
│  │                 │  │  [D] NEW: Trade Pattern Heatmap      │  │
│  │                 │  │  [E] NEW: Strategy DNA Fingerprint   │  │
│  └─────────────────┘  └──────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### Chi tiết các module mới trong MacroModal

#### [D] TRADE PATTERN HEATMAP (MỚI)
Lưới 7×24 (ngày × giờ), mỗi ô màu sắc theo winrate trung bình:
- Đỏ đậm = giờ thua nhiều nhất
- Xanh đậm = giờ thắng nhiều nhất
- Dữ liệu đọc từ localStorage `zarmor_trade_history_${accountId}`

```
       00 01 02 03 04 05 06 07 08 09 10 11 12 13 14 15...
Mon  [ ██ ██ ░░ ░░ ░░ ▒▒ ██ ██ ██ ▓▓ ▓▓ ▓▓ ░░ ▒▒ ██ ██ ]
Tue  [ ██ ░░ ░░ ░░ ░░ ░░ ▒▒ ██ ██ ██ ██ ▓▓ ▓▓ ██ ██ ██ ]
...
```
→ **Mục đích**: Cho trader thấy pattern thời gian của chiến lược, AI dùng để đề xuất "Session Window" tối ưu.

#### [E] STRATEGY DNA FINGERPRINT (MỚI)
Radar chart 6 chiều đánh giá toàn bộ phong cách giao dịch:
- **Consistency** (Tính nhất quán R:R)
- **Discipline** (Tỷ lệ tuân thủ Setup)
- **Timing** (Độ chính xác Entry trong giờ tốt)
- **Recovery** (Khả năng phục hồi sau thua)
- **Edge Strength** (Kelly Factor trung bình)
- **Risk Control** (% phiên không vi phạm Max DD)

→ Được tính từ lịch sử session được AI Guard lưu lại.

#### THE CONTINUUM — Enhanced
Thay vì chỉ 1 đường, chia rõ 3 vùng bằng màu nền:

```
│ VÙNG QUÁ KHỨ (Dữ liệu thực)  │ NOW │  VÙNG TƯƠNG LAI (AI Forecast)  │
│  màu nền #040608               │ ▲   │  màu nền #060408               │
│  đường solid, dày              │     │  5 đường mờ Monte Carlo        │
│  kèm drawdown markers          │     │  + AI "Best Path" đặc biệt     │
└────────────────────────────────┘     └────────────────────────────────┘
```

---

## III. AIGUARDCENTER — "CONSCIENCE LAYER" (TÁI THIẾT KẾ TOÀN PHẦN)

### Triết lý mới: Từ "Form chỉnh thông số" → "AI Agent biết suy nghĩ"

AiGuardCenter không còn là nơi user kéo slider chọn archetype. Nó trở thành **màn hình não bộ của AI**, nơi trader thấy được:
1. AI đang "nghĩ" gì về họ
2. AI đã học được gì từ lịch sử
3. AI đề xuất điều chỉnh gì và tại sao

### LAYOUT MỚI: 3 Cột

```
┌──────────────────────────────────────────────────────────────────────┐
│  ⚖️ AI GUARD CENTER — CONSCIENCE ENGINE              [X]            │
│  ─────────────────────────────────────────────────────────────────── │
│                                                                      │
│  ┌──────────────────┐ ┌──────────────────┐ ┌───────────────────┐   │
│  │  COL 1: MEMORY   │ │  COL 2: ANALYSIS │ │  COL 3: DIRECTIVES│   │
│  │  (AI đã học)     │ │  (AI đang nghĩ)  │ │  (AI đề xuất)     │   │
│  │                  │ │                  │ │                   │   │
│  │ [SESSION LOG]    │ │ [COMPLIANCE]     │ │ [CONSTITUTION]    │   │
│  │ Timeline các     │ │ Heatmap tuân thủ │ │ Archetype đề xuất │   │
│  │ session đã qua   │ │ Setup contract   │ │ Kelly mode        │   │
│  │                  │ │                  │ │ Max DD            │   │
│  │ [PATTERN]        │ │ [EDGE DRIFT]     │ │                   │   │
│  │ AI phát hiện     │ │ WR & RR thực tế  │ │ [ALERTS]          │   │
│  │ habits tốt/xấu   │ │ vs. kế hoạch     │ │ Danh sách cảnh    │   │
│  │                  │ │                  │ │ báo đang active   │   │
│  │ [SCORE]          │ │ [RISK AUDIT]     │ │                   │   │
│  │ Strategy DNA     │ │ Những lần vi     │ │ [SAVE MINDSET]    │   │
│  │ qua các phiên    │ │ phạm đã xảy ra   │ │                   │   │
│  └──────────────────┘ └──────────────────┘ └───────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## IV. CƠ CHẾ AI AGENT — DATA FLOW & LEARNING LOOP

### 4.1 Bộ nhớ AI (localStorage schema)

```javascript
// TRADE HISTORY — mỗi lệnh được ghi lại
localStorage.setItem(`zarmor_trades_${accountId}`, JSON.stringify([
  {
    id: "uuid",
    session_id: "...",
    timestamp: 1705123456789,
    symbol: "XAUUSD",
    direction: "BUY",
    entry_price: 2024.50,
    sl_price: 2020.00,       // Risk tính được: 4.5 pip
    tp_price: 2033.00,       // Reward: 8.5 pip → R:R 1:1.89
    result: "WIN" | "LOSS" | "BE",
    actual_rr: 1.89,
    planned_rr: 2.0,         // So sánh planned vs actual
    risk_amount: 45.00,
    hour_of_day: 9,
    day_of_week: 1,
    setup_id: "...",         // Link đến setup contract
    deviation_score: 0.05    // 0 = tuân thủ 100%, 1 = vi phạm hoàn toàn
  }
]))

// SESSION HISTORY — mỗi phiên
localStorage.setItem(`zarmor_sessions_${accountId}`, JSON.stringify([
  {
    session_id: "uuid",
    date: "2025-01-15",
    opening_balance: 10000,
    closing_balance: 10145,
    pnl: 145,
    contract: { daily_budget: 150, max_dd: 10.0 },
    actual_max_dd_hit: 3.2,   // Drawdown thực tế lớn nhất
    trades_count: 5,
    wins: 3, losses: 2,
    actual_wr: 60,
    planned_wr: 55,
    actual_rr_avg: 1.8,
    planned_rr: 2.0,
    compliance_score: 94,     // 0-100: mức tuân thủ setup
    violations: [],           // ["OVER_BUDGET", "MANUAL_OVERRIDE"]
    archetype_used: "SNIPER",
    kelly_mode: "HALF_KELLY"
  }
]))
```

### 4.2 AI Learning Engine (chạy trong AiGuardCenter)

```javascript
// Hàm phân tích pattern từ lịch sử
function analyzeTraderDNA(sessions, trades) {
  // 1. Tính Strategy DNA Score (6 chiều)
  const consistency = calcRRConsistency(trades);        // std dev của actual_rr
  const discipline = avg(sessions.map(s => s.compliance_score));
  const timing = calcTimingScore(trades);               // win% theo hour/day
  const recovery = calcRecoveryScore(sessions);         // recover sau losing streak
  const edgeStrength = calcKellyAvg(sessions);
  const riskControl = sessions.filter(s => s.actual_max_dd_hit < s.contract.max_dd).length / sessions.length * 100;

  // 2. Phát hiện Bad Habits
  const badHabits = [];
  if (calcRevengeTradeRate(trades) > 0.15) badHabits.push("REVENGE_TRADING");
  if (calcOvertradingRate(sessions) > 0.2) badHabits.push("OVERTRADING");
  if (calcTPMovingRate(trades) > 0.3) badHabits.push("MOVING_TP_EARLY");

  // 3. AI Đề xuất điều chỉnh
  const recommendations = [];
  if (actual_wr_avg > planned_wr + 10) recommendations.push({
    type: "UPGRADE_KELLY", 
    reason: "WinRate thực tế vượt kế hoạch 10%+. Có thể nâng Kelly lên FULL_KELLY."
  });
  if (timing.worst_hours.length > 0) recommendations.push({
    type: "SESSION_WINDOW",
    reason: `AI phát hiện bạn thua liên tiếp trong khung ${timing.worst_hours.join(',')}h. Xem xét không giao dịch khung này.`
  });

  return { dna: { consistency, discipline, timing, recovery, edgeStrength, riskControl }, badHabits, recommendations };
}
```

### 4.3 Compliance Monitor (chạy real-time)

Được gọi từ Cockpit mỗi lần có lệnh mới, kiểm tra:

```javascript
function checkCompliance(newTrade, currentSession, setupContract) {
  const violations = [];
  
  // 1. Budget violation
  if (newTrade.risk_amount > setupContract.daily_budget) {
    violations.push({ type: "OVER_BUDGET", severity: "HIGH", detail: `Risk $${newTrade.risk_amount} > Budget $${setupContract.daily_budget}` });
  }
  
  // 2. R:R violation (so với MacroModal plan)
  const macroRR = macroContract.historical_rr;
  if (newTrade.planned_rr < macroRR * 0.7) {
    violations.push({ type: "POOR_RR", severity: "MEDIUM", detail: `R:R ${newTrade.planned_rr} thấp hơn 30% so với kế hoạch MacroModel` });
  }
  
  // 3. Drawdown violation  
  if (currentDrawdown >= setupContract.max_dd * 0.8) {
    violations.push({ type: "DD_WARNING", severity: "CRITICAL", detail: `Đã chạm ${currentDrawdown.toFixed(1)}% / ${setupContract.max_dd}% Max DD` });
  }
  
  return violations;
}
```

---

## V. LUỒNG VẬN HÀNH HOÀN CHỈNH (USER JOURNEY)

```
ĐẦU NGÀY (Trader mở app)
        │
        ▼
[SETUPMODAL] — Xem lại/Lock Setup → Tạo session_contract
        │
        ▼
[MACROMODAL] — Xem Strategy DNA hôm qua → Thiết kế kế hoạch hôm nay
        │    → Quantum Validator kiểm tra → ARM hệ thống
        │
        ▼
[COCKPIT] — Giao dịch thực tế → mỗi lệnh ghi vào trade_history
        │                       → Compliance monitor check real-time
        │                       → AI alert nếu vi phạm
        │
        ▼
[AIGUARDCENTER] — Mở bất kỳ lúc nào
        │  → Xem AI đã học gì từ các phiên qua
        │  → Xem compliance hôm nay
        │  → Đọc AI đề xuất điều chỉnh chiến lược
        │  → Điều chỉnh Constitution nếu cần (sau khi xem evidence)
        │
        ▼
CUỐI NGÀY (Rollover)
        │
        ▼
[AI AUTO-DEBRIEF] — Tự động tính toán session score
        │           → Cập nhật Strategy DNA
        │           → Lưu session vào history
        │           → Gửi Telegram: "Debrief Report"
        │
        ▼
Lặp lại ngày hôm sau với dữ liệu đã học
```

---

## VI. CHI TIẾT TÁI THIẾT KẾ GIAO DIỆN AIGUARDCENTER

### Layout: 3 cột, chiều rộng 1100px

#### CỘT 1: MEMORY BANK (AI Đã Học)

```
┌─────────────────────────────┐
│ 🧠 MEMORY BANK              │
│ 23 sessions analyzed         │
│                              │
│ SESSION TIMELINE             │
│ ┌──────────────────────┐     │
│ │ Today    ░░░░ 94%    │     │  ← compliance score
│ │ 14/01    ████ 87%    │     │
│ │ 13/01    ██░░ 61%    │  ⚠️ │  ← violation flag
│ │ 12/01    ████ 92%    │     │
│ │ 11/01    ████ 98%    │     │
│ └──────────────────────┘     │
│ [VIEW ALL SESSIONS]          │
│                              │
│ BAD HABITS DETECTED          │
│ ┌──────────────────────┐     │
│ │ ⚡ REVENGE TRADING   │     │
│ │ 3/23 sessions (13%)  │     │
│ │ Thường xảy ra sau    │     │
│ │ 2+ lệnh thua liên tục│     │
│ └──────────────────────┘     │
│                              │
│ STRATEGY DNA SCORE           │
│ [Radar chart 6 chiều]        │
│ Overall: 78/100 ▲+4          │
└─────────────────────────────┘
```

#### CỘT 2: LIVE ANALYSIS (AI Đang Nghĩ)

```
┌─────────────────────────────┐
│ ⚡ LIVE ANALYSIS             │
│ Last updated: 2 min ago      │
│                              │
│ COMPLIANCE HEATMAP           │
│ (7 ngày × 24 giờ)           │
│ [Color grid: green/red]      │
│                              │
│ EDGE DRIFT MONITOR           │
│ ┌──────────────────────┐     │
│ │ WinRate              │     │
│ │ Planned:  55%        │     │
│ │ Actual:   61% ▲ +6%  │     │  ← tốt
│ │                      │     │
│ │ R:R Ratio            │     │
│ │ Planned:  2.0        │     │
│ │ Actual:   1.7  ▼-15% │     │  ← cảnh báo
│ └──────────────────────┘     │
│                              │
│ RISK AUDIT (THIS SESSION)    │
│ ┌──────────────────────┐     │
│ │ ✅ No violations     │     │
│ │ Budget used: 67%     │     │
│ │ DD current: 2.1%     │     │
│ │ DD capacity: 10%     │     │
│ │ [████░░░░░░] 21%     │     │
│ └──────────────────────┘     │
└─────────────────────────────┘
```

#### CỘT 3: DIRECTIVES (AI Đề Xuất)

```
┌─────────────────────────────┐
│ 📋 AI DIRECTIVES             │
│                              │
│ AI RECOMMENDATIONS           │
│ (dựa trên 23 sessions)      │
│ ┌──────────────────────┐     │
│ │ 💡 R:R đang drift    │     │
│ │ xuống 1.7. AI đề xuất│     │
│ │ tăng TP target hoặc  │     │
│ │ giảm SL.             │     │
│ │ [APPLY TO MACRO →]   │     │
│ └──────────────────────┘     │
│                              │
│ CONSTITUTION (Manual)        │
│ [1] IDENTITY ────────────── │
│ [select archetype]           │
│                              │
│ [2] KELLY MODE ─────────── │
│ [select kelly]               │
│                              │
│ [3] HARD LIMITS ──────────  │
│ Max DD: [slider] 10%         │
│ Mode: [STATIC/TRAILING]      │
│                              │
│ ACTIVE ALERTS                │
│ ┌──────────────────────┐     │
│ │ 🟡 R:R drift >10%   │     │
│ │ 🟢 Budget on track  │     │
│ │ 🟢 DD within limits │     │
│ └──────────────────────┘     │
│                              │
│ [SAVE MINDSET]               │
└─────────────────────────────┘
```

---

## VII. API ENDPOINTS CẦN THÊM (Backend)

```python
# Lưu trade vào history
POST /api/log-trade
{ account_id, trade_data }

# Lưu session kết thúc
POST /api/close-session
{ account_id, session_summary }

# Lấy AI analysis
GET /api/ai-analysis/{account_id}
→ { dna_score, bad_habits, recommendations, compliance_history }

# Check compliance real-time
POST /api/check-compliance
{ account_id, trade_proposal }
→ { approved: bool, violations: [], warnings: [] }
```

---

## VIII. IMPLEMENTATION ROADMAP

### Phase 1 (Nền tảng — 1 tuần)
- [ ] Thêm `SESSION_CONTRACT` schema vào SetupModal
- [ ] Xây dựng `localStorage` trade/session history
- [ ] Thêm compliance check function vào Cockpit

### Phase 2 (AI Learning — 1 tuần)
- [ ] Xây dựng `analyzeTraderDNA()` engine
- [ ] Redesign AiGuardCenter → 3 cột layout
- [ ] Thêm Session Timeline + Bad Habits panel

### Phase 3 (Visualization — 1 tuần)
- [ ] Thêm Trade Pattern Heatmap vào MacroModal
- [ ] Thêm Strategy DNA Radar chart
- [ ] Enhanced Continuum (3 vùng thời gian)

### Phase 4 (AI Recommendations — 1 tuần)
- [ ] AI đề xuất điều chỉnh Constitution tự động
- [ ] Telegram Debrief Report end-of-day
- [ ] Edge Drift Monitor real-time

---

## IX. TÓM TẮT THAY ĐỔI KEY THEO FILE

| File | Thay đổi | Mức độ |
|------|----------|--------|
| `SetupModal.js` | + Session Contract, + Session Health Bar | Nhỏ |
| `MacroModal.js` | + Heatmap panel, + DNA Radar, + Enhanced Continuum 3 zones | Trung bình |
| `AiGuardCenter.js` | Redesign hoàn toàn → 3 cột, AI Memory, Live Analysis, Directives | Lớn |
| `Cockpit.js` (new) | + Trade logger, + Compliance monitor, + Real-time AI alerts | Mới |
| `aiAgent.js` (new) | AI engine: analyzeTraderDNA(), checkCompliance(), generateRecommendations() | Mới |
