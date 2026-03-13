/**
 * RadarScoreEngine.js — Radar Architecture V4
 * Market Opportunity Engine · Z-Armor Platform
 *
 * Architecture: Precompute → Cache → Serve
 * RadarScore uses 4 orthogonal market dimensions (no indicator stacking).
 *
 * Weights:
 *   TrendStructure      35%
 *   VolatilityExpansion 30%
 *   LiquidityCondition  20%
 *   MomentumAlignment   15%
 *
 * Then applies RegimeMultiplier based on detected regime.
 *
 * Domain: Tactical Domain — consumes intelligence from Market Domain.
 * RadarScoreEngine does NOT contain core market logic.
 * Core market regime/volatility logic lives in MarketIntelligenceDomain (backend).
 *
 * Scalability:
 *   At 50k traders, this engine runs ONCE per market data update (server-side precompute).
 *   Results are cached server-side (~30s TTL).
 *   Clients read cached results — no per-user computation.
 *   This fallback (offline) mode is client-side only when API is unreachable.
 */

const RadarScoreEngine = (() => {

  // ─── Dimension Weights ───────────────────────────────────────────────
  const WEIGHTS = {
    trend      : 0.35,  // TrendStructure      (ADX, EMA structure)
    volatility : 0.30,  // VolatilityExpansion (ATR expansion, Bollinger width)
    liquidity  : 0.20,  // LiquidityCondition  (spread, session depth)
    momentum   : 0.15,  // MomentumAlignment   (multi-TF momentum confluence)
  };

  // ─── Regime Multipliers ──────────────────────────────────────────────
  // Applied AFTER base score calculation.
  // In RANGE regime: reduce trend weight effect (trend score less relevant).
  const REGIME_MULTIPLIERS = {
    EXPANSION    : 1.08,  // trending strongly → amplify
    TREND        : 1.05,  // directional trend → slightly amplify
    RANGE_BOUND  : 0.90,  // range market → reduce trend influence
    VOLATILE     : 0.82,  // chaotic → reduce signal reliability
    ACCUMULATION : 0.95,  // early phase → slight reduction
    DISTRIBUTION : 0.88,  // late trend → reduce
  };

  // ─── Asset Characteristic Seeds (offline fallback only) ─────────────
  // Real scores come from the backend precompute pipeline.
  const ASSET_PROFILES = {
    GOLD  : { trend: 0.78, volatility: 0.62, liquidity: 0.82, momentum: 0.74 },
    EURUSD: { trend: 0.60, volatility: 0.52, liquidity: 0.90, momentum: 0.65 },
    BTC   : { trend: 0.68, volatility: 0.78, liquidity: 0.72, momentum: 0.70 },
    NASDAQ: { trend: 0.65, volatility: 0.65, liquidity: 0.84, momentum: 0.72 },
    OIL   : { trend: 0.60, volatility: 0.70, liquidity: 0.68, momentum: 0.62 },
    SILVER: { trend: 0.65, volatility: 0.68, liquidity: 0.72, momentum: 0.65 },
  };

  // ─── Timeframe Modifiers ─────────────────────────────────────────────
  const TF_MODIFIERS = {
    M5 : { trend: 0.82, volatility: 1.10, liquidity: 0.90, momentum: 0.85 },
    M15: { trend: 0.88, volatility: 1.05, liquidity: 0.92, momentum: 0.90 },
    H1 : { trend: 1.00, volatility: 1.00, liquidity: 1.00, momentum: 1.00 },
    H4 : { trend: 1.06, volatility: 0.95, liquidity: 1.02, momentum: 1.04 },
    D1 : { trend: 1.10, volatility: 0.90, liquidity: 1.05, momentum: 1.08 },
    W1 : { trend: 1.12, volatility: 0.85, liquidity: 1.08, momentum: 1.10 },
  };

  // ─── Opportunity Level Thresholds ────────────────────────────────────
  const OPPORTUNITY_LEVELS = [
    { min: 80, label: 'VERY HIGH', color: '#00ff9d' },
    { min: 65, label: 'HIGH',      color: '#00ff9d' },
    { min: 50, label: 'MODERATE',  color: '#00e5ff' },
    { min: 35, label: 'LOW',       color: '#ffaa00' },
    { min: 0,  label: 'AVOID',     color: '#ff3355' },
  ];

  // ─── In-memory result cache (per asset+TF, 30s TTL) ─────────────────
  const _cache = new Map();
  const CACHE_TTL_MS = 30_000;

  function _cacheKey(asset, tf) {
    return `${asset.toUpperCase()}:${(tf || 'H1').toUpperCase()}`;
  }

  function _fromCache(asset, tf) {
    const key  = _cacheKey(asset, tf);
    const item = _cache.get(key);
    if (!item) return null;
    if (Date.now() - item.ts > CACHE_TTL_MS) { _cache.delete(key); return null; }
    return { ...item.data, _cache_hit: true };
  }

  function _toCache(asset, tf, data) {
    _cache.set(_cacheKey(asset, tf), { ts: Date.now(), data });
  }

  // ─── Helpers ─────────────────────────────────────────────────────────
  function _jitter(val, range = 0.06) {
    return Math.min(1, Math.max(0, val + (Math.random() - 0.5) * range));
  }

  function _clamp(v, lo = 0, hi = 100) {
    return Math.min(hi, Math.max(lo, v));
  }

  function _detectRegime(components, tfMod) {
    const { trend, volatility, liquidity, momentum } = components;
    const trendScore = trend * 100;
    const volScore   = volatility * 100;

    if (trendScore >= 72 && momentum * 100 >= 65) return 'EXPANSION';
    if (trendScore >= 60 && volScore < 60)         return 'TREND';
    if (volScore >= 72)                            return 'VOLATILE';
    if (trendScore >= 40 && volScore < 50)         return 'RANGE_BOUND';
    if (trendScore < 40 && momentum * 100 >= 60)   return 'ACCUMULATION';
    return 'DISTRIBUTION';
  }

  function _opportunityLevel(score) {
    for (const lvl of OPPORTUNITY_LEVELS) {
      if (score >= lvl.min) return lvl;
    }
    return OPPORTUNITY_LEVELS[OPPORTUNITY_LEVELS.length - 1];
  }

  function _sessionLabel() {
    const h = new Date().getUTCHours();
    if (h < 2)  return 'ASIA';
    if (h < 8)  return 'LONDON_OPEN';
    if (h < 12) return 'LONDON';
    if (h < 17) return 'NEW_YORK';
    if (h < 20) return 'NY_LONDON_CLOSE';
    return 'ASIA_OPEN';
  }

  function _confidenceLevel(score, componentVariance) {
    if (score >= 70 && componentVariance < 15) return 'HIGH';
    if (score >= 50 && componentVariance < 25) return 'MEDIUM';
    return 'LOW';
  }

  // ─── Core Score Calculation ───────────────────────────────────────────
  /**
   * compute({ asset, timeframe, marketData? })
   *
   * If marketData is provided (from API), use it directly.
   * Otherwise, fall back to offline seeded calculation.
   *
   * Returns V4 result object:
   * {
   *   asset, score, regime, opportunity, components,
   *   confidence, session, breakdown, strategy_hint,
   *   risk_notes, share_url, scan_id, timestamp, _source
   * }
   */
  function compute({ asset = 'GOLD', timeframe = 'H1', marketData = null } = {}) {
    const assetKey = asset.toUpperCase();
    const tfKey    = (timeframe || 'H1').toUpperCase();

    // 1. Cache check
    const cached = _fromCache(assetKey, tfKey);
    if (cached) return cached;

    // 2. Use API-provided market data if available
    let dims;
    if (marketData && marketData.dimensions) {
      // Market Intelligence Domain provided structured dimensions
      dims = {
        trend      : _clamp(marketData.dimensions.trend      || 0, 0, 100) / 100,
        volatility : _clamp(marketData.dimensions.volatility  || 0, 0, 100) / 100,
        liquidity  : _clamp(marketData.dimensions.liquidity   || 0, 0, 100) / 100,
        momentum   : _clamp(marketData.dimensions.momentum    || 0, 0, 100) / 100,
      };
    } else {
      // Offline fallback: seeded + jitter
      const profile = ASSET_PROFILES[assetKey] || ASSET_PROFILES.GOLD;
      const tfMod   = TF_MODIFIERS[tfKey] || TF_MODIFIERS.H1;
      dims = {
        trend      : _jitter(profile.trend      * tfMod.trend),
        volatility : _jitter(profile.volatility * tfMod.volatility),
        liquidity  : _jitter(profile.liquidity  * tfMod.liquidity),
        momentum   : _jitter(profile.momentum   * tfMod.momentum),
      };
    }

    // 3. Base Score = weighted sum of 4 orthogonal dimensions
    const baseScore = (
      dims.trend      * WEIGHTS.trend      +
      dims.volatility * WEIGHTS.volatility +
      dims.liquidity  * WEIGHTS.liquidity  +
      dims.momentum   * WEIGHTS.momentum
    );

    // 4. Regime detection
    const regime = marketData?.regime || _detectRegime(dims, tfKey);

    // 5. Apply regime multiplier
    const multiplier   = REGIME_MULTIPLIERS[regime] ?? 1.0;
    const finalScore   = _clamp(Math.round(baseScore * multiplier * 100), 0, 100);

    // 6. Opportunity level
    const opportunity  = _opportunityLevel(finalScore);

    // 7. Component variance (for confidence)
    const compValues   = [dims.trend, dims.volatility, dims.liquidity, dims.momentum].map(v => v * 100);
    const mean         = compValues.reduce((a, b) => a + b, 0) / compValues.length;
    const variance     = Math.sqrt(compValues.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / compValues.length);

    const confidence   = _confidenceLevel(finalScore, variance);
    const session      = _sessionLabel();

    // 8. Breakdown (raw component scores × 100)
    const breakdown = {
      'TREND STRUCTURE'      : Math.round(dims.trend      * 100),
      'VOLATILITY EXPANSION' : Math.round(dims.volatility * 100),
      'LIQUIDITY CONDITION'  : Math.round(dims.liquidity  * 100),
      'MOMENTUM ALIGNMENT'   : Math.round(dims.momentum   * 100),
    };

    // 9. Strategy hint
    const strategy_hint = _buildStrategyHint(finalScore, regime, dims);

    // 10. Risk notes
    const risk_notes = _buildRiskNotes(finalScore, regime, dims);

    const result = {
      asset      : assetKey,
      timeframe  : tfKey,
      score      : finalScore,
      regime,
      opportunity: opportunity.label,
      opportunityColor: opportunity.color,
      confidence,
      session,
      components : {
        trend      : Math.round(dims.trend      * 100),
        volatility : Math.round(dims.volatility * 100),
        liquidity  : Math.round(dims.liquidity  * 100),
        momentum   : Math.round(dims.momentum   * 100),
      },
      breakdown,
      // Legacy pillars mapping (for existing renderResult compat)
      _pillars: {
        trend    : Math.round(dims.trend      * 100),
        vol      : Math.round(dims.volatility * 100),
        session  : Math.round(dims.liquidity  * 100),
        structure: Math.round(dims.momentum   * 100),
      },
      strategy_hint,
      risk_notes,
      label        : opportunity.label,
      color        : opportunity.color,
      report_queued: true,
      scan_id      : 'rsv4_' + Date.now(),
      timestamp    : new Date().toISOString(),
      _source      : marketData ? 'api' : 'fallback',
      _regime_multiplier: multiplier,
    };

    // 11. Cache result
    _toCache(assetKey, tfKey, result);

    return result;
  }

  // ─── Strategy Hints ───────────────────────────────────────────────────
  function _buildStrategyHint(score, regime, dims) {
    if (regime === 'EXPANSION' || regime === 'TREND') {
      return `Trend structure mạnh (${Math.round(dims.trend * 100)}) — ưu tiên lệnh theo xu hướng. SL dưới swing low gần nhất.`;
    }
    if (regime === 'RANGE_BOUND') {
      return `Thị trường sideway. Liquidity ${Math.round(dims.liquidity * 100)} — fade moves tại extreme, TP gần support/resistance.`;
    }
    if (regime === 'VOLATILE') {
      return `Volatility cao (${Math.round(dims.volatility * 100)}) — giảm size 50%, mở rộng SL × 1.5, chỉ vào lệnh khi có xác nhận.`;
    }
    if (regime === 'ACCUMULATION') {
      return `Regime tích lũy. Chờ volume breakout xác nhận trước khi vào lệnh theo xu hướng mới.`;
    }
    if (regime === 'DISTRIBUTION') {
      return `Phân phối cuối trend. Tránh lệnh mới theo hướng cũ — theo dõi dấu hiệu đảo chiều.`;
    }
    return `Score ${score} — theo dõi thêm trước khi hành động.`;
  }

  // ─── Risk Notes ───────────────────────────────────────────────────────
  function _buildRiskNotes(score, regime, dims) {
    const notes = [];
    if (dims.volatility > 0.70) notes.push(`Volatility expansion cao (${Math.round(dims.volatility * 100)}) — spread có thể tăng`);
    if (dims.liquidity  < 0.40) notes.push(`Liquidity thấp (${Math.round(dims.liquidity * 100)}) — tránh lệnh lớn`);
    if (dims.trend      < 0.35) notes.push(`Trend structure yếu — không vào lệnh theo xu hướng`);
    if (regime === 'VOLATILE')  notes.push(`Regime VOLATILE — rủi ro cao bất thường, giảm position size`);
    if (score < 35)             notes.push(`Score thấp — không khuyến nghị mở lệnh mới`);
    return notes;
  }

  // ─── Precompute Batch (for server-side use) ───────────────────────────
  /**
   * precomputeAll(assetsData)
   * Server-side: receives market data for all assets, computes and caches scores.
   * Clients then read from cache rather than triggering individual calculations.
   *
   * @param {Array} assetsData — [{ asset, timeframe, dimensions, regime }]
   * @returns {Object} results map keyed by "ASSET:TF"
   */
  function precomputeAll(assetsData = []) {
    const results = {};
    for (const item of assetsData) {
      const result = compute({
        asset      : item.asset,
        timeframe  : item.timeframe,
        marketData : item,
      });
      results[_cacheKey(item.asset, item.timeframe)] = result;
    }
    return results;
  }

  // ─── Hydrate from API response ────────────────────────────────────────
  /**
   * hydrateFromAPI(apiResponse)
   * Maps raw API scan response into V4 result format.
   * This bridges between the server's Market Intelligence Domain output
   * and the Tactical Domain (RadarScanPage) display contract.
   */
  function hydrateFromAPI(apiResponse) {
    if (!apiResponse) return null;
    const d = apiResponse;

    // If API already returns V4 format
    if (d.components && d.opportunity) return { ...d, _source: 'api' };

    // Legacy API format → map to V4
    const score = d.score || 0;
    const opp   = _opportunityLevel(score);
    return {
      ...d,
      opportunity    : d.opportunity || opp.label,
      opportunityColor: d.color || opp.color,
      label          : d.label || opp.label,
      color          : d.color || opp.color,
      components     : d.components || {
        trend      : d.breakdown?.['TREND (ADX)']   || d.breakdown?.['TREND STRUCTURE']     || 0,
        volatility : d.breakdown?.['VOLATILITY']     || d.breakdown?.['VOLATILITY EXPANSION']|| 0,
        liquidity  : d.breakdown?.['SESSION FIT']    || d.breakdown?.['LIQUIDITY CONDITION'] || 0,
        momentum   : d.breakdown?.['MARKET STRUCT']  || d.breakdown?.['MOMENTUM ALIGNMENT']  || 0,
      },
      _pillars: {
        trend    : d.breakdown?.['TREND (ADX)']   || 0,
        vol      : d.breakdown?.['VOLATILITY']     || 0,
        session  : d.breakdown?.['SESSION FIT']    || 0,
        structure: d.breakdown?.['MARKET STRUCT']  || 0,
      },
      _source: 'api',
    };
  }

  // ─── Score color helper (shared utility) ─────────────────────────────
  function scoreColor(score) {
    for (const lvl of OPPORTUNITY_LEVELS) {
      if (score >= lvl.min) return lvl.color;
    }
    return '#ff3355';
  }

  function scoreLabel(score) {
    const opp = _opportunityLevel(score);
    return opp.label;
  }

  // ─── Public API ───────────────────────────────────────────────────────
  return {
    compute,
    precomputeAll,
    hydrateFromAPI,
    scoreColor,
    scoreLabel,
    WEIGHTS,
    REGIME_MULTIPLIERS,
    // Legacy compat: expose run() as alias for compute()
    run: ({ asset, timeframe } = {}) => compute({ asset, timeframe }),
  };

})();

// ─── Module Export (Node.js / bundler compat) ─────────────────────────
if (typeof module !== 'undefined' && module.exports) {
  module.exports = RadarScoreEngine;
}
