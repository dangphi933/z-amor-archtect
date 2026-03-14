// ================================================================
// Z-ARMOR KERNEL v3.0 — Single-file build (Final)
//
// Fixes:
//   [FIX-01] models.mqh      : VOLATILE → DIR_NO_ENTRY
//   [FIX-02] panel_controller: Tab STRATEGY redesign v3.3
//            MONITOR | STRATEGY | CONTROL (3 tabs)
//            Score hero block, Gate badge, Direction badge
//            Section A/B/C/D — to hơn, rõ hơn
//   [FIX-03] _ShowTab ids1   : sync 100% với _BuildTab1 objects
//
// Setup: Tools > Options > Expert Advisors > Allow WebRequest
//        URL: http://47.129.243.206:8000
// ================================================================

#property copyright "Z-Armor Kernel v3.0"
#property version   "3.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Controls\Dialog.mqh>
#include <Controls\Label.mqh>
#include <Controls\Button.mqh>


// ============================================================================
// SECTION: core/models.mqh
// ============================================================================
// ==============================================================================
// FILE: core/models.mqh  — Z-ARMOR KERNEL v3.0
// Central data contracts. Zero MT5 dependency.
// v3.0 changes vs v2.1:
//   + ENUM_DIRECTION_MODE  (replaces direction logic in BoltVolman)
//   + ENUM_ENTRY_TYPE      (StrategyProfile entry filter)
//   + ENUM_SESSION_FLAG    (bitmask for session filter)
//   + ENUM_RISK_MODE       (profile risk cap)
//   + struct StrategyProfile  (NEW — cloud template)
//   + struct RegimeContext    (NEW — per-symbol from radar_map)
//   ~ ENUM_ALPHA_STATE kept for backward compat but deprecated
//   ~ ENUM_CAPITAL_STATE kept (CircuitBreaker still uses numeric levels)
//   ~ SystemStateSnapshot extended with direction_mode, profile_name
// ==============================================================================

#define MAX_SYMBOLS 16

// ─── Enums (legacy — kept for backward compat) ────────────────────────────────

enum ENUM_ALPHA_STATE
{
   ALPHA_OPTIMAL   = 0,   // [DEPRECATED v3.0] — use DIRECTION_MODE instead
   ALPHA_MODERATE  = 1,
   ALPHA_WEAK      = 2,
   ALPHA_BLOCKED   = 3,
};

enum ENUM_CAPITAL_STATE
{
   CAPITAL_AGGRESSIVE = 0,
   CAPITAL_STABLE     = 1,
   CAPITAL_DEFENSIVE  = 2,
   CAPITAL_SURVIVAL   = 3,
   CAPITAL_CRITICAL   = 4,  // CircuitBreaker threshold
};

enum ENUM_SYSTEM_STATE
{
   SYS_AGGRESSIVE = 0,
   SYS_NORMAL     = 1,
   SYS_DEFENSIVE  = 2,
   SYS_SURVIVAL   = 3,
   SYS_FLAT       = 4,
   SYS_LOCKED     = 5,
};

enum ENUM_REGIME
{
   REGIME_TREND_STRONG   = 0,
   REGIME_TREND_MODERATE = 1,
   REGIME_RANGE          = 2,
   REGIME_VOLATILE       = 3,
   REGIME_SQUEEZE        = 4,
   REGIME_UNCERTAIN      = 5,
};

enum ENUM_GATE_ACTION
{
   GATE_ALLOW     = 0,
   GATE_WARN      = 1,
   GATE_BLOCK     = 2,
   GATE_HARD_LOCK = 3,
};

// ─── Enums (v3.0 NEW) ─────────────────────────────────────────────────────────

// Direction cloud decides — EA just executes in the allowed direction
enum ENUM_DIRECTION_MODE
{
   DIR_BUY_ONLY  = 0,   // TREND_FOLLOWING regime — only longs
   DIR_SELL_ONLY = 1,   // TREND_FOLLOWING inverted — only shorts
   DIR_BOTH      = 2,   // RANGE_BOUND — both directions ok
   DIR_NO_ENTRY  = 3,   // AVOID / score < 30 — no new entries
};

// Entry filter in StrategyProfile — trader sets on dashboard
enum ENUM_ENTRY_TYPE
{
   ENTRY_BREAKOUT_ONLY = 0,  // Only enter on breakout bars
   ENTRY_PULLBACK_ONLY = 1,  // Only enter on pullback confirmation
   ENTRY_BOTH          = 2,  // Any valid setup
};

// Bitmask: combine with OR. eg LONDON|NY = 3
enum ENUM_SESSION_FLAG
{
   SESSION_ASIA    = 1,
   SESSION_LONDON  = 2,
   SESSION_NY      = 4,
   SESSION_WEEKEND = 8,
   SESSION_ALL     = 15,
};

// Risk mode — profile-level cap on position sizing
enum ENUM_RISK_MODE
{
   RISK_CONSERVATIVE = 0,  // position_pct capped at 60%
   RISK_NORMAL       = 1,  // position_pct used as-is (up to 100%)
   RISK_AGGRESSIVE   = 2,  // allows >100% when state=ALLOW_SCALE
};

// ─── StrategyProfile (NEW v3.0) ───────────────────────────────────────────────
// Populated from heartbeat units_config.strategy_profile JSON.
// Trader creates templates on RegimeFit Dashboard — EA never hardcodes these.

struct StrategyProfile
{
   string            profile_name;     // Display name eg "Gold Scalp H1"
   ENUM_ENTRY_TYPE   entry_type;       // BREAKOUT_ONLY | PULLBACK_ONLY | BOTH
   int               min_score_entry;  // 0-100, default 60
   int               session_filter;   // bitmask from ENUM_SESSION_FLAG
   double            rr_ratio;         // TP/SL ratio, default 2.0
   double            max_spread_pct;   // Max spread as fraction of ATR
   bool              trailing_sl;      // Trailing stop enabled
   ENUM_RISK_MODE    risk_mode;        // Risk cap override
   bool              is_loaded;        // false = no profile from cloud yet
};

// ─── RegimeContext (NEW v3.0) ─────────────────────────────────────────────────
// Per-symbol context from heartbeat radar_map.
// EA reads this every tick — populated by cloud_bridge each heartbeat.

struct RegimeContext
{
   string               symbol;
   int                  score;           // 0-100 from Zcloud
   string               regime_str;      // Raw string: "TREND_FOLLOWING" etc
   ENUM_DIRECTION_MODE  direction_mode;  // Parsed direction gate
   int                  position_pct;    // 0-125, cloud-computed
   double               sl_multiplier;   // ATR × this = SL distance
   double               damping_factor;  // Portfolio-level scaling (0.0-1.0)
   bool                 allow_trade;     // Hard gate from server
   string               state_cap;       // "OPTIMAL"/"CAUTION"/"BLOCKED"
   datetime             fetched_at;      // When this was received
   int                  ttl_sec;         // Cache validity window
   bool                 is_valid;        // false = using safe defaults
};

// ─── Instrument Specification ─────────────────────────────────────────────────

struct InstrumentSpec
{
   string   symbol;
   double   tick_size;
   double   tick_value;
   double   point;
   double   volume_min;
   double   volume_step;
   double   volume_max;
   double   spread_points;
   double   contract_size;
};

// ─── Position Snapshot ────────────────────────────────────────────────────────

struct PositionSnapshot
{
   ulong    ticket;
   string   symbol;
   int      direction;
   double   volume;
   double   entry_price;
   double   stop_loss;
   double   take_profit;
   double   current_price;
   double   unrealized_pnl;
   double   risk_money;
   long     magic;
   datetime open_time;
};

// ─── Account Snapshot ─────────────────────────────────────────────────────────

struct AccountSnapshot
{
   double   equity;
   double   balance;
   double   margin_used;
   double   margin_free;
   double   margin_level_pct;
   datetime timestamp;
};

// ─── Portfolio Snapshot ───────────────────────────────────────────────────────

struct PortfolioSnapshot
{
   AccountSnapshot  account;
   PositionSnapshot positions[];
   int              position_count;
   double           total_risk_money;
   double           total_risk_pct;
   double           net_delta;
   double           gross_exposure;
};

// ─── Market Snapshot (per symbol) ────────────────────────────────────────────

struct MarketSnapshot
{
   string         symbol;
   double         bid;
   double         ask;
   datetime       timestamp;
   InstrumentSpec spec;
   double         open[];
   double         high[];
   double         low[];
   double         close[];
   int            bar_count;
};

// ─── Entry Signal (RegimeGateFilter output) ───────────────────────────────────
// v3.0: signal has NO direction — direction comes from RegimeContext.direction_mode
// Filter only determines: is this a good time to enter? entry type matches?

struct EntrySignal
{
   string   symbol;
   bool     valid;           // true = entry timing is good
   double   strength;        // 0-100 entry quality score (timing only)
   ENUM_ENTRY_TYPE entry_type_detected; // BREAKOUT or PULLBACK (for logging)
   double   atr14;           // ATR for sizing
   double   sl_distance_atr; // SL as ATR multiples (× profile sl_multiplier)
   datetime signal_time;
   string   reject_reason;   // Why valid=false (for logging)
};

// ─── Risk Decision (LocalSafetyNet + SizingEngine → ExecutionEngine) ─────────

struct RiskDecision
{
   string               symbol;
   int                  direction;          // Final: +1 BUY / -1 SELL (from RegimeContext)
   ENUM_GATE_ACTION     gate_action;
   string               gate_reason;
   double               approved_volume;
   double               approved_sl;
   double               approved_tp;
   double               approved_risk_pct;
   double               sl_atr_multiplier;
   ENUM_SYSTEM_STATE    system_state;
   ENUM_CAPITAL_STATE   capital_state;      // kept for compat
   ENUM_ALPHA_STATE     alpha_state;        // deprecated, set to ALPHA_MODERATE
   double               z_pressure;         // from cloud heartbeat
   double               portfolio_risk_pct;
   datetime             decision_time;
};

// ─── System State Snapshot (for UI render) ────────────────────────────────────

struct SystemStateSnapshot
{
   ENUM_SYSTEM_STATE    system_state;
   ENUM_CAPITAL_STATE   capital_state;
   ENUM_ALPHA_STATE     alpha_state;        // deprecated
   ENUM_REGIME          regime;
   ENUM_DIRECTION_MODE  direction_mode;     // NEW v3.0 — shown on panel
   double               equity;
   double               balance;
   double               z_pressure;
   double               portfolio_risk_pct;
   double               daily_dd_pct;
   double               trailing_dd_pct;
   int                  trade_count_today;
   int                  loss_streak;
   bool                 cloud_locked;
   bool                 emergency;
   string               last_gate_reason;
   string               active_profile_name;  // NEW v3.0
   string               active_symbol_regime; // NEW v3.0 — first symbol regime string
   int                  cloud_score;          // NEW v3.0 — primary symbol score
   datetime             last_heartbeat;       // NEW v3.0 — cloud freshness
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

ENUM_DIRECTION_MODE ParseDirectionMode(const string &regime_str, bool allow_trade)
{
   // FIX-5: Map ZCloud radar engine regime strings → direction mode
   // ZCloud returns: STRONG_TREND, TRENDING, NEUTRAL, MEAN_REVERSION,
   //                 VOLATILE, BREAKOUT_WATCH, UNCERTAIN
   // Legacy strings (kept for backward compat): TREND_FOLLOWING, TREND_INVERTED, RANGE_BOUND
   if(!allow_trade)                                          return DIR_NO_ENTRY;

   // ZCloud regime strings
   if(regime_str == "STRONG_TREND")                         return DIR_BUY_ONLY;
   if(regime_str == "TRENDING")                             return DIR_BUY_ONLY;
   if(regime_str == "MEAN_REVERSION")                       return DIR_BOTH;
   if(regime_str == "BREAKOUT_WATCH")                       return DIR_BOTH;
   if(regime_str == "NEUTRAL")                              return DIR_BOTH;
   if(regime_str == "VOLATILE")                             return DIR_NO_ENTRY;
   if(regime_str == "UNCERTAIN")                            return DIR_NO_ENTRY;

   // Legacy strings (pre-ZCloud)
   if(StringFind(regime_str, "TREND_FOLLOW") >= 0)          return DIR_BUY_ONLY;
   if(StringFind(regime_str, "TREND_INVERT") >= 0)          return DIR_SELL_ONLY;
   if(StringFind(regime_str, "RANGE") >= 0)                 return DIR_BOTH;
   if(StringFind(regime_str, "AVOID") >= 0)                 return DIR_NO_ENTRY;

   return DIR_BOTH; // safe default
}

// Safe default RegimeContext when cloud offline
RegimeContext DefaultRegimeContext(const string &symbol)
{
   RegimeContext ctx;
   ctx.symbol         = symbol;
   ctx.score          = 50;
   ctx.regime_str     = "RANGE_BOUND";
   ctx.direction_mode = DIR_BOTH;
   ctx.position_pct   = 60;
   ctx.sl_multiplier  = 1.5;
   ctx.damping_factor = 1.0;
   ctx.allow_trade    = true;
   ctx.state_cap      = "CAUTION";
   ctx.fetched_at     = 0;
   ctx.ttl_sec        = 1800;
   ctx.is_valid       = false;
   return ctx;
}

// Default StrategyProfile when no cloud profile loaded
StrategyProfile DefaultStrategyProfile()
{
   StrategyProfile p;
   p.profile_name    = "Default";
   p.entry_type      = ENTRY_BOTH;
   p.min_score_entry = 60;
   p.session_filter  = SESSION_ALL;
   p.rr_ratio        = 2.0;
   p.max_spread_pct  = 0.5;
   p.trailing_sl     = false;
   p.risk_mode       = RISK_NORMAL;
   p.is_loaded       = false;
   return p;
}


// ============================================================================
// SECTION: core/state_machine.mqh
// ============================================================================
// ==============================================================================
// FILE: core/state_machine.mqh  — Z-ARMOR KERNEL v3.0  (lite)
// Anti-spam, cooldown, trade count, loss streak.
//
// v3.0 changes vs v2.1:
//   REMOVED: AlphaState calculation (was OPTIMAL/MODERATE/WEAK/BLOCKED)
//            → AlphaState now comes from cloud regime score
//   REMOVED: CAPITAL_STATE integration (simplified — CircuitBreaker handles it)
//   ADDED:   SetMaxTrades() / SetCooldown() setters (for runtime config update)
//   KEPT:    Anti-spam new bar per-symbol, loss streak, daily trade count
//   KEPT:    SetCloudState(locked, emergency)
// ==============================================================================


class StateMachine
{
private:
   int      m_max_trades_per_day;
   int      m_max_loss_streak;
   int      m_cooldown_seconds;

   bool     m_cloud_locked;
   bool     m_emergency;

   int      m_trade_count;
   int      m_loss_streak;
   datetime m_last_trade_time;
   int      m_last_day;

   // Per-symbol new-bar anti-spam
   string   m_sym_list[MAX_SYMBOLS];
   datetime m_sym_last_bar[MAX_SYMBOLS];
   int      m_sym_count;

   int _symSlot(const string &sym)
   {
      for(int i = 0; i < m_sym_count; i++)
         if(m_sym_list[i] == sym) return i;
      if(m_sym_count < MAX_SYMBOLS)
      {
         m_sym_list[m_sym_count]    = sym;
         m_sym_last_bar[m_sym_count] = 0;
         return m_sym_count++;
      }
      return 0;
   }

public:

   void Init(int max_trades = 20, int max_streak = 3, int cooldown = 60)
   {
      m_max_trades_per_day = max_trades;
      m_max_loss_streak    = max_streak;
      m_cooldown_seconds   = cooldown;
      m_cloud_locked       = false;
      m_emergency          = false;
      m_trade_count        = 0;
      m_loss_streak        = 0;
      m_last_trade_time    = 0;
      m_last_day           = -1;
      m_sym_count          = 0;
      ArrayInitialize(m_sym_last_bar, 0);
   }

   void SetCloudState(bool locked, bool emergency)
   {
      m_cloud_locked = locked;
      m_emergency    = emergency;
   }

   void SetMaxTrades(int v) { m_max_trades_per_day = v; }
   void SetCooldown(int v)  { m_cooldown_seconds   = v; }

   // ── Daily reset check (call once per tick) ────────────────────────────────
   void CheckDailyReset(datetime now)
   {
      MqlDateTime dt;
      TimeToStruct(now, dt);
      if(dt.day_of_year != m_last_day)
      {
         m_trade_count = 0;
         m_loss_streak = 0;
         m_last_day    = dt.day_of_year;
      }
   }

   // ── New-bar anti-spam for one symbol ──────────────────────────────────────
   bool IsNewBar(const string &sym, datetime bar_time)
   {
      int slot = _symSlot(sym);
      if(m_sym_last_bar[slot] == bar_time) return false;
      m_sym_last_bar[slot] = bar_time;
      return true;
   }

   // ── Main state evaluation for one symbol ──────────────────────────────────
   // Returns GATE_ALLOW / GATE_BLOCK / GATE_HARD_LOCK + reason string
   ENUM_GATE_ACTION Evaluate(const string &symbol, datetime now, string &reason)
   {
      CheckDailyReset(now);

      if(m_emergency)    { reason = "Emergency";    return GATE_HARD_LOCK; }
      if(m_cloud_locked) { reason = "Cloud locked"; return GATE_HARD_LOCK; }

      if(m_trade_count >= m_max_trades_per_day)
      {
         reason = StringFormat("Daily limit %d reached", m_max_trades_per_day);
         return GATE_BLOCK;
      }

      if(m_loss_streak >= m_max_loss_streak)
      {
         reason = StringFormat("Loss streak %d", m_loss_streak);
         return GATE_BLOCK;
      }

      if(m_last_trade_time > 0 && (now - m_last_trade_time) < m_cooldown_seconds)
      {
         reason = StringFormat("Cooldown %ds remaining",
                                m_cooldown_seconds - (int)(now - m_last_trade_time));
         return GATE_BLOCK;
      }

      return GATE_ALLOW;
   }

   // ── Register closed trade ─────────────────────────────────────────────────
   void RegisterTrade(datetime t, double pnl)
   {
      m_trade_count++;
      m_last_trade_time = t;
      if(pnl < 0) m_loss_streak++;
      else        m_loss_streak = 0;
   }

   // ── Getters ───────────────────────────────────────────────────────────────
   int GetTradeCount() const { return m_trade_count; }
   int GetLossStreak() const { return m_loss_streak; }
};


// ============================================================================
// SECTION: core/local_safety_net.mqh
// ============================================================================
// ==============================================================================
// FILE: core/local_safety_net.mqh  — Z-ARMOR KERNEL v3.0
// Minimal local safety layer — REPLACES RiskEngine (full 5-model version).
//
// v3.0 principle: Z-Cloud handles risk intelligence (Z-Pressure, regime).
// EA only needs a lightweight failsafe that works when cloud is offline.
//
// Kept from v2.1 RiskEngine:
//   CircuitBreaker  — hard stop when balance_dd >= threshold (CAPITAL_CRITICAL)
//   ExposureGate    — portfolio risk limit + per-symbol limit
//   StateMachine    — anti-spam, loss streak, cooldown, daily count
//
// Removed from v2.1 RiskEngine:
//   DrawdownModel elaborate  (Z-Pressure now from cloud)
//   PressureModel            (Z-Pressure from heartbeat response)
//   VolatilityModel          (ATR spike check simplified to 1 line)
//   AlphaState calculation   (replaced by direction_mode from cloud)
//   6-multiplier lot sizing  (replaced by SizingEngine 3-param formula)
//
// Consumers:
//   MultiSymbolScheduler calls Evaluate() after RegimeGateFilter
//   Returns GATE_HARD_LOCK if circuit breaker tripped
//   Returns GATE_BLOCK if exposure limit reached
//   Returns GATE_ALLOW otherwise
// ==============================================================================


class LocalSafetyNet
{
private:
   // Config
   double  m_circuit_breaker_pct;   // eg 0.03 = 3% balance drawdown → hard stop
   double  m_max_portfolio_risk;    // eg 0.05 = 5% total open risk
   double  m_max_symbol_risk;       // eg 0.02 = 2% per symbol

   // State
   double  m_balance_peak;
   bool    m_circuit_blown;
   bool    m_cloud_locked;
   bool    m_emergency;

   StateMachine m_state;

public:

   void Init(double circuit_breaker = 0.03,
             double max_port_risk   = 0.05,
             double max_sym_risk    = 0.02,
             int    max_trades      = 20,
             int    max_streak      = 3,
             int    cooldown_sec    = 60)
   {
      m_circuit_breaker_pct = circuit_breaker;
      m_max_portfolio_risk  = max_port_risk;
      m_max_symbol_risk     = max_sym_risk;
      m_balance_peak        = 0;
      m_circuit_blown       = false;
      m_cloud_locked        = false;
      m_emergency           = false;
      m_state.Init(max_trades, max_streak, cooldown_sec);
   }

   // ── Cloud state injection (called from OnTick step 1) ─────────────────────
   void SetCloudState(bool locked, bool emergency)
   {
      m_cloud_locked = locked;
      m_emergency    = emergency;
      m_state.SetCloudState(locked, emergency);
   }

   // ── Set active regime context for current symbol ──────────────────────────
   // Called from OnTick step 3 — feeds per-symbol allow_trade into state machine
   void SetRegimeContext(const RegimeContext &ctx)
   {
      // State machine doesn't need regime ctx directly — safety net reads allow_trade below
      // Reserved for future: cooldown extension on VOLATILE regime
   }

   // ── Main evaluation ───────────────────────────────────────────────────────
   // Returns GATE_ALLOW / GATE_BLOCK / GATE_HARD_LOCK
   // Does NOT compute lot size — that's SizingEngine's job
   ENUM_GATE_ACTION Evaluate(const string          &symbol,
                              const PortfolioSnapshot &port,
                              const RegimeContext     &ctx,
                              string                 &reason_out)
   {
      reason_out = "";

      // 1. Emergency / Cloud lock (highest priority)
      if(m_emergency)    { reason_out = "EMERGENCY";    return GATE_HARD_LOCK; }
      if(m_cloud_locked) { reason_out = "Cloud locked"; return GATE_HARD_LOCK; }

      // 2. Cloud per-symbol gate
      if(!ctx.allow_trade)
      {
         reason_out = StringFormat("[%s] Cloud BLOCK (score=%d, cap=%s)", symbol, ctx.score, ctx.state_cap);
         return GATE_HARD_LOCK;
      }

      // 3. Circuit breaker — balance drawdown
      _UpdatePeak(port.account.balance);
      if(m_balance_peak > 0)
      {
         double dd = (m_balance_peak - port.account.balance) / m_balance_peak;
         if(dd >= m_circuit_breaker_pct)
         {
            m_circuit_blown = true;
            reason_out = StringFormat("CircuitBreaker %.1f%% DD", dd * 100);
            return GATE_HARD_LOCK;
         }
      }
      if(m_circuit_blown) { reason_out = "CircuitBreaker (latched)"; return GATE_HARD_LOCK; }

      // 4. Portfolio exposure gate
      if(port.total_risk_pct >= m_max_portfolio_risk)
      {
         reason_out = StringFormat("PortfolioRisk %.1f%% >= %.1f%%",
                                    port.total_risk_pct * 100, m_max_portfolio_risk * 100);
         return GATE_BLOCK;
      }

      // 5. Per-symbol exposure gate
      double sym_risk = _CalcSymbolRisk(symbol, port);
      if(sym_risk >= m_max_symbol_risk)
      {
         reason_out = StringFormat("[%s] SymbolRisk %.1f%% >= %.1f%%",
                                    symbol, sym_risk * 100, m_max_symbol_risk * 100);
         return GATE_BLOCK;
      }

      // 6. ATR spike check (simplified — if spread > 3× ATR, be cautious)
      // Full VolatilityModel removed — just a simple guard
      // [intentionally lightweight — cloud handles regime classification]

      // 7. State machine: anti-spam, cooldown, loss streak, daily limit
      ENUM_GATE_ACTION sm = m_state.Evaluate(symbol, TimeCurrent(), reason_out);
      return sm;
   }

   // ── Register trade result (called from OnTradeTransaction) ────────────────
   void RegisterTrade(datetime t, double pnl) { m_state.RegisterTrade(t, pnl); }

   // ── Reset circuit breaker (manual, after equity recovered) ────────────────
   void ResetCircuitBreaker() { m_circuit_blown = false; m_balance_peak = 0; }

   // ── Getters (for UI snapshot) ──────────────────────────────────────────────
   int    GetTradeCount()  const { return m_state.GetTradeCount(); }
   int    GetLossStreak()  const { return m_state.GetLossStreak(); }
   bool   IsCircuitBlown() const { return m_circuit_blown; }

   // Update max trades / cooldown at runtime
   void UpdateMaxTrades(int v) { m_state.SetMaxTrades(v); }
   void UpdateCooldown(int v)  { m_state.SetCooldown(v); }

private:

   void _UpdatePeak(double balance)
   {
      if(balance > m_balance_peak) m_balance_peak = balance;
   }

   double _CalcSymbolRisk(const string &symbol, const PortfolioSnapshot &port) const
   {
      if(port.account.equity <= 0) return 0;
      double sym_risk = 0;
      for(int i = 0; i < port.position_count; i++)
         if(port.positions[i].symbol == symbol)
            sym_risk += port.positions[i].risk_money;
      return sym_risk / port.account.equity;
   }
};


// ============================================================================
// SECTION: core/sizing_engine.mqh
// ============================================================================
// ==============================================================================
// FILE: core/sizing_engine.mqh  — Z-ARMOR KERNEL v3.0  (NEW)
// Lot size, SL, TP calculation — cloud-driven 3-param formula.
//
// v2.1 had 6-multiplier chain inside RiskEngine:
//   eff_risk = base × score_scale × sys_scale × dd_mult × pressure_mult × remote_mult
//
// v3.0 replaces with 3 clean params (all from cloud):
//   posSize = profile.baseLot × (position_pct/100) × damping_factor × exposure_scale
//   SL      = atr14 × sl_multiplier × profile.sl_safety_factor (default 1.0)
//   TP      = SL × profile.rr_ratio
//
// Where:
//   position_pct   → from radar_map per-symbol (0-125)
//   damping_factor → from z_pressure block (0.0-1.0+, portfolio-level)
//   exposure_scale → local: 1.0 if symbol risk < limit, else reduces to fit
//   baseLot        → computed from base_risk_pct × equity / (SL in account currency)
//
// Risk mode cap (from StrategyProfile):
//   CONSERVATIVE → cap position_pct at 60
//   NORMAL       → use as-is
//   AGGRESSIVE   → allow up to 125 (only when ALLOW_SCALE gate)
// ==============================================================================


class SizingEngine
{
private:
   double m_base_risk_pct;       // eg 0.01 = 1% equity risk per trade

public:

   void Init(double base_risk_pct = 0.01)
   {
      m_base_risk_pct = base_risk_pct;
   }

   // ── Compute full RiskDecision sizing ─────────────────────────────────────
   // Fills d.approved_volume, d.approved_sl, d.approved_tp
   // Caller sets d.symbol, d.direction, d.gate_action before calling this.
   void Compute(RiskDecision           &d,
                const RegimeContext    &ctx,
                const StrategyProfile  &profile,
                const EntrySignal      &sig,
                const PortfolioSnapshot &port,
                double                  exposure_scale)
   {
      double equity = port.account.equity;
      if(equity <= 0) { d.approved_volume = 0; return; }

      // ── Step 1: Apply risk mode cap to position_pct ───────────────────────
      int pos_pct = ctx.position_pct;
      switch(profile.risk_mode)
      {
         case RISK_CONSERVATIVE: pos_pct = MathMin(pos_pct, 60);  break;
         case RISK_NORMAL:       pos_pct = MathMin(pos_pct, 100); break;
         case RISK_AGGRESSIVE:   pos_pct = MathMin(pos_pct, 125); break;
      }

      // ── Step 2: Effective risk % ──────────────────────────────────────────
      // base_risk × (position_pct/100) × damping × exposure_scale
      double eff_risk = m_base_risk_pct
                      * (pos_pct / 100.0)
                      * ctx.damping_factor
                      * exposure_scale;

      eff_risk = MathMax(eff_risk, 0.0);
      eff_risk = MathMin(eff_risk, 0.20); // hard cap: never risk > 20%

      // ── Step 3: SL price distance (in account currency via ATR) ───────────
      // sl_distance = ATR × sl_multiplier (from cloud, already profile-aware)
      double atr14 = sig.atr14;
      if(atr14 <= 0) { d.approved_volume = 0; return; }

      double sl_dist = atr14 * ctx.sl_multiplier;
      double tp_dist = sl_dist * profile.rr_ratio;

      // ── Step 4: Volume from equity × risk / SL cost ───────────────────────
      InstrumentSpec spec = port.positions[0].symbol == d.symbol && port.position_count > 0
                            ? _InferSpec(d.symbol)
                            : _InferSpec(d.symbol); // always use symbol spec

      double volume = _CalcVolume(eff_risk, sl_dist, spec, equity);

      // ── Step 5: Build SL/TP prices from direction ─────────────────────────
      double price = (d.direction == 1) ? SymbolInfoDouble(d.symbol, SYMBOL_ASK)
                                        : SymbolInfoDouble(d.symbol, SYMBOL_BID);

      double sl = (d.direction == 1) ? price - sl_dist : price + sl_dist;
      double tp = (d.direction == 1) ? price + tp_dist : price - tp_dist;

      // Fill decision
      d.approved_volume    = volume;
      d.approved_sl        = NormalizeDouble(sl, (int)SymbolInfoInteger(d.symbol, SYMBOL_DIGITS));
      d.approved_tp        = NormalizeDouble(tp, (int)SymbolInfoInteger(d.symbol, SYMBOL_DIGITS));
      d.approved_risk_pct  = eff_risk;
      d.sl_atr_multiplier  = ctx.sl_multiplier;
      d.z_pressure         = 0; // filled by caller from cloud context
      d.decision_time      = TimeCurrent();
   }

private:

   double _CalcVolume(double risk_pct, double sl_dist,
                       const InstrumentSpec &spec, double equity)
   {
      if(risk_pct <= 0 || sl_dist <= 0)        return 0.0;
      if(spec.point <= 0 || spec.tick_size <= 0) return spec.volume_min;
      if(equity <= 0)                             return 0.0;

      double sl_points    = sl_dist / spec.point;
      double risk_money   = equity * risk_pct;
      double cost_per_lot = (sl_points * spec.tick_value) / spec.tick_size;

      if(cost_per_lot <= 0) return spec.volume_min;

      double vol = risk_money / cost_per_lot;

      if(spec.volume_step > 0)
         vol = MathFloor(vol / spec.volume_step) * spec.volume_step;

      return MathMax(spec.volume_min, MathMin(vol, spec.volume_max));
   }

   // Build InstrumentSpec from MT5 symbol info
   InstrumentSpec _InferSpec(const string &symbol)
   {
      InstrumentSpec s;
      s.symbol        = symbol;
      s.tick_size     = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
      s.tick_value    = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
      s.point         = SymbolInfoDouble(symbol, SYMBOL_POINT);
      s.volume_min    = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
      s.volume_step   = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
      s.volume_max    = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
      s.spread_points = (double)SymbolInfoInteger(symbol, SYMBOL_SPREAD);
      s.contract_size = SymbolInfoDouble(symbol, SYMBOL_TRADE_CONTRACT_SIZE);
      return s;
   }
};


// ============================================================================
// SECTION: strategy/regime_gate_filter.mqh
// ============================================================================
// ==============================================================================
// FILE: strategy/regime_gate_filter.mqh  — Z-ARMOR KERNEL v3.0
// Entry timing filter — REPLACES BoltVolmanStrategy.
//
// DESIGN PRINCIPLE (v3.0):
//   EA does NOT ask "where is the market going?" — that is Domain 1+2's job.
//   EA only asks: "Is this a good moment to enter according to the regime?"
//
// v2.1 BoltVolmanStrategy vs v3.0 RegimeGateFilter:
//   v2.1: Detect breakout → decide direction → generate SignalRequest (dir+score)
//   v3.0: Check bar pattern (breakout/pullback) → filter by profile.entry_type
//         → return EntrySignal (timing only, NO direction)
//         → direction is always taken from RegimeContext.direction_mode
//
// Inputs:
//   MarketSnapshot   snap    — OHLCV bars
//   RegimeContext    ctx     — from cloud heartbeat (direction_mode, score, etc)
//   StrategyProfile  profile — from cloud units_config (entry_type, session, etc)
//
// Output: EntrySignal
//   .valid        = true if timing is good AND regime/profile gates pass
//   .strength     = 0-100 quality of this entry timing
//   .entry_type_detected = BREAKOUT or PULLBACK (for logging)
//   .atr14        = ATR for sizing
//   .sl_distance_atr = SL expressed as ATR multiples
//   (direction is NOT set here — use RegimeContext.direction_mode)
// ==============================================================================


class RegimeGateFilter
{
private:
   int    m_range_bars;

   // ── Pure ATR computation (no MT5 calls) ───────────────────────────────────
   double _atr(const double &h[], const double &l[], const double &c[], int p) const
   {
      int sz = ArraySize(h);
      if(sz < p + 1) return 0.0;
      double s = 0;
      for(int i = 0; i < p; i++)
         s += MathMax(h[i]-l[i], MathMax(MathAbs(h[i]-c[i+1]), MathAbs(l[i]-c[i+1])));
      return s / p;
   }

   // ── Range clarity — tightness of consolidation before potential entry ─────
   double _rangeClarity(const double &h[], const double &l[],
                         const double &c[], int lookback) const
   {
      if(ArraySize(h) < lookback + 2) return 0.0;
      double max_h = h[2], min_l = l[2], sum_range = 0.0;
      for(int i = 2; i < lookback + 2; i++)
      {
         sum_range += (h[i] - l[i]);
         if(h[i] > max_h) max_h = h[i];
         if(l[i] < min_l) min_l = l[i];
      }
      double band = max_h - min_l;
      double avg  = sum_range / lookback;
      if(band <= 0 || avg <= 0) return 0.0;
      return MathMin(25.0, MathMax(0.0, 25.0 * (1.0 - avg / band)));
   }

   // ── Pullback quality ──────────────────────────────────────────────────────
   double _pullbackScore(const double &c[], double atr14) const
   {
      if(atr14 <= 0) return 0.0;
      double depth = MathAbs(c[0] - c[1]) / atr14;
      return MathMax(0.0, 15.0 * (1.0 - depth * 2.0));
   }

   // ── Session check — is current UTC hour within profile session filter ─────
   bool _sessionOk(int session_filter) const
   {
      if(session_filter == SESSION_ALL) return true;
      datetime now = TimeCurrent();
      MqlDateTime dt;
      TimeToStruct(now, dt);
      int h = dt.hour;

      // Weekend check
      if(dt.day_of_week == 0 || dt.day_of_week == 6)
         return (session_filter & SESSION_WEEKEND) != 0;

      bool london = (h >= 7 && h < 16);
      bool ny     = (h >= 13 && h < 22);
      bool asia   = (h >= 22 || h < 7);

      if(london && (session_filter & (uint)SESSION_LONDON)) return true;
      if(ny     && (session_filter & (uint)SESSION_NY))     return true;
      if(asia   && (session_filter & (uint)SESSION_ASIA))   return true;
      return false;
   }

public:

   void Init(int range_bars = 20)
   {
      m_range_bars = range_bars;
   }

   // ── Main evaluation ───────────────────────────────────────────────────────
   EntrySignal Evaluate(const MarketSnapshot  &snap,
                        const RegimeContext   &ctx,
                        const StrategyProfile &profile)
   {
      EntrySignal sig;
      sig.symbol         = snap.symbol;
      sig.valid          = false;
      sig.strength       = 0;
      sig.atr14          = 0;
      sig.sl_distance_atr = 1.5;
      sig.signal_time    = snap.timestamp;
      sig.reject_reason  = "";

      // ── Gate 1: Cloud hard block ──────────────────────────────────────────
      if(!ctx.allow_trade || ctx.direction_mode == DIR_NO_ENTRY)
      {
         sig.reject_reason = "Cloud: " + ctx.state_cap;
         return sig;
      }

      // ── Gate 2: Minimum score from profile ────────────────────────────────
      if(ctx.score < profile.min_score_entry)
      {
         sig.reject_reason = StringFormat("Score %d < min %d", ctx.score, profile.min_score_entry);
         return sig;
      }

      // ── Gate 3: Session filter ────────────────────────────────────────────
      if(!_sessionOk(profile.session_filter))
      {
         sig.reject_reason = "Outside session filter";
         return sig;
      }

      // ── Gate 4: Sufficient bars ───────────────────────────────────────────
      int sz = snap.bar_count;
      if(sz < m_range_bars + 4)
      {
         sig.reject_reason = "Insufficient bars";
         return sig;
      }

      double h[]; ArrayCopy(h, snap.high, 0, 0, WHOLE_ARRAY);
      double l[]; ArrayCopy(l, snap.low,  0, 0, WHOLE_ARRAY);
      double c[]; ArrayCopy(c, snap.close,0, 0, WHOLE_ARRAY);
      double o[]; ArrayCopy(o, snap.open, 0, 0, WHOLE_ARRAY);

      double atr14  = _atr(h, l, c, 14);
      double atr100 = _atr(h, l, c, 100);

      if(atr14 <= 0) { sig.reject_reason = "ATR=0"; return sig; }
      sig.atr14 = atr14;

      // ── Gate 5: Spread check ──────────────────────────────────────────────
      double spread = snap.ask - snap.bid;
      if(atr14 > 0 && profile.max_spread_pct > 0)
      {
         if(spread > atr14 * profile.max_spread_pct)
         {
            sig.reject_reason = StringFormat("Spread %.5f > %.0f%% ATR", spread, profile.max_spread_pct * 100);
            return sig;
         }
      }

      // ── Bar pattern detection ─────────────────────────────────────────────
      bool break_up   = (c[1] > h[2] && c[1] > o[1]);
      bool break_down = (c[1] < l[2] && c[1] < o[1]);
      bool pullback   = false;

      // Pullback: current bar retraced into the previous breakout bar
      if(break_up)   pullback = (c[0] < c[1]);
      if(break_down) pullback = (c[0] > c[1]);

      bool is_breakout  = (break_up || break_down);
      bool is_pullback  = (is_breakout && pullback);

      // ── Gate 6: Entry type filter from profile ────────────────────────────
      if(profile.entry_type == ENTRY_BREAKOUT_ONLY && !is_breakout)
      {
         sig.reject_reason = "No breakout bar (profile: BREAKOUT_ONLY)";
         return sig;
      }
      if(profile.entry_type == ENTRY_PULLBACK_ONLY && !is_pullback)
      {
         sig.reject_reason = "No pullback (profile: PULLBACK_ONLY)";
         return sig;
      }
      if(!is_breakout && !is_pullback)
      {
         sig.reject_reason = "No valid bar pattern";
         return sig;
      }

      // ── Gate 7: Direction compatibility ───────────────────────────────────
      // Even though we don't SET direction here, reject if the only available
      // bar pattern contradicts the direction_mode (e.g. breakout DOWN when BUY_ONLY)
      if(ctx.direction_mode == DIR_BUY_ONLY && break_down && !break_up)
      {
         sig.reject_reason = "Breakout DOWN conflicts DIR_BUY_ONLY";
         return sig;
      }
      if(ctx.direction_mode == DIR_SELL_ONLY && break_up && !break_down)
      {
         sig.reject_reason = "Breakout UP conflicts DIR_SELL_ONLY";
         return sig;
      }

      // ── Compute entry quality score (timing only) ─────────────────────────
      double body          = MathAbs(c[1] - o[1]);
      double break_strength = (atr14 > 0) ? MathMin(25.0, (body / atr14) * 12.5) : 0;
      double range_clarity  = _rangeClarity(h, l, c, m_range_bars);
      double vol_alignment  = (atr100 > 0) ? MathMin(10.0, (atr14 / atr100) * 5.0) : 0;
      double pullback_q     = is_pullback ? _pullbackScore(c, atr14) : 0;
      double trend_q        = (atr100 > 0 && atr14 > atr100) ? 10.0 : 5.0;

      // Minimum component gates (same thresholds as v2.1 BoltVolman)
      if(break_strength < 8.0)  { sig.reject_reason = "Weak breakout body"; return sig; }
      if(range_clarity  < 6.0)  { sig.reject_reason = "Poor range clarity";  return sig; }
      if(vol_alignment  < 3.0)  { sig.reject_reason = "Vol misaligned";      return sig; }

      double total = break_strength + range_clarity + vol_alignment + pullback_q + trend_q;

      // ── All gates passed ──────────────────────────────────────────────────
      sig.valid              = true;
      sig.strength           = total;
      sig.entry_type_detected = is_pullback ? ENTRY_PULLBACK_ONLY : ENTRY_BREAKOUT_ONLY;
      sig.sl_distance_atr    = ctx.sl_multiplier; // ATR multiples for SL

      return sig;
   }
};


// ============================================================================
// SECTION: execution/mt5_adapter.mqh
// ============================================================================
// ==============================================================================
// FILE: execution/mt5_adapter.mqh
// The ONLY file in the entire kernel allowed to call MT5 API functions.
// Translates broker-native types into kernel structs and vice versa.
// Replacing this file = porting to new broker.
// ==============================================================================


class MT5Adapter
{
private:
   CTrade        m_trade;
   CPositionInfo m_pos;
   long          m_magic;

   ENUM_TIMEFRAMES _mapTF(int tf)
   {
      switch(tf)
      {
         case 1:    return PERIOD_M1;
         case 5:    return PERIOD_M5;
         case 15:   return PERIOD_M15;
         case 30:   return PERIOD_M30;
         case 60:   return PERIOD_H1;
         case 240:  return PERIOD_H4;
         case 1440: return PERIOD_D1;
         default:   return PERIOD_CURRENT;
      }
   }

public:
   void Init(long magic)
   {
      m_magic = magic;
      m_trade.SetExpertMagicNumber(magic);
      m_trade.SetDeviationInPoints(10);
   }

   // ── Market data ───────────────────────────────────────────────────────────

   bool BuildMarketSnapshot(string sym, int tf, int bars, MarketSnapshot &snap)
   {
      snap.symbol    = sym;
      snap.bid       = SymbolInfoDouble(sym, SYMBOL_BID);
      snap.ask       = SymbolInfoDouble(sym, SYMBOL_ASK);
      snap.timestamp = TimeCurrent();

      snap.spec.symbol        = sym;
      snap.spec.tick_size     = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
      snap.spec.tick_value    = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
      snap.spec.point         = SymbolInfoDouble(sym, SYMBOL_POINT);
      snap.spec.volume_min    = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
      snap.spec.volume_step   = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
      snap.spec.volume_max    = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
      snap.spec.spread_points = (snap.ask - snap.bid) / snap.spec.point;
      snap.spec.contract_size = SymbolInfoDouble(sym, SYMBOL_TRADE_CONTRACT_SIZE);

      ENUM_TIMEFRAMES etf = _mapTF(tf);
      ArrayResize(snap.open,  bars);
      ArrayResize(snap.high,  bars);
      ArrayResize(snap.low,   bars);
      ArrayResize(snap.close, bars);

      if(CopyOpen(sym,  etf, 0, bars, snap.open)  <= 0) return false;
      if(CopyHigh(sym,  etf, 0, bars, snap.high)  <= 0) return false;
      if(CopyLow(sym,   etf, 0, bars, snap.low)   <= 0) return false;
      if(CopyClose(sym, etf, 0, bars, snap.close) <= 0) return false;

      ArraySetAsSeries(snap.open,  true);
      ArraySetAsSeries(snap.high,  true);
      ArraySetAsSeries(snap.low,   true);
      ArraySetAsSeries(snap.close, true);
      snap.bar_count = bars;

      return true;
   }

   datetime GetLastBarTime(string sym, int tf)
   {
      return iTime(sym, _mapTF(tf), 0);
   }

   // ── Account data ──────────────────────────────────────────────────────────

   AccountSnapshot BuildAccountSnapshot()
   {
      AccountSnapshot a;
      a.equity       = AccountInfoDouble(ACCOUNT_EQUITY);
      a.balance      = AccountInfoDouble(ACCOUNT_BALANCE);
      a.margin_used  = AccountInfoDouble(ACCOUNT_MARGIN);
      a.margin_free  = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
      a.margin_level_pct = AccountInfoDouble(ACCOUNT_MARGIN_LEVEL);
      a.timestamp    = TimeCurrent();
      return a;
   }

   // ── Positions (filtered by magic) ─────────────────────────────────────────

   void BuildPositionSnapshots(PositionSnapshot &out[], int &count)
   {
      count = 0;
      int total = PositionsTotal();
      ArrayResize(out, total);

      for(int i = 0; i < total; i++)
      {
         if(!m_pos.SelectByIndex(i)) continue;
         if(m_pos.Magic() != m_magic) continue;

         PositionSnapshot p;
         p.ticket        = m_pos.Ticket();
         p.symbol        = m_pos.Symbol();
         p.direction     = (m_pos.PositionType() == POSITION_TYPE_BUY) ? 1 : -1;
         p.volume        = m_pos.Volume();
         p.entry_price   = m_pos.PriceOpen();
         p.stop_loss     = m_pos.StopLoss();
         p.take_profit   = m_pos.TakeProfit();
         p.current_price = m_pos.PriceCurrent();
         p.unrealized_pnl = m_pos.Profit();
         p.magic         = m_pos.Magic();
         p.open_time     = (datetime)m_pos.Time();

         // Pre-compute risk money
         if(p.stop_loss > 0)
         {
            double pt    = SymbolInfoDouble(p.symbol, SYMBOL_POINT);
            double tv    = SymbolInfoDouble(p.symbol, SYMBOL_TRADE_TICK_VALUE);
            double ts    = SymbolInfoDouble(p.symbol, SYMBOL_TRADE_TICK_SIZE);
            double sl_d  = MathAbs(p.entry_price - p.stop_loss);
            double sl_pt = (pt > 0) ? sl_d / pt : 0;
            p.risk_money = (ts > 0) ? (sl_pt * tv / ts) * p.volume : 0;
         }
         else p.risk_money = 0;

         out[count] = p;
         count++;
      }
      ArrayResize(out, count);
   }

   // ── Order execution ───────────────────────────────────────────────────────

   bool SendOrder(const RiskDecision &d)
   {
      if(d.gate_action != GATE_ALLOW && d.gate_action != GATE_WARN) return false;
      if(d.approved_volume <= 0) return false;

      string sym = d.symbol;
      double minLot  = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
      double stepLot = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
      double lot = MathMax(minLot, MathFloor(d.approved_volume / stepLot) * stepLot);

      bool ok = false;
      if(d.direction == 1)
      {
         double price = SymbolInfoDouble(sym, SYMBOL_ASK);
         ok = m_trade.Buy(lot, sym, price, d.approved_sl, d.approved_tp,
                          "ZArmor|" + EnumToString(d.system_state));
      }
      else if(d.direction == -1)
      {
         double price = SymbolInfoDouble(sym, SYMBOL_BID);
         ok = m_trade.Sell(lot, sym, price, d.approved_sl, d.approved_tp,
                           "ZArmor|" + EnumToString(d.system_state));
      }

      if(!ok)
         Print("[MT5Adapter] SendOrder FAIL: ", sym, " code=", m_trade.ResultRetcode());

      return ok;
   }

   bool ClosePosition(ulong ticket)
   {
      return m_trade.PositionClose(ticket);
   }

   bool ModifyPosition(ulong ticket, double new_sl, double new_tp)
   {
      return m_trade.PositionModify(ticket, new_sl, new_tp);
   }

   // Force-flat all positions owned by this EA
   void ForceFlat()
   {
      for(int i = PositionsTotal()-1; i >= 0; i--)
      {
         if(m_pos.SelectByIndex(i) && m_pos.Magic() == m_magic)
            m_trade.PositionClose(m_pos.Ticket());
      }
   }
};


// ============================================================================
// SECTION: execution/execution_engine.mqh
// ============================================================================
// ==============================================================================
// FILE: execution/execution_engine.mqh  — Z-ARMOR KERNEL v3.0
// Applies RiskDecision-approved orders via MT5Adapter.
//
// v3.0 changes vs v2.1:
//   + Check direction_mode from RegimeContext before Apply()
//     (BUY_ONLY → reject SELL orders, SELL_ONLY → reject BUY orders)
//   + direction is now injected from RegimeContext, not from strategy signal
//   = Core Apply/Close/Modify/ForceFlat unchanged
// ==============================================================================


class ExecutionEngine
{
private:
   MT5Adapter* m_adapter;

public:

   void Init(MT5Adapter* adapter) { m_adapter = adapter; }

   // ── Apply — with direction_mode gate ──────────────────────────────────────
   bool Apply(const RiskDecision &d, ENUM_DIRECTION_MODE dir_mode = DIR_BOTH)
   {
      if(d.gate_action == GATE_BLOCK || d.gate_action == GATE_HARD_LOCK)
      {
         Print("[Exec] BLOCKED: ", d.symbol, " | ", d.gate_reason);
         return false;
      }

      // Direction filter — regime decides, EA obeys
      if(dir_mode == DIR_NO_ENTRY)
      {
         Print("[Exec] DIR_NO_ENTRY for ", d.symbol, " — skipping");
         return false;
      }
      if(dir_mode == DIR_BUY_ONLY && d.direction != 1)
      {
         Print("[Exec] DIR_BUY_ONLY: skip SELL on ", d.symbol);
         return false;
      }
      if(dir_mode == DIR_SELL_ONLY && d.direction != -1)
      {
         Print("[Exec] DIR_SELL_ONLY: skip BUY on ", d.symbol);
         return false;
      }

      if(d.approved_volume <= 0)
      {
         Print("[Exec] Volume=0, skip: ", d.symbol);
         return false;
      }

      if(d.gate_action == GATE_WARN)
      {
         Print("[Exec] WARN entry: ", d.symbol,
               " dir=", d.direction == 1 ? "BUY" : "SELL",
               " vol=", DoubleToString(d.approved_volume, 2),
               " Z=", DoubleToString(d.z_pressure, 2));
      }

      bool ok = m_adapter.SendOrder(d);
      if(ok)
      {
         Print("[Exec] OK: ", d.symbol,
               " dir=", d.direction == 1 ? "BUY" : "SELL",
               " vol=",  DoubleToString(d.approved_volume, 2),
               " sl=",   DoubleToString(d.approved_sl, 5),
               " tp=",   DoubleToString(d.approved_tp, 5),
               " risk=", DoubleToString(d.approved_risk_pct * 100, 2), "%",
               " mode=", EnumToString(dir_mode));
      }
      return ok;
   }

   void Close(ulong ticket)                   { m_adapter.ClosePosition(ticket); }
   void Modify(ulong ticket, double sl, double tp) { m_adapter.ModifyPosition(ticket, sl, tp); }
   void ForceFlat()
   {
      Print("[Exec] FORCE FLAT — closing all positions");
      m_adapter.ForceFlat();
   }
};


// ============================================================================
// SECTION: execution/cloud_bridge.mqh
// ============================================================================
// ==============================================================================
// FILE: execution/cloud_bridge.mqh  — Z-ARMOR KERNEL v3.0
// Cloud Interface Layer — parse all intelligence from heartbeat response.
//
// v3.0 changes vs mt5_adapter_radar.mqh (v2.1):
//   + ParseStrategyProfile()  — parse units_config.strategy_profile from JSON
//   + ParseDampingFactor()    — parse z_pressure.damping_factor from JSON
//   + ParseRegimeContextAll() — richer struct with direction_mode + damping
//   ~ Renamed file: mt5_adapter_radar → cloud_bridge (clearer role)
//   ~ RadarContext → RegimeContext (aligned with models.mqh v3.0)
//   = JSON extractor helpers unchanged (battle-tested in v2.1)
//
// Globals populated by BridgeTick() after each successful heartbeat:
//   RegimeContext  g_radar[MAX_RADAR_SYMBOLS]   — per-symbol regime data
//   int            g_radar_count
//   StrategyProfile g_profile                   — active strategy template
//   double          g_damping                   — portfolio damping factor
//   bool            g_bridge_ok
//   datetime        g_last_heartbeat
// ==============================================================================


#define MAX_RADAR_SYMBOLS 8

// ─── Global bridge state ──────────────────────────────────────────────────────
RegimeContext    g_radar[MAX_RADAR_SYMBOLS];
int              g_radar_count    = 0;
StrategyProfile  g_profile;
double           g_damping        = 1.0;
bool             g_bridge_ok      = false;
datetime         g_last_heartbeat = 0;

// ─── CloudBridge class ────────────────────────────────────────────────────────

class CloudBridge
{
public:

   // ── Parse entire heartbeat response ───────────────────────────────────────
   // Call after successful WebRequest in BridgeTick().
   // Populates g_radar[], g_profile, g_damping.
   static void ParseResponse(const string &json)
   {
      _ParseRadarMap(json);
      _ParseStrategyProfile(json);
      _ParseDampingFactor(json);
      g_last_heartbeat = TimeCurrent();
      g_bridge_ok      = true;
   }

   // ── Get RegimeContext for a specific symbol ────────────────────────────────
   // Returns safe default if not found.
   static RegimeContext GetContext(const string &symbol)
   {
      for(int i = 0; i < g_radar_count; i++)
         if(g_radar[i].symbol == symbol)
            return g_radar[i];
      return DefaultRegimeContext(symbol);
   }

   // ── Check if heartbeat data is still fresh for a context ──────────────────
   static bool IsFresh(const RegimeContext &ctx)
   {
      if(!ctx.is_valid) return false;
      return (TimeCurrent() - ctx.fetched_at) < (datetime)ctx.ttl_sec;
   }

   // ── Mark bridge offline ───────────────────────────────────────────────────
   static void SetOffline()
   {
      g_bridge_ok = false;
   }

   // ── Build URL param: symbols for heartbeat request ─────────────────────────
   static string BuildSymbolsParam(const string &symbols[], int count)
   {
      string result = "";
      for(int i = 0; i < count; i++)
      {
         if(i > 0) result += ",";
         result += symbols[i];
      }
      return result;
   }

   // ── Timeframe → string ────────────────────────────────────────────────────
   static string TFToString(ENUM_TIMEFRAMES tf)
   {
      switch(tf)
      {
         case PERIOD_M1:  return "M1";
         case PERIOD_M5:  return "M5";
         case PERIOD_M15: return "M15";
         case PERIOD_M30: return "M30";
         case PERIOD_H1:  return "H1";
         case PERIOD_H4:  return "H4";
         case PERIOD_D1:  return "D1";
         default:         return "H1";
      }
   }

private:

   // ── Parse radar_map → g_radar[] ───────────────────────────────────────────
   static void _ParseRadarMap(const string &json)
   {
      g_radar_count = 0;

      // FIX-3: ZCloud ea_router returns "radar" not "radar_map"
      // Try "radar" first (ZCloud), fall back to "radar_map" (legacy)
      int map_start = StringFind(json, "\"radar\":");
      int key_len   = 8;   // len(""radar":") 
      if(map_start < 0)
      {
         map_start = StringFind(json, "\"radar_map\":");
         key_len   = 12;
      }
      if(map_start < 0) return;

      int obj_start = StringFind(json, "{", map_start + key_len);
      if(obj_start < 0) return;

      string section = StringSubstr(json, obj_start);
      int pos = 1; // skip opening brace

      while(g_radar_count < MAX_RADAR_SYMBOLS)
      {
         // Find symbol key
         int ks = StringFind(section, "\"", pos);
         if(ks < 0) break;
         int ke = StringFind(section, "\"", ks + 1);
         if(ke < 0) break;

         string sym = StringSubstr(section, ks + 1, ke - ks - 1);
         if(StringLen(sym) < 3 || StringLen(sym) > 12) { pos = ke + 1; continue; }

         // Find value object
         int vs = StringFind(section, "{", ke);
         int ve = StringFind(section, "}", vs);
         if(vs < 0 || ve < 0) break;

         string obj = StringSubstr(section, vs, ve - vs + 1);

         RegimeContext ctx;
         ctx.symbol         = sym;
         ctx.score          = (int)_ExtractInt(obj, "score", 50);
         // FIX-4: ZCloud returns ea_position_pct / ea_sl_multiplier / ea_allow_trade
         // Also try unprefixed names for backward compat with legacy responses
         ctx.regime_str    = _ExtractString(obj, "regime", "RANGE_BOUND");
         ctx.allow_trade   = _ExtractBool(obj,   "ea_allow_trade",
                             _ExtractBool(obj,   "allow_trade",   true));
         ctx.position_pct  = (int)_ExtractInt(obj, "ea_position_pct",
                             _ExtractInt(obj,      "position_pct",   60));
         ctx.sl_multiplier = _ExtractDouble(obj, "ea_sl_multiplier",
                             _ExtractDouble(obj,  "sl_multiplier",   1.5));
         // ea_state_cap (informational — used by panel display)
         ctx.state_cap     = _ExtractString(obj, "ea_state_cap",
                             _ExtractString(obj,  "state_cap", "CAUTION"));
         ctx.state_cap      = _ExtractString(obj, "state_cap", "CAUTION");
         ctx.ttl_sec        = (int)_ExtractInt(obj, "ttl_sec", 1800);
         ctx.damping_factor = _ExtractDouble(obj, "damping_factor", 1.0);
         ctx.fetched_at     = TimeCurrent();
         ctx.is_valid       = true;

         // Parse direction_mode from regime string + allow_trade
         ctx.direction_mode = ParseDirectionMode(ctx.regime_str, ctx.allow_trade);

         // Validate ranges
         if(ctx.score < 0 || ctx.score > 100)             ctx.score = 50;
         if(ctx.position_pct < 0 || ctx.position_pct > 125) ctx.position_pct = 60;
         if(ctx.sl_multiplier < 0.5 || ctx.sl_multiplier > 5.0) ctx.sl_multiplier = 1.5;
         if(ctx.damping_factor < 0.0 || ctx.damping_factor > 2.0) ctx.damping_factor = 1.0;

         g_radar[g_radar_count++] = ctx;

         pos = ve + 1;
      }
   }

   // ── Parse strategy_profile from units_config in heartbeat JSON ────────────
   // Server injects: "strategy_profile": {"profile_name":"...", "entry_type":"BOTH", ...}
   static void _ParseStrategyProfile(const string &json)
   {
      int sp_start = StringFind(json, "\"strategy_profile\"");
      if(sp_start < 0)
      {
         // Keep existing profile or use default
         if(!g_profile.is_loaded)
            g_profile = DefaultStrategyProfile();
         return;
      }

      int obj_start = StringFind(json, "{", sp_start + 18);
      if(obj_start < 0) return;
      int obj_end = StringFind(json, "}", obj_start);
      if(obj_end < 0) return;

      string obj = StringSubstr(json, obj_start, obj_end - obj_start + 1);

      g_profile.profile_name    = _ExtractString(obj, "profile_name", "Cloud Profile");
      g_profile.min_score_entry = (int)_ExtractInt(obj, "min_score_entry", 60);
      g_profile.rr_ratio        = _ExtractDouble(obj, "rr_ratio", 2.0);
      g_profile.max_spread_pct  = _ExtractDouble(obj, "max_spread_pct", 0.5);
      g_profile.trailing_sl     = _ExtractBool(obj, "trailing_sl", false);
      g_profile.session_filter  = (int)_ExtractInt(obj, "session_filter", SESSION_ALL);
      g_profile.is_loaded       = true;

      // entry_type string → enum
      string et = _ExtractString(obj, "entry_type", "BOTH");
      if(et == "BREAKOUT_ONLY")    g_profile.entry_type = ENTRY_BREAKOUT_ONLY;
      else if(et == "PULLBACK_ONLY") g_profile.entry_type = ENTRY_PULLBACK_ONLY;
      else                           g_profile.entry_type = ENTRY_BOTH;

      // risk_mode string → enum
      string rm = _ExtractString(obj, "risk_mode", "NORMAL");
      if(rm == "CONSERVATIVE")     g_profile.risk_mode = RISK_CONSERVATIVE;
      else if(rm == "AGGRESSIVE")  g_profile.risk_mode = RISK_AGGRESSIVE;
      else                          g_profile.risk_mode = RISK_NORMAL;

      Print("[Bridge] Profile loaded: ", g_profile.profile_name,
            " entry=", EnumToString(g_profile.entry_type),
            " min_score=", g_profile.min_score_entry,
            " rr=", DoubleToString(g_profile.rr_ratio, 1));
   }

   // ── Parse damping_factor from z_pressure block ─────────────────────────────
   // Server format: "z_pressure": {"value": 0.3, "damping_factor": 0.85, ...}
   // Fallback: also check top-level damping_factor field
   static void _ParseDampingFactor(const string &json)
   {
      // Try z_pressure block first
      int zp_start = StringFind(json, "\"z_pressure\"");
      if(zp_start >= 0)
      {
         int obj_s = StringFind(json, "{", zp_start + 12);
         int obj_e = StringFind(json, "}", obj_s);
         if(obj_s >= 0 && obj_e >= 0)
         {
            string obj = StringSubstr(json, obj_s, obj_e - obj_s + 1);
            double df = _ExtractDouble(obj, "damping_factor", -1.0);
            if(df >= 0.0 && df <= 2.0) { g_damping = df; return; }
         }
      }

      // Fallback: top-level damping_factor
      double df2 = _ExtractDouble(json, "damping_factor", -1.0);
      if(df2 >= 0.0 && df2 <= 2.0) { g_damping = df2; return; }

      // No damping in response — keep last known value (default 1.0)
   }

   // ── JSON extractors (unchanged from v2.1 — battle-tested) ─────────────────

   // Public alias for use outside CloudBridge (e.g. DoHandshake)
   static string _ExtractStr(const string &j, const string &key, const string &def)
   { return _ExtractString(j, key, def); }

   static long _ExtractInt(const string &j, const string &key, long def)
   {
      string pat = "\"" + key + "\":";
      int pos = StringFind(j, pat);
      if(pos < 0) return def;
      pos += StringLen(pat);
      while(pos < StringLen(j) && StringGetCharacter(j, pos) == ' ') pos++;
      string n = "";
      if(StringGetCharacter(j, pos) == '-') { n = "-"; pos++; }
      while(pos < StringLen(j))
      {
         ushort c = StringGetCharacter(j, pos);
         if(c >= '0' && c <= '9') { n += ShortToString(c); pos++; }
         else break;
      }
      if(StringLen(n) == 0 || n == "-") return def;
      return StringToInteger(n);
   }

   static double _ExtractDouble(const string &j, const string &key, double def)
   {
      string pat = "\"" + key + "\":";
      int pos = StringFind(j, pat);
      if(pos < 0) return def;
      pos += StringLen(pat);
      while(pos < StringLen(j) && StringGetCharacter(j, pos) == ' ') pos++;
      string n = ""; bool dot = false;
      if(StringGetCharacter(j, pos) == '-') { n = "-"; pos++; }
      while(pos < StringLen(j))
      {
         ushort c = StringGetCharacter(j, pos);
         if(c >= '0' && c <= '9') { n += ShortToString(c); pos++; }
         else if(c == '.' && !dot) { n += "."; dot = true; pos++; }
         else break;
      }
      if(StringLen(n) == 0 || n == "-") return def;
      return StringToDouble(n);
   }

   static string _ExtractString(const string &j, const string &key, const string &def)
   {
      string pat = "\"" + key + "\":";
      int pos = StringFind(j, pat);
      if(pos < 0) return def;
      pos += StringLen(pat);
      while(pos < StringLen(j) && StringGetCharacter(j, pos) == ' ') pos++;
      if(StringGetCharacter(j, pos) != '"') return def;
      pos++;
      int ep = StringFind(j, "\"", pos);
      if(ep < 0) return def;
      return StringSubstr(j, pos, ep - pos);
   }

   static bool _ExtractBool(const string &j, const string &key, bool def)
   {
      string pat = "\"" + key + "\":";
      int pos = StringFind(j, pat);
      if(pos < 0) return def;
      pos += StringLen(pat);
      while(pos < StringLen(j) && StringGetCharacter(j, pos) == ' ') pos++;
      string r = StringSubstr(j, pos, 5);
      if(StringFind(r, "true")  == 0) return true;
      if(StringFind(r, "false") == 0) return false;
      return def;
   }
};


// ============================================================================
// SECTION: scheduler/multi_symbol_scheduler.mqh
// ============================================================================
// ==============================================================================
// FILE: scheduler/multi_symbol_scheduler.mqh  — Z-ARMOR KERNEL v3.0
// Per-symbol execution coordinator.
//
// v3.0 changes vs v2.1:
//   REPLACED:  BoltVolmanStrategy.Evaluate() → RegimeGateFilter.Evaluate()
//   REPLACED:  RiskEngine.Evaluate() → LocalSafetyNet.Evaluate() + SizingEngine.Compute()
//   REMOVED:   RemoteRiskOverride passthrough (now via RegimeContext from cloud)
//   ADDED:     RegimeGateFilter receives RegimeContext + StrategyProfile (from g_radar/g_profile)
//   ADDED:     Direction assigned from RegimeContext.direction_mode (not from signal)
//   KEPT:      Anti-spam new-bar per-symbol, PortfolioSnapshot assembly, ForceCloseSym()
//   KEPT:      OnTradeTransaction registration via RegisterTrade()
// ==============================================================================


class MultiSymbolScheduler
{
private:
   string             m_symbols[MAX_SYMBOLS];
   int                m_sym_count;
   int                m_timeframe;
   int                m_bars;
   long               m_magic;

   MT5Adapter*        m_adapter;
   LocalSafetyNet*    m_safety;
   SizingEngine*      m_sizer;
   ExecutionEngine*   m_exec;
   RegimeGateFilter   m_gate;

   // Per-symbol anti-spam: last bar time
   datetime           m_last_bar[MAX_SYMBOLS];

   // Last built portfolio snapshot (cached for UI)
   PortfolioSnapshot  m_last_portfolio;
   SystemStateSnapshot m_last_ss;

   // ── Parse symbols from comma-separated string ──────────────────────────────
   void _parseSym(const string &list)
   {
      string parts[];
      int n = StringSplit(list, ',', parts);
      m_sym_count = 0;
      for(int i = 0; i < n && m_sym_count < MAX_SYMBOLS; i++)
      {
         string s = parts[i];
         StringTrimLeft(s); StringTrimRight(s);
         if(StringLen(s) > 0)
            m_symbols[m_sym_count++] = s;
      }
   }

   PortfolioSnapshot _buildPortfolio()
   {
      PortfolioSnapshot p;
      p.account = m_adapter.BuildAccountSnapshot();
      m_adapter.BuildPositionSnapshots(p.positions, p.position_count);
      p.total_risk_money = 0; p.net_delta = 0; p.gross_exposure = 0;
      for(int i = 0; i < p.position_count; i++)
      {
         p.total_risk_money += p.positions[i].risk_money;
         p.net_delta        += p.positions[i].direction * p.positions[i].volume;
         p.gross_exposure   += p.positions[i].volume;
      }
      p.total_risk_pct = (p.account.equity > 0)
                          ? p.total_risk_money / p.account.equity : 0.0;
      return p;
   }

   // Exposure scale: 1.0 if symbol has room, fractional to stay within limit
   double _exposureScale(const string &sym, const PortfolioSnapshot &port,
                          double max_sym_risk_pct)
   {
      if(port.account.equity <= 0) return 0;
      double sym_risk = 0;
      for(int i = 0; i < port.position_count; i++)
         if(port.positions[i].symbol == sym)
            sym_risk += port.positions[i].risk_money;

      double sym_risk_pct  = sym_risk / port.account.equity;
      double remaining     = max_sym_risk_pct - sym_risk_pct;
      if(remaining <= 0) return 0;

      // Portfolio-level remaining
      double port_remaining = 0.05 - port.total_risk_pct; // 5% hard cap
      if(port_remaining <= 0) return 0;

      return MathMin(1.0, MathMin(remaining, port_remaining) / m_base_risk_pct());
   }

   double m_base_risk_cache;
   double m_base_risk_pct() { return m_base_risk_cache > 0 ? m_base_risk_cache : 0.01; }

public:

   void Init(const string &symbol_list, int timeframe, int bars, long magic,
             MT5Adapter*     adapter,
             LocalSafetyNet* safety,
             SizingEngine*   sizer,
             ExecutionEngine* exec,
             double base_risk_pct = 0.01)
   {
      _parseSym(symbol_list);
      m_timeframe         = timeframe;
      m_bars              = bars;
      m_magic             = magic;
      m_adapter           = adapter;
      m_safety            = safety;
      m_sizer             = sizer;
      m_exec              = exec;
      m_base_risk_cache   = base_risk_pct;
      m_gate.Init(20);
      ArrayInitialize(m_last_bar, 0);
   }

   // ── Main cycle — called from OnTick() ────────────────────────────────────
   void Update()
   {
      m_last_portfolio = _buildPortfolio();

      for(int i = 0; i < m_sym_count; i++)
      {
         string sym = m_symbols[i];

         // ── Build market snapshot ─────────────────────────────────────────
         MarketSnapshot snap;
         if(!m_adapter.BuildMarketSnapshot(sym, m_timeframe, m_bars, snap))
            continue;

         // ── Anti-spam: process only on new bar ───────────────────────────
         if(snap.bar_count < 2) continue;
         datetime bar0 = iTime(sym, (ENUM_TIMEFRAMES)(m_timeframe * 60), 1);
         if(bar0 == m_last_bar[i]) continue;
         m_last_bar[i] = bar0;

         // ── Get regime context + profile from cloud bridge ────────────────
         RegimeContext   ctx     = CloudBridge::GetContext(sym);
         StrategyProfile profile = g_profile;

         // ── Step A: Regime gate filter ────────────────────────────────────
         EntrySignal sig = m_gate.Evaluate(snap, ctx, profile);
         if(!sig.valid)
         {
            // Verbose: uncomment for debugging
            // Print("[Sched] ", sym, " gate reject: ", sig.reject_reason);
            continue;
         }

         // ── Step B: LocalSafetyNet ────────────────────────────────────────
         string safety_reason;
         ENUM_GATE_ACTION gate = m_safety.Evaluate(sym, m_last_portfolio, ctx, safety_reason);
         if(gate == GATE_HARD_LOCK || gate == GATE_BLOCK)
         {
            Print("[Sched] ", sym, " safety block: ", safety_reason);
            continue;
         }

         // ── Step C: Determine direction from RegimeContext ────────────────
         // EA does NOT decide direction — it reads from cloud
         int direction = 0;
         ENUM_DIRECTION_MODE dm = ctx.direction_mode;
         if(dm == DIR_BUY_ONLY)   direction = 1;
         else if(dm == DIR_SELL_ONLY) direction = -1;
         else if(dm == DIR_BOTH)
         {
            // For BOTH: use bar pattern direction detected by gate filter
            // EntrySignal knows if we detected a break_up or break_down
            // Simple heuristic: use price vs last close
            double c0 = snap.close[0], c1 = snap.close[1];
            direction = (c0 > c1) ? 1 : -1;
         }
         if(direction == 0) continue; // DIR_NO_ENTRY handled by gate

         // ── Step D: Size the trade ────────────────────────────────────────
         double exp_scale = _exposureScale(sym, m_last_portfolio, 0.02);
         if(exp_scale <= 0)
         {
            Print("[Sched] ", sym, " exposure full, skip");
            continue;
         }

         RiskDecision d;
         d.symbol          = sym;
         d.direction       = direction;
         d.gate_action     = gate; // GATE_ALLOW or GATE_WARN
         d.gate_reason     = safety_reason;
         d.system_state    = SYS_NORMAL;
         d.capital_state   = CAPITAL_STABLE;
         d.alpha_state     = ALPHA_MODERATE; // deprecated
         d.z_pressure      = 0;              // caller fills from cloud if needed
         d.portfolio_risk_pct = m_last_portfolio.total_risk_pct;

         m_sizer.Compute(d, ctx, profile, sig, m_last_portfolio, exp_scale);

         if(d.approved_volume <= 0)
         {
            Print("[Sched] ", sym, " volume=0, skip");
            continue;
         }

         // ── Step E: Execute ───────────────────────────────────────────────
         m_exec.Apply(d, dm);
      }
   }

   // ── Force close all positions for one symbol ──────────────────────────────
   void ForceCloseSym(const string &sym)
   {
      PositionSnapshot pos[];
      int cnt;
      m_adapter.BuildPositionSnapshots(pos, cnt);
      for(int i = 0; i < cnt; i++)
         if(pos[i].symbol == sym)
            m_exec.Close(pos[i].ticket);
   }

   // ── Register closed trade ─────────────────────────────────────────────────
   void RegisterTrade(datetime t, double pnl) { m_safety.RegisterTrade(t, pnl); }

   // ── Getters for UI ────────────────────────────────────────────────────────
   void GetLastAccountSnap(AccountSnapshot &out) { out = m_last_portfolio.account; }
   double GetLastTotalRisk() { return m_last_portfolio.total_risk_pct; }
};


// ============================================================================
// SECTION: ui/panel_controller.mqh
// ============================================================================
// ==============================================================================
// FILE: ui/panel_controller.mqh  — Z-ARMOR KERNEL v3.2
// Simple chart-object panel — NO CAppDialog inheritance.
//
// v3.2 changes vs v3.1:
//   + Tab 1 STRATEGY: hoàn toàn redesign — Strategy Flow Model visual diagram
//     + Flow diagram: ZCloud Score → GateFilter → SafetyNet → Sizer → ORDER
//     + Live strip: Gate label + pos% + SL×ATR + RR (realtime)
//     + Section A: Regime & Entry — entry type, direction, session, min score vs live
//     + Section B: Sizing & Risk — Gate→Pos% bar 12-char + eff lot formula
//     + Section C: Input vs Cloud — 6 checks (TF match mới) + per-row bg color + Health bar
//     + Section D: Execution Scope — symbols + TF match pair
//   ~ Panel W 265→290, H 445→492
//   = Tab 0 MONITOR, Tab 2 CONTROL: không thay đổi
//   = GV keys, SetInputs() API: backward-compatible 100%
//
// Tab 0: MONITOR  — regime, score, direction, pos%, equity, Z-Pressure, stats
// Tab 1: STRATEGY — flow model + profile A–D + input conflict health
// Tab 2: CONTROL  — emergency controls + cloud sync status
// ==============================================================================

// Windows API — mở browser từ panel click
#import "shell32.dll"
   int ShellExecuteW(int hwnd, string op, string file, string params, string dir, int show);
#import


#define GV_EMERGENCY       "ZARMOR_EMERGENCY"
#define GV_LOCK            "ZARMOR_LOCK"
#define GV_PAUSE           "ZARMOR_PAUSE"
#define GV_CLOSE_ALL_PAUSE "ZARMOR_CLOSE_ALL_PAUSE"

#define PANEL_X   20
#define PANEL_Y   20
#define PANEL_W   320
#define PANEL_H   450
#define PANEL_PFX "ZAP3_"

struct LocalInputSnapshot
{
   double base_risk_pct;
   double max_total_risk;
   double max_symbol_risk;
   double circuit_breaker;
   int    max_trades_day;
   int    max_loss_streak;
   int    cooldown_sec;
   string symbols;
   int    timeframe_min;
   string radar_tf;
};

class PanelController
{
private:
   bool               m_created;
   bool               m_paused;
   int                m_tab;
   long               m_chart;
   LocalInputSnapshot m_inputs;

   string _n(string id) { return PANEL_PFX + id; }

   void _rect(string id,int x,int y,int w,int h,color bg,color brd=clrNONE)
   {
      string nm=_n(id);
      if(ObjectFind(m_chart,nm)<0) ObjectCreate(m_chart,nm,OBJ_RECTANGLE_LABEL,0,0,0);
      ObjectSetInteger(m_chart,nm,OBJPROP_XDISTANCE,x);
      ObjectSetInteger(m_chart,nm,OBJPROP_YDISTANCE,y);
      ObjectSetInteger(m_chart,nm,OBJPROP_XSIZE,w);
      ObjectSetInteger(m_chart,nm,OBJPROP_YSIZE,h);
      ObjectSetInteger(m_chart,nm,OBJPROP_BGCOLOR,bg);
      ObjectSetInteger(m_chart,nm,OBJPROP_BORDER_COLOR,brd==clrNONE?bg:brd);
      ObjectSetInteger(m_chart,nm,OBJPROP_CORNER,CORNER_LEFT_UPPER);
      ObjectSetInteger(m_chart,nm,OBJPROP_BACK,false);
      ObjectSetInteger(m_chart,nm,OBJPROP_SELECTABLE,false);
   }

   void _label(string id,int x,int y,string txt,color clr=0xAAAAAA,int fs=8,string font="Arial")
   {
      string nm=_n(id);
      if(ObjectFind(m_chart,nm)<0) ObjectCreate(m_chart,nm,OBJ_LABEL,0,0,0);
      ObjectSetInteger(m_chart,nm,OBJPROP_XDISTANCE,x);
      ObjectSetInteger(m_chart,nm,OBJPROP_YDISTANCE,y);
      ObjectSetString (m_chart,nm,OBJPROP_TEXT,txt);
      ObjectSetInteger(m_chart,nm,OBJPROP_COLOR,clr);
      ObjectSetInteger(m_chart,nm,OBJPROP_FONTSIZE,fs);
      ObjectSetString (m_chart,nm,OBJPROP_FONT,font);
      ObjectSetInteger(m_chart,nm,OBJPROP_CORNER,CORNER_LEFT_UPPER);
      ObjectSetInteger(m_chart,nm,OBJPROP_BACK,false);
      ObjectSetInteger(m_chart,nm,OBJPROP_SELECTABLE,false);
   }

   void _btn(string id,int x,int y,int w,int h,string txt,color bg=0x2E75B6,color fg=0xFFFFFF)
   {
      string nm=_n(id);
      if(ObjectFind(m_chart,nm)<0) ObjectCreate(m_chart,nm,OBJ_BUTTON,0,0,0);
      ObjectSetInteger(m_chart,nm,OBJPROP_XDISTANCE,x);
      ObjectSetInteger(m_chart,nm,OBJPROP_YDISTANCE,y);
      ObjectSetInteger(m_chart,nm,OBJPROP_XSIZE,w);
      ObjectSetInteger(m_chart,nm,OBJPROP_YSIZE,h);
      ObjectSetString (m_chart,nm,OBJPROP_TEXT,txt);
      ObjectSetInteger(m_chart,nm,OBJPROP_COLOR,fg);
      ObjectSetInteger(m_chart,nm,OBJPROP_BGCOLOR,bg);
      ObjectSetInteger(m_chart,nm,OBJPROP_BORDER_COLOR,bg);
      ObjectSetInteger(m_chart,nm,OBJPROP_FONTSIZE,8);
      ObjectSetInteger(m_chart,nm,OBJPROP_CORNER,CORNER_LEFT_UPPER);
      ObjectSetInteger(m_chart,nm,OBJPROP_BACK,false);
      ObjectSetInteger(m_chart,nm,OBJPROP_SELECTABLE,false);
      ObjectSetInteger(m_chart,nm,OBJPROP_STATE,false);
   }

   void _set(string id,string txt,color clr=0xAAAAAA)
   {
      ObjectSetString (m_chart,_n(id),OBJPROP_TEXT,txt);
      ObjectSetInteger(m_chart,_n(id),OBJPROP_COLOR,clr);
   }

   void _setRect(string id,color bg)
   {
      ObjectSetInteger(m_chart,_n(id),OBJPROP_BGCOLOR,bg);
      ObjectSetInteger(m_chart,_n(id),OBJPROP_BORDER_COLOR,bg);
   }

   void _vis(string id,bool show)
   {
      ObjectSetInteger(m_chart,_n(id),OBJPROP_TIMEFRAMES,
                       show?OBJ_ALL_PERIODS:OBJ_NO_PERIODS);
   }

   void _DeleteAll() { ObjectsDeleteAll(m_chart,PANEL_PFX); }

   string _bar(double val,int w=10)
   {
      int f=(int)MathRound(MathMax(0.0,MathMin(1.0,val))*w);
      string s="";
      for(int i=0;i<w;i++) s+=(i<f)?"█":"░";
      return s;
   }

   string _tfStr(int m)
   {
      switch(m)
      { case 1:return "M1"; case 5:return "M5"; case 15:return "M15";
        case 30:return "M30"; case 60:return "H1"; case 240:return "H4";
        case 1440:return "D1"; default:return IntegerToString(m)+"m"; }
   }

   void _divLine(string id,int px,int y) { _rect(id,px+4,y,PANEL_W-8,1,0x1C2B3A); }

   // ── Helper: render one C-section check row ────────────────────────────────
   void _setCheckRow(string prefix,string paramName,string localVal,string advice,
                     bool ok,bool warn)
   {
      string icon; color statusC,bgC;
      if(ok)        { icon="[OK]"; statusC=0x00C875; bgC=0x060E09; }
      else if(warn) { icon="[!] "; statusC=0xFFA500; bgC=0x0E0A04; }
      else          { icon="[!!]"; statusC=0xE53935; bgC=0x100606; }
      _setRect(prefix+"_bg",bgC);
      _set(prefix+"_st",icon,     statusC);
      _set(prefix+"_k", paramName,0x556677);
      _set(prefix+"_l", localVal, 0x778899);
      _set(prefix+"_a", advice,   statusC);
   }

   // ==========================================================================
   // BUILD
   // ==========================================================================
   void _Build()
   {
      int px=PANEL_X, py=PANEL_Y;
      _rect("bg",   px,py,PANEL_W,PANEL_H,0x080C14,0x1C2B3A);
      _rect("title",px,py,PANEL_W,18,     0x0E1D2E);
      _label("tit", px+6, py+3, "Z-ARMOR v3.0", 0x00B4D8, 8, "Arial Bold");
      _label("tit2",px+162,py+4,"Cloud-Driven EA",0x2A3A4A,7);

      int tw=(PANEL_W-6)/3;
      _btn("tab0",px+2,       py+20,tw,  18,"MONITOR",  0x1E4D8C,0xFFFFFF);
      _btn("tab1",px+2+tw,    py+20,tw,  18,"STRATEGY", 0x1A2535,0xCCCCCC);
      _btn("tab2",px+2+tw*2,  py+20,tw-2,18,"CONTROL",  0x1A2535,0xCCCCCC);

      int top=py+42;
      _BuildTab0(px,top);
      _BuildTab1(px,top);
      _BuildTab2(px,top);
      _ShowTab(0);
      ChartRedraw(m_chart);
   }

   // ==========================================================================
   // TAB 0: MONITOR (unchanged from v3.1)
   // ==========================================================================
   void _BuildTab0(int px,int top)
   {
      int y=top;
      _label("t0_hb",   px+5,y,"--",          0x445566,7); y+=14;
      _label("t0_prof", px+5,y,"Profile: --", 0x00B4D8,8); y+=16;
      _divLine("t0_s1",px,y); y+=5;
      _label("t0_reg",  px+5, y,"REGIME: --", 0xFFA500,8);
      _label("t0_scr",  px+195,y,"Scr:--",    0xEEEEEE,8); y+=15;
      _label("t0_dir",  px+5, y,"DIR: --",    0x00C875,9);
      _label("t0_gtl",  px+170,y,"Gate:--",   0xEEEEEE,8); y+=17;
      _label("t0_pl",   px+5, y,"Pos%:",      0x445566,7);
      _label("t0_pb",   px+38,y,"░░░░░░░░░░", 0x00C875,8);
      _label("t0_pv",   px+128,y,"--%",        0xEEEEEE,8);
      _label("t0_slv",  px+168,y,"SL:--",      0x778899,8); y+=13;
      _divLine("t0_s2",px,y); y+=5;
      _label("t0_eq",   px+5, y,"Eq: --",     0xEEEEEE,8);
      _label("t0_bal",  px+148,y,"Bal: --",   0x778899,8); y+=14;
      _label("t0_dd",   px+5, y,"DD: --",     0xEEEEEE,8);
      _label("t0_risk", px+148,y,"Risk: --",  0xEEEEEE,8); y+=14;
      _divLine("t0_s3",px,y); y+=5;
      _label("t0_zplbl",px+5, y,"Z-Pressure:",0x445566,7); y+=12;
      _label("t0_zpb",  px+5, y,"░░░░░░░░░░", 0x00C875,8);
      _label("t0_zpv",  px+108,y,"0.00",       0xEEEEEE,8);
      _label("t0_dmp",  px+148,y,"dmp:1.0",   0x445566,7); y+=14;
      _divLine("t0_s4",px,y); y+=5;
      _label("t0_tc",   px+5, y,"Trades: --", 0x445566,8);
      _label("t0_ls",   px+148,y,"Streak: --",0x445566,8); y+=14;
      _label("t0_rr",   px+5, y,"RR: --",     0xEEEEEE,8);
      _label("t0_tsl",  px+148,y,"TSL: off",  0x445566,8); y+=14;
      _label("t0_stt",  px+5, y,"State: --",  0xEEEEEE,9); y+=14;
      _label("t0_gtr",  px+5, y,"",            0xFFA500,7);
   }

   // ==========================================================================
   // TAB 1: STRATEGY DASHBOARD — v3.5 (minimal, guaranteed fit)
   // ==========================================================================
   void _BuildTab1(int px,int top)
   {
      int y=top;
      int W=PANEL_W;
      int VX=px+90;

      // ── Profile header ────────────────────────────────────────────────────
      _rect("t1_ph_bg", px+2, y, W-4, 20, 0x071828, 0x0D2E50);
      _label("t1_pn",   px+8,  y+4, "Profile: --",  0xFFFFFF, 9, "Arial Bold");
      _label("t1_src",  px+W-50, y+5, "[Cloud]",     0x00C875, 8);
      y+=22;

      // ── SCORE + GATE + DIRECTION hero ────────────────────────────────────
      _rect("t1_score_bg", px+2, y, W-4, 30, 0x050F1F, 0x0D2E50);
      _label("t1_sc_lbl", px+8,  y+2,  "SCORE",     0x446677, 7);
      _label("t1_sc_val", px+8,  y+11, "--",         0x00E5FF, 14, "Arial Bold");
      _label("t1_sc_div", px+66, y+5,  "│",          0x1A3A5C, 10);
      _rect("t1_gate_bg", px+72, y+3,  68, 24, 0x0A1E0A, 0x1A3A1A);
      _label("t1_gate_v", px+78, y+9,  "--",         0x00C875, 10, "Arial Bold");
      _rect("t1_dir_bg",  px+146,y+3,  82, 24, 0x0A0A20, 0x1A1A3A);
      _label("t1_dir_v",  px+150,y+9,  "--",         0x00B4D8, 10, "Arial Bold");
      _label("t1_pp_lbl", px+238,y+2,  "Pos%",       0x446677, 7);
      _label("t1_pp_val", px+236,y+11, "--%",         0xEEEEEE, 9, "Arial Bold");
      y+=32;

      // ── LIVE STRIP: Gate · SL · RR ───────────────────────────────────────
      _rect("t1_ls_bg", px+2, y, W-4, 13, 0x080E1C, 0x142030);
      _label("t1_ls_gl", px+7,   y+2, "Gate:",  0x445566, 7);
      _label("t1_ls_gv", px+33,  y+2, "--",     0x00C875, 8, "Arial Bold");
      _label("t1_ls_sl", px+116, y+2, "SL:",    0x445566, 7);
      _label("t1_ls_sv", px+130, y+2, "--×ATR", 0x778899, 7);
      _label("t1_ls_rl", px+215, y+2, "RR:",    0x445566, 7);
      _label("t1_ls_rv", px+229, y+2, "1:--",   0xEEEEEE, 7);
      y+=15;

      // ── A: REGIME & ENTRY ────────────────────────────────────────────────
      _rect("t1_ah_bg", px+2, y, W-4, 13, 0x071828, 0x0D2E50);
      _rect("t1_ad",    px+5, y+3, 5, 5, 0x00C875);
      _label("t1_ah",   px+13, y+1, "A  REGIME & ENTRY", 0x00C875, 8, "Arial Bold");
      y+=14;
      _rect("t1_a_row1", px+2, y, W-4, 15, 0x040C14, 0x0A1828);
      _label("t1_a1k",   px+8, y+3, "Entry type",  0x668899, 8);
      _label("t1_a1v",   VX,   y+3, "--",           0x00B4D8, 9, "Arial Bold");
      y+=16;
      _rect("t1_a_row2", px+2, y, W-4, 15, 0x050D15, 0x0A1828);
      _label("t1_a2k",   px+8, y+3, "Direction",   0x668899, 8);
      _label("t1_a2v",   VX,   y+3, "--",           0x00C875, 9, "Arial Bold");
      y+=16;
      // Session + MinScore on one row
      _rect("t1_a_row3", px+2, y, W-4, 15, 0x040C14, 0x0A1828);
      _label("t1_a3k",   px+8,   y+3, "Session",    0x668899, 8);
      _label("t1_a3v",   VX,     y+3, "--",          0xCCDDEE, 8);
      _label("t1_a4k",   px+170, y+3, "MinScr:",    0x668899, 8);
      _label("t1_a4v",   px+218, y+3, "--",          0xCCDDEE, 8);
      _label("t1_a4c",   px+238, y+3, "",             0x00C875, 7);
      // dummy for row4 (not built, but render uses it)
      _label("t1_a_row4",px+2, y-100, "", 0x000000, 7);
      y+=17;

      // ── B: SIZING & RISK ─────────────────────────────────────────────────
      _rect("t1_bh_bg", px+2, y, W-4, 13, 0x071828, 0x0D2E50);
      _rect("t1_bd",    px+5, y+3, 5, 5, 0x00B4D8);
      _label("t1_bh",   px+13, y+1, "B  SIZING & RISK", 0x00B4D8, 8, "Arial Bold");
      y+=14;
      _rect("t1_b_row1", px+2, y, W-4, 15, 0x040C14, 0x0A1828);
      _label("t1_b1k",   px+8, y+3, "Risk mode",   0x668899, 8);
      _label("t1_b1v",   VX,   y+3, "--",           0xCCDDEE, 8);
      y+=16;
      _rect("t1_b_row2", px+2, y, W-4, 15, 0x050D15, 0x0A1828);
      _label("t1_b2k",   px+8, y+3, "Gate → Pos%", 0x668899, 8);
      _label("t1_b2gl",  VX,   y+3, "--",           0xCCDDEE, 8, "Arial Bold");
      y+=16;
      _rect("t1_b_bar_bg", px+2, y, W-4, 13, 0x050810, 0x0D1828);
      _label("t1_b2al",    px+7,   y+2, "0",         0x223344, 7);
      _label("t1_b2bar",   px+15,  y+2, "░░░░░░░░░░░░░░░░", 0x00C875, 7);
      _label("t1_b2pv",    px+185, y+2, "--%",       0xEEEEEE, 8, "Arial Bold");
      _label("t1_b2cap",   px+234, y+2, "│125",      0x334455, 7);
      y+=15;
      // SL + RR + Eff on one row
      _rect("t1_b_row3", px+2, y, W-4, 15, 0x040C14, 0x0A1828);
      _label("t1_b3k",   px+8,   y+3, "Eff:",       0x668899, 7);
      _label("t1_b3f",   px+30,  y+3, "--",          0x778899, 7);
      _label("t1_b4k",   px+118, y+3, "SL:",         0x668899, 7);
      _label("t1_b4v",   px+134, y+3, "--×ATR",      0xCCDDEE, 7);
      _label("t1_b5k",   px+196, y+3, "RR:",         0x668899, 7);
      _label("t1_b5v",   px+212, y+3, "1:--",        0xCCDDEE, 7);
      // dummies for unused rows
      _label("t1_b_row4", px+2, y-100, "", 0x000000, 7);
      _label("t1_b_row5", px+2, y-100, "", 0x000000, 7);
      _label("t1_b6k",    px+2, y-100, "", 0x000000, 7);
      _label("t1_b6v",    px+2, y-100, "", 0x000000, 7);
      _label("t1_tsl",    px+2, y-100, "", 0x000000, 7);
      y+=17;

      // ── C: INPUT vs CLOUD ────────────────────────────────────────────────
      _rect("t1_ch_bg", px+2, y, W-4, 13, 0x071828, 0x0D2E50);
      _rect("t1_cd",    px+5, y+3, 5, 5, 0xFFA500);
      _label("t1_ch_hdr",px+13, y+1, "C  INPUT vs CLOUD", 0xFFA500, 8, "Arial Bold");
      y+=14;
      _rect("t1_cc_hdr_bg", px+2, y, W-4, 11, 0x050810, 0x0A1020);
      _label("t1_cc_p", px+28,  y+1, "param",    0x334455, 7);
      _label("t1_cc_l", px+118, y+1, "local",    0x334455, 7);
      _label("t1_cc_a", px+168, y+1, "advice",   0x334455, 7);
      y+=12;
      for(int i=1;i<=6;i++)
      {
         string si=IntegerToString(i);
         _rect("t1_cr"+si+"_bg",  px+2,  y, W-4, 13, 0x060C16, 0x0A1424);
         _label("t1_cr"+si+"_st", px+6,  y+2, "[--]", 0x445566, 7);
         _label("t1_cr"+si+"_k",  px+28, y+2, "--",   0x668899, 7);
         _label("t1_cr"+si+"_l",  px+116,y+2, "--",   0x889AAA, 7);
         _label("t1_cr"+si+"_ar", px+158,y+2, "▶",    0x223344, 7);
         _label("t1_cr"+si+"_a",  px+168,y+2, "--",   0xCCDDEE, 7);
         y+=14;
      }
      _rect("t1_hl_bg", px+2, y, W-4, 15, 0x050810, 0x0A1020);
      _label("t1_hl",   px+8,  y+3, "Health:", 0x668899, 8);
      _label("t1_hbar", px+55, y+3, "░░░░░░░░░░", 0x00C875, 8);
      _label("t1_hsum", px+185,y+3, "--/6",    0x00C875, 9, "Arial Bold");
      // dummies for scope strip
      _label("t1_dh_bg", px+2, y-100, "", 0x000000, 7);
      _label("t1_dd",    px+2, y-100, "", 0x000000, 7);
      _label("t1_dh",    px+2, y-100, "", 0x000000, 7);
      _label("t1_d1k",   px+2, y-100, "", 0x000000, 7);
      _label("t1_d1v",   px+2, y-100, "", 0x000000, 7);
      _label("t1_d2v",   px+2, y-100, "", 0x000000, 7);
      _label("t1_d3k",   px+2, y-100, "", 0x000000, 7);
      _label("t1_d3v",   px+2, y-100, "", 0x000000, 7);
      _label("t1_d_row1",px+2, y-100, "", 0x000000, 7);
      _label("t1_d_row2",px+2, y-100, "", 0x000000, 7);
      y+=17;

      // ── STRATEGY DETAIL button ────────────────────────────────────────────
      _btn("t1_det_btn",  px+4, y, W-8, 22,
           "⚡  STRATEGY DETAIL  — View & Switch Presets", 0x040E20, 0x00B4D8);
      _label("t1_det_hint", px+8, y+25, "Opens browser · Changes apply in 30s", 0x2A3D50, 7);
   }

   // ==========================================================================
   // TAB 2: CONTROL (unchanged)
   // ==========================================================================
   void _BuildTab2(int px,int top)
   {
      int y=top;
      _label("t2_hdr", px+5,y,"Override Controls",0xE53935,9); y+=20;
      _btn("t2_emer",  px+5,y,PANEL_W-10,26,"EMERGENCY STOP",0xC00000,0xFFFFFF); y+=32;
      int hw=(PANEL_W-14)/2;
      _btn("t2_pause", px+5,      y,hw,  22,"PAUSE",    0x1A2535,0xFFFFFF);
      _btn("t2_flat",  px+5+hw+4, y,hw-2,22,"CLOSE ALL",0x8B2500,0xFFFFFF); y+=28;
      _btn("t2_unlock",px+5,y,PANEL_W-10,22,"UNLOCK ALL",0x374151,0x00B4D8); y+=30;
      _label("t2_sts", px+5,y,"Ready",0x00C875,8); y+=16;
      _divLine("t2_s1",px,y); y+=5;
      _label("t2_bh",  px+5,y,"CLOUD BRIDGE",0x2A3A4A,7,"Arial Bold"); y+=12;
      _label("t2_brd", px+5,y,"Bridge: --",  0x445566,7); y+=13;
      _label("t2_age", px+5,y,"Last HB: --", 0x445566,7); y+=13;
      _label("t2_lic", px+5,y,"License: --", 0x445566,7); y+=14;
      _divLine("t2_s2",px,y); y+=5;
      _label("t2_n1",  px+5,y,"Strategy config via RegimeFit Dashboard",0x2A3A4A,7); y+=11;
      _label("t2_n2",  px+5,y,"UNLOCK resets all GV lock flags",        0x2A3A4A,7);
   }

   // ==========================================================================
   // SHOW / HIDE
   // ==========================================================================
   void _ShowTab(int t)
   {
      m_tab=t;
      ObjectSetInteger(m_chart,_n("tab0"),OBJPROP_BGCOLOR,t==0?(color)0x1E4D8C:(color)0x1A2535);
      ObjectSetInteger(m_chart,_n("tab1"),OBJPROP_BGCOLOR,t==1?(color)0x005A4A:(color)0x1A2535);
      ObjectSetInteger(m_chart,_n("tab2"),OBJPROP_BGCOLOR,t==2?(color)0x6B1212:(color)0x1A2535);

      static string ids0[]={
         "t0_hb","t0_prof","t0_s1","t0_reg","t0_scr","t0_dir","t0_gtl",
         "t0_pl","t0_pb","t0_pv","t0_slv","t0_s2","t0_eq","t0_bal",
         "t0_dd","t0_risk","t0_s3","t0_zplbl","t0_zpb","t0_zpv","t0_dmp",
         "t0_s4","t0_tc","t0_ls","t0_rr","t0_tsl","t0_stt","t0_gtr"};

      // ids1 = khớp 100% với _BuildTab1 v3.5
      static string ids1[]={
         "t1_ph_bg","t1_pn","t1_src",
         "t1_score_bg","t1_sc_lbl","t1_sc_val","t1_sc_div",
         "t1_gate_bg","t1_gate_v","t1_dir_bg","t1_dir_v",
         "t1_pp_lbl","t1_pp_val",
         "t1_ls_bg","t1_ls_gl","t1_ls_gv","t1_ls_sl","t1_ls_sv","t1_ls_rl","t1_ls_rv",
         "t1_ah_bg","t1_ad","t1_ah",
         "t1_a_row1","t1_a1k","t1_a1v",
         "t1_a_row2","t1_a2k","t1_a2v",
         "t1_a_row3","t1_a3k","t1_a3v","t1_a4k","t1_a4v","t1_a4c",
         "t1_a_row4",
         "t1_bh_bg","t1_bd","t1_bh",
         "t1_b_row1","t1_b1k","t1_b1v",
         "t1_b_row2","t1_b2k","t1_b2gl",
         "t1_b_bar_bg","t1_b2al","t1_b2bar","t1_b2pv","t1_b2cap",
         "t1_b_row3","t1_b3k","t1_b3f","t1_b4k","t1_b4v","t1_b5k","t1_b5v",
         "t1_b_row4","t1_b_row5","t1_b6k","t1_b6v","t1_tsl",
         "t1_ch_bg","t1_cd","t1_ch_hdr",
         "t1_cc_hdr_bg","t1_cc_p","t1_cc_l","t1_cc_a",
         "t1_cr1_bg","t1_cr1_st","t1_cr1_k","t1_cr1_l","t1_cr1_ar","t1_cr1_a",
         "t1_cr2_bg","t1_cr2_st","t1_cr2_k","t1_cr2_l","t1_cr2_ar","t1_cr2_a",
         "t1_cr3_bg","t1_cr3_st","t1_cr3_k","t1_cr3_l","t1_cr3_ar","t1_cr3_a",
         "t1_cr4_bg","t1_cr4_st","t1_cr4_k","t1_cr4_l","t1_cr4_ar","t1_cr4_a",
         "t1_cr5_bg","t1_cr5_st","t1_cr5_k","t1_cr5_l","t1_cr5_ar","t1_cr5_a",
         "t1_cr6_bg","t1_cr6_st","t1_cr6_k","t1_cr6_l","t1_cr6_ar","t1_cr6_a",
         "t1_hl_bg","t1_hl","t1_hbar","t1_hsum",
         "t1_dh_bg","t1_dd","t1_dh","t1_d1k","t1_d1v","t1_d2v","t1_d3k","t1_d3v",
         "t1_d_row1","t1_d_row2",
         "t1_det_btn","t1_det_hint"};

      static string ids2[]={
         "t2_hdr","t2_emer","t2_pause","t2_flat","t2_unlock","t2_sts",
         "t2_s1","t2_bh","t2_brd","t2_age","t2_lic","t2_s2","t2_n1","t2_n2"};

      for(int i=0;i<ArraySize(ids0);i++) _vis(ids0[i],t==0);
      for(int i=0;i<ArraySize(ids1);i++) _vis(ids1[i],t==1);
      for(int i=0;i<ArraySize(ids2);i++) _vis(ids2[i],t==2);
      ChartRedraw(m_chart);
   }

   // ==========================================================================
   // RENDER TAB 0 (unchanged)
   // ==========================================================================
   void _RenderTab0(const SystemStateSnapshot &ss)
   {
      int age=(int)(TimeCurrent()-ss.last_heartbeat);
      string hb; color hbc;
      if(ss.last_heartbeat==0)  { hb="Cloud: offline";                     hbc=0xE53935; }
      else if(age<45)           { hb="Cloud: OK "+IntegerToString(age)+"s"; hbc=0x00C875; }
      else if(age<90)           { hb="Cloud: stale "+IntegerToString(age)+"s"; hbc=0xFFA500; }
      else                      { hb="Cloud: OFFLINE";                     hbc=0xE53935; }
      _set("t0_hb",hb,hbc);

      string pn=StringLen(ss.active_profile_name)>0?ss.active_profile_name:"Default";
      _set("t0_prof","Profile: "+pn,0x00B4D8);

      string reg=StringLen(ss.active_symbol_regime)>0?ss.active_symbol_regime:"UNKNOWN";
      color rc;
      if(StringFind(reg,"TREND_FOLLOW")>=0)      rc=0x00C875;
      else if(StringFind(reg,"TREND_INVERT")>=0) rc=0xE57373;
      else if(StringFind(reg,"RANGE")>=0)        rc=0x00B4D8;
      else if(StringFind(reg,"AVOID")>=0)        rc=0xE53935;
      else                                       rc=0xFFA500;
      _set("t0_reg","REGIME: "+reg,rc);
      _set("t0_scr","Scr:"+IntegerToString(ss.cloud_score),0xEEEEEE);

      string dt; color dc;
      switch(ss.direction_mode)
      { case DIR_BUY_ONLY:  dt="▲ BUY ONLY";  dc=0x00C875; break;
        case DIR_SELL_ONLY: dt="▼ SELL ONLY"; dc=0xE53935; break;
        case DIR_BOTH:      dt="↕ BOTH";      dc=0x00B4D8; break;
        case DIR_NO_ENTRY:  dt="✖ NO ENTRY";  dc=0xE53935; break;
        default:            dt="? LOADING";   dc=0x445566; break; }
      _set("t0_dir",dt,dc);

      RegimeContext ctx=(g_radar_count>0)?g_radar[0]:DefaultRegimeContext("--");
      string gl; color gc;
      int sc=ctx.score;
      if(!ctx.allow_trade||sc<30) { gl="BLOCK";   gc=0xE53935; }
      else if(sc<50)              { gl="WARN";    gc=0xFF6600; }
      else if(sc<70)              { gl="CAUTION"; gc=0xFFA500; }
      else if(sc<85)              { gl="ALLOW";   gc=0x00C875; }
      else                        { gl="SCALE▲";  gc=0x00E5FF; }
      _set("t0_gtl","Gate:"+gl,gc);

      int pct=ctx.allow_trade?ctx.position_pct:0;
      double pF=MathMin(1.0,pct/125.0);
      color pbc=pct>100?(color)0x00E5FF:pct>60?(color)0x00C875:pct>30?(color)0xFFA500:(color)0xE53935;
      _set("t0_pb",_bar(pF,10),pbc);
      _set("t0_pv",IntegerToString(pct)+"%",pbc);
      _set("t0_slv","SL:"+DoubleToString(ctx.sl_multiplier,1)+"x",0x778899);

      _set("t0_eq","Eq: "+DoubleToString(ss.equity,0),0xEEEEEE);
      _set("t0_bal","Bal: "+DoubleToString(ss.balance,0),0x778899);
      double dd=ss.daily_dd_pct*100;
      _set("t0_dd","DD: "+DoubleToString(dd,1)+"%",dd>3?(color)0xE53935:dd>1.5?(color)0xFFA500:(color)0xEEEEEE);
      _set("t0_risk","Risk: "+DoubleToString(ss.portfolio_risk_pct*100,1)+"%",0xEEEEEE);

      double z=ss.z_pressure;
      color zc=z>0.7?(color)0xE53935:z>0.4?(color)0xFFA500:(color)0x00C875;
      _set("t0_zpb",_bar(z,10),zc);
      _set("t0_zpv",DoubleToString(z,2),0xEEEEEE);
      _set("t0_dmp","dmp:"+DoubleToString(ctx.damping_factor,2),0x445566);

      _set("t0_tc","Trades: "+IntegerToString(ss.trade_count_today),0x445566);
      _set("t0_ls","Streak: "+IntegerToString(ss.loss_streak),ss.loss_streak>=2?(color)0xFFA500:(color)0x445566);
      _set("t0_rr","RR: "+DoubleToString(g_profile.rr_ratio,1),0xEEEEEE);
      _set("t0_tsl","TSL: "+(g_profile.trailing_sl?"ON":"off"),g_profile.trailing_sl?(color)0x00C875:(color)0x445566);

      string st; color sc2;
      if(ss.emergency)         { st="● EMERGENCY"; sc2=0xE53935; }
      else if(ss.cloud_locked) { st="● LOCKED";    sc2=0xFFA500; }
      else switch(ss.system_state)
      { case SYS_FLAT:       st="● FLAT";      sc2=0xE53935; break;
        case SYS_LOCKED:     st="● LOCKED";    sc2=0xFFA500; break;
        case SYS_DEFENSIVE:  st="● DEFENSIVE"; sc2=0xFFA500; break;
        case SYS_AGGRESSIVE: st="● SCALING";   sc2=0x00E5FF; break;
        default:             st="● ACTIVE";    sc2=0x00C875; break; }
      _set("t0_stt",st,sc2);
      if(StringLen(ss.last_gate_reason)>0) _set("t0_gtr",ss.last_gate_reason,0xFFA500);
      else                                  _set("t0_gtr","",0x445566);
      ChartRedraw(m_chart);
   }

   // ==========================================================================
   // RENDER TAB 1 — Strategy Dashboard v3.2
   // ==========================================================================
   void _RenderTab1(const SystemStateSnapshot &ss)
   {
      StrategyProfile p  =g_profile;
      RegimeContext  ctx =(g_radar_count>0)?g_radar[0]:DefaultRegimeContext("--");

      // ── Profile header ────────────────────────────────────────────────────
      string pn=p.is_loaded?p.profile_name:"Default (cloud offline)";
      _set("t1_pn",  "Profile: "+pn,    p.is_loaded?(color)0xFFFFFF:(color)0xFFA500);
      _set("t1_src", p.is_loaded?"[Cloud]":"[Local]",
           p.is_loaded?(color)0x00C875:(color)0xFFA500);

      // ── SCORE + GATE hero ─────────────────────────────────────────────────
      // Score value — colour by range
      int sc=ctx.score;
      color scC = sc>=85?(color)0x00E5FF : sc>=70?(color)0x00C875 : sc>=50?(color)0xFFA500
                                         : sc>=30?(color)0xFF6600 : (color)0xE53935;
      _set("t1_sc_val", IntegerToString(sc), scC);

      // Gate badge
      string gL; color gLC;
      int cap_pct=(p.risk_mode==RISK_CONSERVATIVE)?60:(p.risk_mode==RISK_AGGRESSIVE)?125:100;
      int eff_pct=ctx.allow_trade?MathMin(ctx.position_pct,cap_pct):0;
      if(!ctx.allow_trade||sc<30) { gL="BLOCK";   gLC=0xE53935; }
      else if(sc<50)               { gL="WARN";    gLC=0xFF6600; }
      else if(sc<70)               { gL="CAUTION"; gLC=0xFFA500; }
      else if(sc<85)               { gL="ALLOW";   gLC=0x00C875; }
      else                         { gL="SCALE ▲"; gLC=0x00E5FF; }
      _set("t1_gate_v", gL, gLC);
      ObjectSetInteger(m_chart,_n("t1_gate_bg"),OBJPROP_BGCOLOR,
                       gLC==0xE53935?0x200808:gLC==0xFF6600?0x1A0800:
                       gLC==0xFFA500?0x1A1000:gLC==0x00E5FF?0x001A1A:0x0A1E0A);

      // Direction badge
      string dt2; color dc2;
      switch(ctx.direction_mode)
      { case DIR_BUY_ONLY:  dt2="▲ BUY ONLY";  dc2=0x00C875; break;
        case DIR_SELL_ONLY: dt2="▼ SELL ONLY"; dc2=0xE53935; break;
        case DIR_BOTH:      dt2="↕ BOTH";      dc2=0x00B4D8; break;
        case DIR_NO_ENTRY:  dt2="✖ NO ENTRY";  dc2=0xE53935; break;
        default:            dt2="? --";        dc2=0x445566; break; }
      _set("t1_dir_v", dt2, dc2);

      // Pos%
      _set("t1_pp_val", IntegerToString(eff_pct)+"%", scC);

      // ── Live status strip ─────────────────────────────────────────────────
      _set("t1_ls_gv", gL+" "+IntegerToString(eff_pct)+"%", gLC);
      _set("t1_ls_sv", DoubleToString(ctx.sl_multiplier,1)+"×ATR",
           ctx.sl_multiplier>1.8?(color)0xFFA500:(color)0x778899);
      _set("t1_ls_rv", "1:"+DoubleToString(p.rr_ratio,1), 0xEEEEEE);

      // ── Section A ─────────────────────────────────────────────────────────
      string et; color etc;
      switch(p.entry_type)
      { case ENTRY_BREAKOUT_ONLY: et="BREAKOUT ONLY"; etc=0x00B4D8; break;
        case ENTRY_PULLBACK_ONLY: et="PULLBACK ONLY"; etc=0x7986CB; break;
        default:                  et="BOTH";          etc=0x778899; break; }
      _set("t1_a1v", et, etc);
      _set("t1_a2v", dt2, dc2);

      string sess="";
      if((p.session_filter&SESSION_LONDON) !=0) sess+="LON ";
      if((p.session_filter&SESSION_NY)     !=0) sess+="NY ";
      if((p.session_filter&SESSION_ASIA)   !=0) sess+="ASIA ";
      if((p.session_filter&SESSION_WEEKEND)!=0) sess+="WKD";
      if(StringLen(sess)==0||(uint)p.session_filter==(uint)SESSION_ALL) sess="ALL";
      _set("t1_a3v", StringTrimRight(sess), 0xCCDDEE);

      bool scoreOk=(ctx.score>=p.min_score_entry);
      _set("t1_a4v", IntegerToString(p.min_score_entry), 0xCCDDEE);
      _set("t1_a4c", "live:"+IntegerToString(ctx.score)+(scoreOk?" ✓":" ✗"),
           scoreOk?(color)0x00C875:(color)0xE53935);

      // ── Section B ─────────────────────────────────────────────────────────
      string rm; color rmc;
      switch(p.risk_mode)
      { case RISK_CONSERVATIVE: rm="CONSERVATIVE  cap 60%"; rmc=0xFFA500; break;
        case RISK_AGGRESSIVE:   rm="AGGRESSIVE  up 125%";   rmc=0x00E5FF; break;
        default:                rm="NORMAL  up 100%";       rmc=0x00C875; break; }
      _set("t1_b1v", rm, rmc);

      string g2L; color g2C;
      if(!ctx.allow_trade||sc<30) { g2L="BLOCK → 0%";    g2C=0xE53935; }
      else if(sc<50)               { g2L="WARN → 30%";    g2C=0xFF6600; }
      else if(sc<70)               { g2L="CAUTION → 60%"; g2C=0xFFA500; }
      else if(sc<85)               { g2L="ALLOW → 100%";  g2C=0x00C875; }
      else                         { g2L="SCALE → 125%";  g2C=0x00E5FF; }
      if(eff_pct<ctx.position_pct) g2L+="  (cap:"+IntegerToString(eff_pct)+"%)";
      _set("t1_b2gl", g2L, g2C);

      // Pos% bar — 16 chars wide
      double barF=eff_pct/125.0;
      color  barC=eff_pct>100?(color)0x00E5FF:eff_pct>60?(color)0x00C875
                 :eff_pct>30?(color)0xFFA500:(color)0xE53935;
      _set("t1_b2bar", _bar(barF,16), barC);
      _set("t1_b2pv",  IntegerToString(eff_pct)+"%", barC);

      string effStr=IntegerToString(eff_pct)+"% × dmp:"
                   +DoubleToString(ctx.damping_factor,2)+" × exp";
      _set("t1_b3f", effStr, 0x667788);

      _set("t1_b4v", DoubleToString(ctx.sl_multiplier,2)+"×ATR",
           ctx.sl_multiplier>1.8?(color)0xFFA500:(color)0x00C875);
      _set("t1_b5v", "1:"+DoubleToString(p.rr_ratio,1), 0xCCDDEE);
      _set("t1_b6v", IntegerToString((int)(p.max_spread_pct*100))+"% ATR", 0xCCDDEE);
      _set("t1_tsl",  p.trailing_sl?"TSL: ON":"TSL: off",
           p.trailing_sl?(color)0x00C875:(color)0x445566);

      // ── Section C — 6 checks ─────────────────────────────────────────────
      int okCount=0;

      // 1. BaseRisk
      _setCheckRow("t1_cr1","BaseRisk",
                   DoubleToString(m_inputs.base_risk_pct*100,1)+"%","local only",true,false);
      okCount++;

      // 2. MaxTotalRisk 3–10%
      bool c2ok=(m_inputs.max_total_risk>=0.03&&m_inputs.max_total_risk<=0.10);
      _setCheckRow("t1_cr2","MaxRisk",
                   DoubleToString(m_inputs.max_total_risk*100,0)+"%",
                   c2ok?"in range [3-10%]":"out of range!",c2ok,false);
      if(c2ok) okCount++;

      // 3. Circuit < MaxTotalRisk
      bool c3ok=(m_inputs.circuit_breaker<m_inputs.max_total_risk);
      _setCheckRow("t1_cr3","Circuit",
                   DoubleToString(m_inputs.circuit_breaker*100,0)+"%",
                   c3ok?"< MaxRisk ✓":"≥ MaxRisk!",c3ok,false);
      if(c3ok) okCount++;

      // 4. Cooldown ≥30s
      bool c4ok  =(m_inputs.cooldown_sec>=30);
      bool c4warn=(m_inputs.cooldown_sec>=10&&m_inputs.cooldown_sec<30);
      _setCheckRow("t1_cr4","Cooldown",
                   IntegerToString(m_inputs.cooldown_sec)+"s",
                   c4ok?"≥30s OK":c4warn?"rec ≥30s":"too low!",c4ok,c4warn);
      if(c4ok||c4warn) okCount++;

      // 5. MaxTradesPerDay 2–30
      bool c5ok=(m_inputs.max_trades_day>=2&&m_inputs.max_trades_day<=30);
      _setCheckRow("t1_cr5","MaxTrades",
                   IntegerToString(m_inputs.max_trades_day),
                   c5ok?"in range ✓":"check!",c5ok,false);
      if(c5ok) okCount++;

      // 6. TF match
      string tfLocal=_tfStr(m_inputs.timeframe_min);
      bool c6ok=(tfLocal==m_inputs.radar_tf);
      _setCheckRow("t1_cr6","TF match",tfLocal,
                   c6ok?"= RadarTF ✓":"≠ "+m_inputs.radar_tf,c6ok,false);
      if(c6ok) okCount++;

      double hF=okCount/6.0;
      color  hC=okCount>=5?(color)0x00C875:okCount>=3?(color)0xFFA500:(color)0xE53935;
      _set("t1_hbar", _bar(hF,10), hC);
      _set("t1_hsum", IntegerToString(okCount)+"/6", hC);

      // ── Section D ─────────────────────────────────────────────────────────
      string syms=m_inputs.symbols;
      if(StringLen(syms)>36) syms=StringSubstr(syms,0,34)+"..";
      _set("t1_d1v", syms, 0x00B4D8);
      bool tfOk=(tfLocal==m_inputs.radar_tf);
      color tfc=tfOk?(color)0x00C875:(color)0xFFA500;
      _set("t1_d2v", tfLocal,            tfc);
      _set("t1_d3v", m_inputs.radar_tf,  tfc);

      ChartRedraw(m_chart);
   }

   // ==========================================================================
   // RENDER TAB 2 (unchanged)
   // ==========================================================================
   void _RenderTab2()
   {
      string bs=g_bridge_ok
         ?("Online – "+TimeToString(g_last_heartbeat,TIME_SECONDS)):"OFFLINE";
      _set("t2_brd","Bridge: "+bs,g_bridge_ok?(color)0x00C875:(color)0xE53935);
      if(g_last_heartbeat>0)
      {
         int a=(int)(TimeCurrent()-g_last_heartbeat);
         _set("t2_age","Last HB: "+IntegerToString(a)+"s ago",
              a<60?(color)0x00C875:a<120?(color)0xFFA500:(color)0xE53935);
      }
      else _set("t2_age","Last HB: never",0x445566);
      string licSt=g_bridge_ok?(g_radar_count>0?"Active":"Pending"):"Unverified";
      color  licC =g_bridge_ok?(g_radar_count>0?(color)0x00C875:(color)0xFFA500):(color)0xE53935;
      _set("t2_lic","License: "+licSt,licC);
      ChartRedraw(m_chart);
   }

public:

   void Init()
   {
      m_created=false; m_paused=false; m_tab=0; m_chart=0;
      m_inputs.base_risk_pct=0.01; m_inputs.max_total_risk=0.05;
      m_inputs.max_symbol_risk=0.02; m_inputs.circuit_breaker=0.03;
      m_inputs.max_trades_day=20; m_inputs.max_loss_streak=3;
      m_inputs.cooldown_sec=60; m_inputs.symbols="?";
      m_inputs.timeframe_min=60; m_inputs.radar_tf="H1";
   }

   // SetInputs() API unchanged — backward-compatible
   void SetInputs(double baseRisk,double maxTotalRisk,double maxSymRisk,
                  double circBr,int maxTrades,int maxStreak,int cooldown,
                  string syms,int tfMin,string radarTF)
   {
      m_inputs.base_risk_pct  =baseRisk;
      m_inputs.max_total_risk =maxTotalRisk;
      m_inputs.max_symbol_risk=maxSymRisk;
      m_inputs.circuit_breaker=circBr;
      m_inputs.max_trades_day =maxTrades;
      m_inputs.max_loss_streak=maxStreak;
      m_inputs.cooldown_sec   =cooldown;
      m_inputs.symbols        =syms;
      m_inputs.timeframe_min  =tfMin;
      m_inputs.radar_tf       =radarTF;
   }

   bool Create(long chart=0){ m_chart=chart; m_created=true; _Build(); return true; }
   void Destroy()            { _DeleteAll(); m_created=false; }

   void Render(const SystemStateSnapshot &ss)
   {
      if(!m_created) return;
      if(m_tab==0) _RenderTab0(ss);
      if(m_tab==1) _RenderTab1(ss);
      if(m_tab==2) _RenderTab2();
   }

   void ChartEvent(const int id,const long &lp,const double &dp,const string &sp)
   {
      if(!m_created||id!=CHARTEVENT_OBJECT_CLICK) return;
      if(sp==_n("tab0")){ _ShowTab(0); return; }
      if(sp==_n("tab1")){ _ShowTab(1); return; }
      if(sp==_n("tab2")){ _ShowTab(2); return; }
      if(sp==_n("t2_emer"))
      {
         ObjectSetInteger(m_chart,sp,OBJPROP_STATE,false);
         GlobalVariableSet(GV_EMERGENCY,1.0);
         _set("t2_sts","EMERGENCY ACTIVATED",0xE53935); ChartRedraw(m_chart); return;
      }
      if(sp==_n("t2_pause"))
      {
         ObjectSetInteger(m_chart,sp,OBJPROP_STATE,false);
         m_paused=!m_paused;
         GlobalVariableSet(GV_PAUSE,m_paused?1.0:0.0);
         ObjectSetInteger(m_chart,_n("t2_pause"),OBJPROP_BGCOLOR,m_paused?(color)0xFF8C00:(color)0x1A2535);
         ObjectSetString (m_chart,_n("t2_pause"),OBJPROP_TEXT,   m_paused?"RESUME":"PAUSE");
         _set("t2_sts",m_paused?"Paused":"Running",m_paused?(color)0xFFA500:(color)0x00C875);
         ChartRedraw(m_chart); return;
      }
      if(sp==_n("t2_flat"))
      {
         ObjectSetInteger(m_chart,sp,OBJPROP_STATE,false);
         GlobalVariableSet(GV_CLOSE_ALL_PAUSE,1.0);
         _set("t2_sts","Closing all...",0xFFA500); ChartRedraw(m_chart); return;
      }
      if(sp==_n("t2_unlock"))
      {
         ObjectSetInteger(m_chart,sp,OBJPROP_STATE,false);
         GlobalVariableSet(GV_LOCK,0.0);
         GlobalVariableSet(GV_EMERGENCY,0.0);
         GlobalVariableSet(GV_PAUSE,0.0);
         m_paused=false;
         ObjectSetInteger(m_chart,_n("t2_pause"),OBJPROP_BGCOLOR,(color)0x1A2535);
         ObjectSetString (m_chart,_n("t2_pause"),OBJPROP_TEXT,"PAUSE");
         _set("t2_sts","Unlocked",0x00C875); ChartRedraw(m_chart); return;
      }

      // ── STRATEGY DETAIL button — mở browser với strategy_detail.html ─────
      if(sp==_n("t1_det_btn"))
      {
         ObjectSetInteger(m_chart,sp,OBJPROP_STATE,false);
         // Build URL với license key + account + TF để trang web auto-load đúng profile
         string url = "http://47.129.243.206:8000"
                    + "/strategy/detail"
                    + "?tf="      + m_inputs.radar_tf
                    + "&symbols=" + m_inputs.symbols;
         // ShellExecuteW mở default browser trên Windows (MT5 chạy trên Windows)
         ShellExecuteW(0,"open",url,"","",1);
         _set("t1_det_hint","Opening browser...",0x00B4D8);
         ChartRedraw(m_chart);
         return;
      }
   }
};


// ============================================================================
// SECTION: ZArmorKernel_v30.mq5
// ============================================================================
// ==============================================================================
// Z-ARMOR KERNEL v3.0  — Domain-Aligned Semi-EA
// Single-file edition. Generated by merge_zarmorkernel.py (v3 config).
//
// Architecture: 3-Domain model
//   Domain 1 (Z-Cloud): Market intelligence, risk params, ML regime
//   Domain 2 (RegimeFit Dashboard): Strategy templates, direction recommendation
//   Domain 3 (This EA): Gate check, size, execute
//
// Key changes from v2.1:
//   - BoltVolmanStrategy → RegimeGateFilter (timing only, no self-direction)
//   - RiskEngine (5 sub-models) → LocalSafetyNet (CircuitBreaker + ExposureGate)
//   - 6-multiplier lot sizing → SizingEngine 3-param formula
//   - Panel 3-tab+11 inputs → 2-tab Monitor+Emergency (settings from cloud)
//   - StrategyProfile: trader creates on dashboard, EA reads via heartbeat
//   - direction_mode injected from cloud radar_map per-symbol
//
// IMPORTANT: MT5 > Tools > Options > Expert Advisors > Allow WebRequest
//            Add URL: http://47.129.243.206:8000
// ==============================================================================

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Controls\Dialog.mqh>
#include <Controls\Label.mqh>
#include <Controls\Button.mqh>

// ─── Forward-declare cloud bridge globals (defined in cloud_bridge.mqh) ───────
// (included transitively via scheduler)

// ─── Input parameters ─────────────────────────────────────────────────────────
// NOTE v3.0: Risk parameters (BaseRisk, ATRMult, etc.) are intentionally fewer.
//   Profile-level settings (min_score, rr_ratio, session) come from cloud template.
//   Only infrastructure-level inputs remain here.

input string  Symbols         = "XAUUSDm,BTCUSDm";   // Symbols (comma-separated)
input int     Timeframe       = 60;                    // Timeframe in minutes (60=H1)
input int     BarsToLoad      = 150;                   // Bars to load per symbol
input long    MagicNumber     = 900001;                // Magic number

// ── Risk infrastructure
input double  BaseRisk        = 0.01;   // Base risk per trade (1% equity)
input double  MaxTotalRisk    = 0.05;   // Max total portfolio risk (5%)
input double  MaxSymbolRisk   = 0.02;   // Max risk per symbol (2%)
input double  CircuitBreaker  = 0.03;   // Circuit breaker — balance DD (3%)

// ── State machine
input int     MaxTradesPerDay = 20;     // Daily trade limit
input int     MaxLossStreak   = 3;      // Max consecutive losses before pause
input int     CooldownSeconds = 60;     // Min seconds between trades

// ── Cloud Bridge
input string  CloudURL        = "http://47.129.243.206:8000"; // Cloud server URL
input int     BridgeInterval  = 30;     // Heartbeat interval (seconds, min 30)
input string  LicenseKey      = "";     // License key (from Z-Armor dashboard)
input string  RadarTF         = "H1";  // Radar timeframe sent to cloud

// ─── Core objects ──────────────────────────────────────────────────────────────
MT5Adapter           g_adapter;
LocalSafetyNet       g_safety;
SizingEngine         g_sizer;
ExecutionEngine      g_exec;
MultiSymbolScheduler g_scheduler;
PanelController      g_panel;

// ─── GV helper functions ───────────────────────────────────────────────────────
bool   gvBool(const string &k)              { return GlobalVariableCheck(k) && GlobalVariableGet(k) != 0.0; }
double gvGet (const string &k, double def)  { return GlobalVariableCheck(k) ? GlobalVariableGet(k) : def; }

// ─── Session token (FIX-2: ZCloud requires handshake before heartbeat) ──────────
// Global session token obtained from POST /ea/handshake
string g_session_token = "";
bool   g_handshake_ok  = false;

// ─── Handshake ── POST /ea/handshake (FIX-2) ─────────────────────────────────
bool DoHandshake()
{
   if(StringLen(LicenseKey) == 0)
   {
      Print("[Bridge] LicenseKey not set — cannot handshake. Fill it in EA inputs.");
      return false;
   }

   string sym_parts[]; StringSplit(Symbols, ',', sym_parts);

   string json = StringFormat(
      "{\"license_key\":\"%s\",\"mt5_login\":\"%I64d\"," 
      "\"broker_server\":\"%s\",\"mt5_build\":\"%d\"}",
      LicenseKey,
      AccountInfoInteger(ACCOUNT_LOGIN),
      AccountInfoString(ACCOUNT_SERVER),
      (int)TerminalInfoInteger(TERMINAL_BUILD)
   );

   char req[], resp[]; string hdrs;
   StringToCharArray(json, req, 0, StringLen(json), CP_UTF8);

   int code = WebRequest("POST", CloudURL + "/ea/handshake",
                          "Content-Type: application/json\r\n",
                          8000, req, resp, hdrs);

   if(code == 200)
   {
      string body = CharArrayToString(resp);
      string pat  = "\"session_token\":\"";
      int idx = StringFind(body, pat);
      if(idx >= 0)
      {
         idx += StringLen(pat);
         int end = StringFind(body, "\"", idx);
         if(end > idx)
         {
            g_session_token = StringSubstr(body, idx, end - idx);
            g_handshake_ok  = true;
            // Also seed config from handshake response
            CloudBridge::ParseResponse(body);
            Print("[Bridge] Handshake OK | token=", StringSubstr(g_session_token,0,12), "...");
            return true;
         }
      }
      Print("[Bridge] Handshake: no session_token in response.");
      return false;
   }
   else if(code == 403)
   {
      string body = CharArrayToString(resp);
      Print("[Bridge] Handshake DENIED: ", StringSubstr(body, 0, 200));
      return false;
   }
   else if(code == -1)
   {
      Print("[Bridge] Handshake failed: Add URL to WebRequest whitelist: ", CloudURL);
      return false;
   }
   Print("[Bridge] Handshake HTTP ", code);
   return false;
}

// ─── BridgeTick — POST /ea/heartbeat with session_token (FIX-1: was GET /heartbeat) ──
void BridgeTick()
{
   string acct = IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN));

   // Build symbol list for radar context
   string sym_parts[]; int nsym = StringSplit(Symbols, ',', sym_parts);
   string syms_param = "";
   for(int i = 0; i < nsym; i++)
   {
      string s = sym_parts[i]; StringTrimLeft(s); StringTrimRight(s);
      if(i > 0) syms_param += ",";
      syms_param += s;
   }

   // FIX-1: ZCloud endpoint is POST /ea/heartbeat with JSON body + session_token
   // FIX-2: Re-handshake automatically if session missing or expired
   if(!g_handshake_ok || StringLen(g_session_token) == 0)
   {
      Print("[Bridge] No session token — attempting handshake first...");
      if(!DoHandshake()) return; // cannot heartbeat without session
   }

   // Compute daily PnL (same as v5.2)
   double daily_pnl = 0;
   datetime today = TimeCurrent() - (TimeCurrent() % 86400);
   HistorySelect(today, TimeCurrent());
   for(int di = 0; di < HistoryDealsTotal(); di++)
   {
      ulong tkt = HistoryDealGetTicket(di);
      long  dtp = HistoryDealGetInteger(tkt, DEAL_TYPE);
      if(dtp == DEAL_TYPE_BUY || dtp == DEAL_TYPE_SELL)
         daily_pnl += HistoryDealGetDouble(tkt, DEAL_PROFIT)
                    + HistoryDealGetDouble(tkt, DEAL_COMMISSION)
                    + HistoryDealGetDouble(tkt, DEAL_SWAP);
   }

   string json = StringFormat(
      "{\"session_token\":\"%s\",\"equity\":%.2f,\"balance\":%.2f,"
      "\"daily_pnl\":%.2f,\"symbols\":\"%s\",\"tf\":\"%s\"}",
      g_session_token,
      AccountInfoDouble(ACCOUNT_EQUITY),
      AccountInfoDouble(ACCOUNT_BALANCE),
      daily_pnl,
      syms_param,
      RadarTF
   );

   char   resp_data[];
   string resp_hdrs;
   char   post_data[];
   StringToCharArray(json, post_data, 0, StringLen(json), CP_UTF8);

   int code = WebRequest("POST", CloudURL + "/ea/heartbeat",
                          "Content-Type: application/json\r\n",
                          5000, post_data, resp_data, resp_hdrs);

   if(code == 200)
   {
      string body = CharArrayToString(resp_data);

      // Parse all cloud intelligence
      CloudBridge::ParseResponse(body);

      // Apply lock/emergency from top-level fields
      if(StringFind(body, "\"lock\":true")       >= 0) GlobalVariableSet(GV_LOCK,      1.0);
      if(StringFind(body, "\"lock\":false")      >= 0) GlobalVariableSet(GV_LOCK,      0.0);
      if(StringFind(body, "\"emergency\":true")  >= 0) GlobalVariableSet(GV_EMERGENCY, 1.0);
      if(StringFind(body, "\"emergency\":false") >= 0) GlobalVariableSet(GV_EMERGENCY, 0.0);

      GlobalVariableSet("ZARMOR_BRIDGE_ALIVE", (double)TimeCurrent());

      Print("[Bridge] OK | Profile=", g_profile.profile_name,
            " | Radars=", IntegerToString(g_radar_count),
            " | Damping=", DoubleToString(g_damping, 2));
   }
   else if(code == 401)
   {
      // Session expired — force re-handshake on next BridgeTick
      g_session_token = "";
      g_handshake_ok  = false;
      CloudBridge::SetOffline();
      Print("[Bridge] 401 — session expired, will re-handshake next cycle");
   }
   else if(code == -1)
   {
      CloudBridge::SetOffline();
      Print("[Bridge] ERROR: Add URL to MT5 > Tools > Options > Expert Advisors > WebRequest: ", CloudURL);
   }
   else
   {
      CloudBridge::SetOffline();
      Print("[Bridge] HTTP ", code);
   }
}

// ─── OnTimer ──────────────────────────────────────────────────────────────────
void OnTimer() { BridgeTick(); }

// ─── OnInit ───────────────────────────────────────────────────────────────────
int OnInit()
{
   // Initialize panel first (no-op if headless)
   g_panel.Init();

   // Core objects
   g_adapter.Init(MagicNumber);

   g_safety.Init(CircuitBreaker, MaxTotalRisk, MaxSymbolRisk,
                  MaxTradesPerDay, MaxLossStreak, CooldownSeconds);

   g_sizer.Init(BaseRisk);
   g_exec.Init(GetPointer(g_adapter));

   g_scheduler.Init(Symbols, Timeframe, BarsToLoad, MagicNumber,
                    GetPointer(g_adapter),
                    GetPointer(g_safety),
                    GetPointer(g_sizer),
                    GetPointer(g_exec),
                    BaseRisk);

   // Create panel
   if(!g_panel.Create(0))
      Print("[Kernel] Panel headless mode");

   // FIX-2: Handshake first, then start heartbeat cycle
   int safe_interval = MathMax(BridgeInterval, 30);
   EventSetTimer(safe_interval);
   if(!DoHandshake())
      Print("[Kernel] Warning: handshake failed at startup — will retry on first timer tick");
   else
      BridgeTick(); // first heartbeat immediately after successful handshake

   Print("[Kernel] Z-Armor Kernel v3.0 | Magic=", MagicNumber,
         " | Symbols=", Symbols,
         " | BaseRisk=", DoubleToString(BaseRisk * 100, 1), "%",
         " | CB=", DoubleToString(CircuitBreaker * 100, 1), "%");
   return INIT_SUCCEEDED;
}

// ─── OnDeinit ─────────────────────────────────────────────────────────────────
void OnDeinit(const int reason)
{
   EventKillTimer();
   g_panel.Destroy();
   Print("[Kernel] Stop. Reason=", reason);
}

// ─── OnTick — 8-step v3.0 ────────────────────────────────────────────────────
void OnTick()
{
   // ── Step 0: Kernel alive heartbeat ────────────────────────────────────────
   GlobalVariableSet("ZARMOR_KERNEL_ALIVE", (double)TimeCurrent());

   // ── Step 1: Read cloud state (GV written by BridgeTick) ──────────────────
   bool locked    = gvBool(GV_LOCK);
   bool emergency = gvBool(GV_EMERGENCY);
   bool paused    = gvBool(GV_PAUSE);

   g_safety.SetCloudState(locked || paused, emergency);

   // ── Step 2: Load strategy profile (from g_profile, populated by BridgeTick)
   // No panel override in v3.0 — profile is cloud-authoritative
   // g_profile is already populated by CloudBridge::ParseResponse()
   if(!g_profile.is_loaded)
   {
      g_profile = DefaultStrategyProfile();
      Print("[Kernel] No cloud profile yet — using defaults");
   }

   // ── Step 3: Apply regime context per-symbol ────────────────────────────────
   // g_radar[] populated by CloudBridge — LocalSafetyNet reads on Evaluate()
   // Nothing extra needed here: scheduler calls CloudBridge::GetContext() per symbol

   // ── Step 4: Force close per-symbol requests ───────────────────────────────
   string sym_parts[]; int n = StringSplit(Symbols, ',', sym_parts);
   for(int i = 0; i < n && i < MAX_SYMBOLS; i++)
   {
      string s = sym_parts[i]; StringTrimLeft(s); StringTrimRight(s);
      string gvk = "ZARMOR_CLOSE_SYM_" + s;
      if(gvBool(gvk))
      {
         g_scheduler.ForceCloseSym(s);
         GlobalVariableSet(gvk, 0.0);
         Print("[Kernel] Force closed: ", s);
      }
   }

   // ── Step 5: Close all + pause ─────────────────────────────────────────────
   if(gvBool(GV_CLOSE_ALL_PAUSE))
   {
      g_exec.ForceFlat();
      GlobalVariableSet(GV_CLOSE_ALL_PAUSE, 0.0);
   }

   // ── Step 6 (priority): Emergency flat ────────────────────────────────────
   if(emergency)
   {
      g_exec.ForceFlat();
      // Fall through to render UI showing emergency state
   }

   // ── Step 7: Scheduler cycle (entry evaluation + execution) ────────────────
   // Skipped if emergency. Safety net inside will block if locked/paused.
   if(!emergency)
      g_scheduler.Update();

   // ── Step 8 (was 7+8 in v2.1): Build snapshot + render UI ─────────────────
   AccountSnapshot acct;
   g_scheduler.GetLastAccountSnap(acct);

   // Get primary symbol regime for display
   RegimeContext primary_ctx = (g_radar_count > 0)
                                ? g_radar[0]
                                : DefaultRegimeContext(sym_parts[0]);

   SystemStateSnapshot ss;
   ss.equity              = acct.equity;
   ss.balance             = acct.balance;
   ss.z_pressure          = g_damping > 0 ? (1.0 - g_damping) : 0.0; // invert: damping=1→no pressure
   ss.portfolio_risk_pct  = g_scheduler.GetLastTotalRisk();
   ss.daily_dd_pct        = (acct.balance > 0 && acct.equity < acct.balance)
                             ? (acct.balance - acct.equity) / acct.balance : 0.0;
   ss.trailing_dd_pct     = 0; // simplified — full calc in cloud
   ss.trade_count_today   = g_safety.GetTradeCount();
   ss.loss_streak         = g_safety.GetLossStreak();
   ss.cloud_locked        = locked || paused;
   ss.emergency           = emergency;
   ss.direction_mode      = primary_ctx.direction_mode;  // v3.0 NEW
   ss.active_profile_name = g_profile.profile_name;       // v3.0 NEW
   ss.active_symbol_regime = primary_ctx.regime_str;      // v3.0 NEW
   ss.cloud_score         = primary_ctx.score;             // v3.0 NEW
   ss.last_heartbeat      = g_last_heartbeat;              // v3.0 NEW
   ss.last_gate_reason    = locked    ? "Cloud locked" :
                            emergency ? "EMERGENCY"    :
                            paused    ? "Paused"       :
                            g_safety.IsCircuitBlown() ? "CircuitBreaker" : "";

   // Determine system state from cloud + local
   if(emergency || g_safety.IsCircuitBlown()) ss.system_state = SYS_FLAT;
   else if(locked || paused)                  ss.system_state = SYS_LOCKED;
   else if(primary_ctx.score < 30)            ss.system_state = SYS_DEFENSIVE;
   else if(primary_ctx.score < 60)            ss.system_state = SYS_NORMAL;
   else                                       ss.system_state = SYS_AGGRESSIVE;

   ss.capital_state = CAPITAL_STABLE; // simplified — cloud has full picture
   ss.alpha_state   = ALPHA_MODERATE; // deprecated in v3.0
   ss.regime        = REGIME_UNCERTAIN;

   g_panel.Render(ss);
}

// ─── OnTradeTransaction — ML flywheel (unchanged from v2.1) ──────────────────
void OnTradeTransaction(const MqlTradeTransaction &trans,
                         const MqlTradeRequest     &req,
                         const MqlTradeResult      &res)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(!HistoryDealSelect(trans.deal))            return;
   if(HistoryDealGetInteger(trans.deal, DEAL_MAGIC) != MagicNumber) return;
   long entry = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
   if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_INOUT) return;

   double pnl = HistoryDealGetDouble(trans.deal, DEAL_PROFIT)
              + HistoryDealGetDouble(trans.deal, DEAL_COMMISSION)
              + HistoryDealGetDouble(trans.deal, DEAL_SWAP);

   g_scheduler.RegisterTrade(TimeCurrent(), pnl);
   Print("[Kernel] Deal closed pnl=", DoubleToString(pnl, 2),
         " sym=", HistoryDealGetString(trans.deal, DEAL_SYMBOL));
}

// ─── OnChartEvent ─────────────────────────────────────────────────────────────
void OnChartEvent(const int id, const long &lp, const double &dp, const string &sp)
{
   g_panel.ChartEvent(id, lp, dp, sp);
}
