// ═══════════════════════════════════════════════════════════════════════════════
// RegimeFitScorer.js  —  ZArmor · Regime Fit Scoring Engine
// Chấm điểm mức độ phù hợp của từng lệnh đang vận hành với regime thị trường.
//
// IMPORT:
//   import { scoreTrade, scoreAllTrades, REGIME_RULES } from './RegimeFitScorer.js';
//
// USAGE trong RightColumn.js:
//   import { scoreAllTrades } from './RegimeFitScorer.js';
//
//   // Trong useMemo hoặc sau mỗi lần radarResult thay đổi:
//   const scoredTrades = useMemo(
//     () => scoreAllTrades(activeTrades, radarResult, riskParams, neural),
//     [activeTrades, radarResult]
//   );
//
// OUTPUT mỗi trade:
//   {
//     ...originalTrade,
//     regime_fit_score:   72,          // 0-100
//     regime_fit_grade:   'B+',        // S/A/B/C/D/F
//     regime_fit_color:   '#00e5ff',   // display color
//     regime_status:      'ALIGNED',   // text badge
//     regime_warnings:    ['...'],     // array of warning strings
//     regime_action:      'HOLD',      // HOLD | REDUCE | CLOSE | MONITOR
//     score_breakdown:    { ... },     // sub-scores for transparency
//   }
// ═══════════════════════════════════════════════════════════════════════════════


// ─── CONSTANTS ───────────────────────────────────────────────────────────────

// Regime → hành vi thị trường
export const REGIME_RULES = {
    // Radar score ≥ 70
    STRONG: {
        favors:     ['BUY', 'LONG'],
        opposes:    [],
        rr_min:     1.5,
        hold_ok:    true,
        add_ok:     true,
        description: 'Strong upside momentum — trending regime',
    },
    GOOD: {
        favors:     ['BUY', 'LONG', 'SELL', 'SHORT'],
        opposes:    [],
        rr_min:     1.5,
        hold_ok:    true,
        add_ok:     false,
        description: 'Tradeable but directional edge weakening',
    },
    // Radar score 30–49
    RISKY: {
        favors:     [],
        opposes:    ['BUY', 'LONG', 'SELL', 'SHORT'],
        rr_min:     2.5,
        hold_ok:    false,
        add_ok:     false,
        description: 'High volatility — reduce exposure',
    },
    // Radar score < 30
    AVOID: {
        favors:     [],
        opposes:    ['BUY', 'LONG', 'SELL', 'SHORT'],
        rr_min:     3.0,
        hold_ok:    false,
        add_ok:     false,
        description: 'Dangerous conditions — no new trades',
    },

    // Regime từ breakdown type (nếu server trả về regime type chứ không phải label)
    TREND: {
        favors:     ['BUY', 'LONG', 'SELL', 'SHORT'],
        opposes:    [],
        rr_min:     1.5,
        hold_ok:    true,
        add_ok:     true,
        description: 'Directional trend — follow momentum',
    },
    RANGE: {
        favors:     ['BUY', 'LONG', 'SELL', 'SHORT'],   // mean reversion
        opposes:    [],
        rr_min:     1.2,
        hold_ok:    true,
        add_ok:     false,
        description: 'Range-bound — tight SL, take profits early',
    },
    VOLATILE: {
        favors:     [],
        opposes:    ['BUY', 'LONG', 'SELL', 'SHORT'],
        rr_min:     2.5,
        hold_ok:    false,
        add_ok:     false,
        description: 'Volatile — reduce size, widen SL or close',
    },
    ACCUMULATION: {
        favors:     ['BUY', 'LONG'],
        opposes:    ['SELL', 'SHORT'],
        rr_min:     1.5,
        hold_ok:    true,
        add_ok:     true,
        description: 'Accumulation phase — longs favored',
    },
    DISTRIBUTION: {
        favors:     ['SELL', 'SHORT'],
        opposes:    ['BUY', 'LONG'],
        rr_min:     1.5,
        hold_ok:    false,
        add_ok:     false,
        description: 'Distribution phase — longs risky, reduce',
    },
};

// Grade thresholds
const GRADE_MAP = [
    { min: 90, grade: 'S',  label: 'PERFECT FIT',   color: '#00ff9d' },
    { min: 75, grade: 'A',  label: 'STRONG FIT',    color: '#00ff9d' },
    { min: 60, grade: 'B',  label: 'ALIGNED',       color: '#00e5ff' },
    { min: 45, grade: 'C',  label: 'BORDERLINE',    color: '#ffaa00' },
    { min: 30, grade: 'D',  label: 'MISALIGNED',    color: '#ff8c00' },
    { min: 0,  grade: 'F',  label: 'CRITICAL',      color: '#ff4444' },
];

function getGrade(score) {
    return GRADE_MAP.find(g => score >= g.min) || GRADE_MAP[GRADE_MAP.length - 1];
}

// ─── CORE SCORING ENGINE ──────────────────────────────────────────────────────

/**
 * Chấm điểm một lệnh dựa trên regime context
 *
 * @param {Object} trade       - lệnh từ activeTrades
 * @param {Object} radarResult - kết quả từ /radar/scan (có thể null)
 * @param {Object} riskParams  - từ unitConfig.risk_params
 * @param {Object} neural      - từ unitConfig.neural_profile
 * @returns {Object}           - trade enriched với regime_fit_score và metadata
 */
export function scoreTrade(trade, radarResult, riskParams = {}, neural = {}) {
    // ── Nếu chưa có radarResult → không thể chấm, trả về placeholder ──
    if (!radarResult || !radarResult.score) {
        return {
            ...trade,
            regime_fit_score:  null,
            regime_fit_grade:  '?',
            regime_fit_color:  '#333',
            regime_status:     'NO SCAN',
            regime_warnings:   ['Chưa có dữ liệu regime — cần scan'],
            regime_action:     'MONITOR',
            score_breakdown:   null,
        };
    }

    const warnings   = [];
    const breakdown  = {};

    // ── Resolve regime rules ──
    const regimeKey  = resolveRegimeKey(radarResult);
    const rules      = REGIME_RULES[regimeKey] || REGIME_RULES['GOOD'];
    const radarScore = radarResult.score || 50;

    // ── Extract trade fields ──
    const side       = (trade.side || trade.type || '').toUpperCase();
    const symbol     = (trade.symbol || '').toUpperCase();
    const tradeRR    = parseFloat(trade.current_rr || trade.rr || 0);
    const pnl        = parseFloat(trade.profit || trade.pnl || trade.unrealized_pnl || 0);
    const openTime   = trade.open_time ? new Date(trade.open_time) : null;
    const ageMinutes = openTime ? (Date.now() - openTime) / 60000 : null;
    const size       = parseFloat(trade.volume || trade.lots || trade.size || 0);

    // Risk params
    const plannedRR  = parseFloat(neural?.historical_rr || riskParams?.rr_target || 2.0);
    const maxSize    = parseFloat(riskParams?.max_lot || riskParams?.lot_cap || 0.5);

    // ══════════════════════════════════════════════════════════════════════
    // SCORING DIMENSIONS (6 dimensions × trọng số)
    // ══════════════════════════════════════════════════════════════════════

    // 1️⃣  DIRECTION ALIGNMENT (30 pts)
    //     Hướng lệnh có phù hợp với regime không?
    let dirScore = 50; // neutral baseline
    const isBullish  = side.includes('BUY')  || side.includes('LONG');
    const isBearish  = side.includes('SELL') || side.includes('SHORT');

    if (rules.favors.length > 0) {
        const favored = rules.favors.some(f =>
            isBullish ? (f === 'BUY' || f === 'LONG') :
            isBearish ? (f === 'SELL' || f === 'SHORT') : false
        );
        const opposed = rules.opposes.some(f =>
            isBullish ? (f === 'BUY' || f === 'LONG') :
            isBearish ? (f === 'SELL' || f === 'SHORT') : false
        );
        if (favored)  dirScore = 95;
        else if (opposed) {
            dirScore = 15;
            warnings.push(`Hướng ${side} ngược với regime ${regimeKey}`);
        } else dirScore = 55;
    } else if (rules.opposes.some(f =>
        isBullish ? (f === 'BUY' || f === 'LONG') :
        isBearish ? (f === 'SELL' || f === 'SHORT') : false
    )) {
        dirScore = 10;
        warnings.push(`Regime ${regimeKey}: tránh mọi lệnh hướng này`);
    }

    breakdown.direction = Math.round(dirScore);

    // 2️⃣  RADAR SCORE COMPATIBILITY (25 pts)
    //     Điểm radar càng cao → lệnh đang hold càng an toàn
    let radarCompat;
    if      (radarScore >= 70) radarCompat = 90;
    else if (radarScore >= 55) radarCompat = 70;
    else if (radarScore >= 40) radarCompat = 45;
    else if (radarScore >= 25) {
        radarCompat = 20;
        warnings.push(`Radar score thấp (${radarScore}) — cân nhắc đóng lệnh`);
    } else {
        radarCompat = 5;
        warnings.push(`Radar score nguy hiểm (${radarScore}) — khuyến nghị đóng`);
    }

    breakdown.radar_compat = radarCompat;

    // 3️⃣  R:R QUALITY (20 pts)
    //     R:R hiện tại so với ngưỡng tối thiểu của regime và kế hoạch
    let rrScore = 50;
    if (tradeRR > 0) {
        const minRR = rules.rr_min;
        if (tradeRR >= plannedRR) {
            rrScore = 95; // vượt kế hoạch
        } else if (tradeRR >= minRR) {
            rrScore = 65 + Math.round((tradeRR - minRR) / (plannedRR - minRR) * 30);
        } else {
            rrScore = Math.max(10, Math.round(tradeRR / minRR * 60));
            if (tradeRR < minRR * 0.7) {
                warnings.push(`R:R ${tradeRR.toFixed(1)} thấp hơn ngưỡng regime ${minRR} — kiểm tra SL`);
            }
        }
    } else {
        rrScore = 40; // không có data R:R
    }

    breakdown.rr_quality = Math.round(rrScore);

    // 4️⃣  MOMENTUM ALIGNMENT (15 pts)
    //     PnL + tuổi lệnh so với session context
    let momentumScore = 50;
    if (pnl > 0) {
        momentumScore = 75; // lệnh đang lời — regime đang support
    } else if (pnl < 0) {
        // Lệnh đang lỗ + regime xấu = double risk
        const lossPct = Math.abs(pnl) / (parseFloat(riskParams?.daily_limit_money) || 150) * 100;
        if (radarScore < 40) {
            momentumScore = 15;
            warnings.push(`Lỗ ${Math.abs(pnl).toFixed(2)}$ trong regime yếu — rủi ro tích lũy`);
        } else {
            momentumScore = Math.max(20, 55 - lossPct * 2);
        }
    }

    // Age penalty: lệnh quá lâu trong regime RISKY/VOLATILE
    if (ageMinutes !== null && ageMinutes > 120 && (regimeKey === 'RISKY' || regimeKey === 'VOLATILE' || regimeKey === 'DISTRIBUTION')) {
        momentumScore = Math.max(10, momentumScore - 20);
        warnings.push(`Lệnh đã ${Math.round(ageMinutes)}m trong regime bất lợi`);
    }

    breakdown.momentum = Math.round(momentumScore);

    // 5️⃣  POSITION SIZE vs REGIME (5 pts)
    //     Size lớn trong regime xấu = rủi ro cao hơn
    let sizeScore = 70;
    if (size > 0 && maxSize > 0) {
        const sizePct = size / maxSize;
        if (sizePct > 0.8 && radarScore < 50) {
            sizeScore = 25;
            warnings.push(`Size lớn (${(sizePct*100).toFixed(0)}% cap) trong regime yếu`);
        } else if (sizePct > 0.5 && radarScore < 35) {
            sizeScore = 40;
            warnings.push(`Cân nhắc giảm size trong điều kiện hiện tại`);
        } else {
            sizeScore = 80;
        }
    }

    breakdown.size_risk = Math.round(sizeScore);

    // 6️⃣  REGIME STABILITY BONUS/PENALTY (5 pts)
    //     Nếu radarResult có stability data → thưởng/phạt thêm
    let stabilityScore = 60;
    if (radarResult.breakdown) {
        const bd = radarResult.breakdown;
        // Tìm stability key (flexible naming)
        const stabKey = Object.keys(bd).find(k => k.toLowerCase().includes('stab'));
        const stabVal = stabKey ? parseInt(bd[stabKey]) : null;
        if (stabVal !== null) {
            stabilityScore = stabVal;
            if (stabVal < 30) warnings.push(`Regime instability cao (${stabVal}) — biến động bất ngờ có thể xảy ra`);
        }
    }

    breakdown.stability = Math.round(stabilityScore);

    // ══════════════════════════════════════════════════════════════════════
    // WEIGHTED TOTAL
    // ══════════════════════════════════════════════════════════════════════
    const WEIGHTS = {
        direction:   0.30,
        radar_compat:0.25,
        rr_quality:  0.20,
        momentum:    0.15,
        size_risk:   0.05,
        stability:   0.05,
    };

    const rawScore = Object.entries(WEIGHTS).reduce((sum, [k, w]) => {
        return sum + (breakdown[k] || 50) * w;
    }, 0);

    const finalScore = Math.round(Math.min(100, Math.max(0, rawScore)));

    // ── Grade & Action ──
    const grade = getGrade(finalScore);

    let action;
    if      (finalScore >= 75) action = 'HOLD';
    else if (finalScore >= 55) action = 'MONITOR';
    else if (finalScore >= 35) action = 'REDUCE';
    else                       action = 'CLOSE';

    if (!rules.hold_ok && finalScore < 60) {
        action = action === 'HOLD' ? 'MONITOR' : action;
    }

    return {
        ...trade,
        regime_fit_score:  finalScore,
        regime_fit_grade:  grade.grade,
        regime_fit_color:  grade.color,
        regime_status:     grade.label,
        regime_warnings:   warnings,
        regime_action:     action,
        regime_key:        regimeKey,
        score_breakdown:   breakdown,
    };
}

/**
 * Chấm điểm tất cả activeTrades
 */
export function scoreAllTrades(activeTrades, radarResult, riskParams = {}, neural = {}) {
    if (!activeTrades || activeTrades.length === 0) return [];
    return activeTrades.map(t => scoreTrade(t, radarResult, riskParams, neural));
}

/**
 * Tóm tắt portfolio-level regime fit
 * Trả về: overall score, critical count, recommendation
 */
export function portfolioRegimeSummary(scoredTrades) {
    if (!scoredTrades || scoredTrades.length === 0) {
        return { overall: null, critical: 0, recommendation: 'NO_TRADES' };
    }

    const withScores = scoredTrades.filter(t => t.regime_fit_score !== null);
    if (withScores.length === 0) {
        return { overall: null, critical: 0, recommendation: 'NO_SCAN' };
    }

    const avg      = withScores.reduce((s, t) => s + t.regime_fit_score, 0) / withScores.length;
    const critical = withScores.filter(t => t.regime_fit_score < 35).length;
    const toClose  = withScores.filter(t => t.regime_action === 'CLOSE').length;
    const toReduce = withScores.filter(t => t.regime_action === 'REDUCE').length;

    let recommendation;
    if (critical >= withScores.length * 0.5) recommendation = 'SCRAM_CONSIDER';
    else if (toClose > 0)   recommendation = 'CLOSE_SOME';
    else if (toReduce > 0)  recommendation = 'REDUCE_SIZE';
    else if (avg >= 70)     recommendation = 'ALL_CLEAR';
    else                    recommendation = 'MONITOR';

    return {
        overall:        Math.round(avg),
        critical,
        toClose,
        toReduce,
        recommendation,
        grade:          getGrade(Math.round(avg)),
    };
}

// ─── INTERNAL HELPERS ─────────────────────────────────────────────────────────

/**
 * Resolve regime key từ radarResult
 * Server có thể trả về regime là label "STRONG"/"GOOD"/"RISKY"/"AVOID"
 * hoặc type "TREND"/"RANGE"/"VOLATILE"/"ACCUMULATION"/"DISTRIBUTION"
 */
function resolveRegimeKey(radarResult) {
    const regime = (radarResult.regime || '').toUpperCase().replace(/\s+/g,'_');
    if (REGIME_RULES[regime]) return regime;

    // Fallback từ score
    const score = radarResult.score || 0;
    if (score >= 70) return 'STRONG';
    if (score >= 50) return 'GOOD';
    if (score >= 30) return 'RISKY';
    return 'AVOID';
}
