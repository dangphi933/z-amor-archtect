import { h } from 'preact';
import RegimeFitModal from './RegimeFitModal.js';
import { scoreAllTrades, portfolioRegimeSummary } from './RegimeFitScorer.js';
import { useState, useRef, useEffect, useMemo } from 'preact/hooks';
import htm from 'htm';

const html = htm.bind(h);
const _rcGetToken = () => localStorage.getItem('za_access_token') || ''; // F-10

// ─── LOG TYPE CONFIG ─────────────────────────────────────────
const LOG_CONFIG = {
    'SESSION_OPEN':    { icon: '🟢', label: 'SESSION', dark: '#002211' },
    'SESSION_CLOSE':   { icon: '📊', label: 'DEBRIEF', dark: '#001122' },
    'TRADE_WIN':       { icon: '✅', label: 'WIN',     dark: '#002211' },
    'TRADE_LOSS':      { icon: '❌', label: 'LOSS',    dark: '#220000' },
    'COMPLIANCE_VIOL': { icon: '⚠️', label: 'VIOLATE', dark: '#221100' },
    'DD_WARNING':      { icon: '☢️', label: 'WARN',    dark: '#221100' },
    'TARGET_REACHED':  { icon: '🎯', label: 'TARGET',  dark: '#002211' },
    'OVERRIDE_UP':     { icon: '🔧', label: 'OVERRIDE', dark: '#111' },
    'INFO':            { icon: '›',  label: 'INFO',    dark: 'transparent' },
    'WARN':            { icon: '⚠',  label: 'WARN',    dark: '#221100' },
    'CRIT':            { icon: '🔴', label: 'CRIT',    dark: '#220000' },
};

// ─── HELPERS ─────────────────────────────────────────────────
function getSessionHistory(accountId) {
    try { return JSON.parse(localStorage.getItem(`zarmor_sessions_${accountId}`) || '[]'); } catch { return []; }
}
function getTodaySession(accountId) {
    try { return JSON.parse(localStorage.getItem(`zarmor_current_session_${accountId}`) || 'null'); } catch { return null; }
}
function loadAuditLogs(accountId) {
    try {
        const raw = localStorage.getItem(`zarmor_audit_${accountId}`);
        if (!raw) return [];
        // [FIX] spread trước reverse để không mutate array gốc
        return [...JSON.parse(raw)].reverse().map(log => ({
            time: log.date ? (log.date.includes(', ') ? log.date.split(', ')[1] : log.date) : '—',
            type: log.action || 'INFO',
            text: log.message || `[${log.action}] Budget → $${log.final || 0}`
        }));
    } catch { return []; }
}
function getRolloverCountdown(rolloverHour) {
    const now = new Date();
    const next = new Date();
    next.setHours(rolloverHour, 0, 0, 0);
    if (now >= next) next.setDate(next.getDate() + 1);
    const ms = next - now;
    const h = Math.floor(ms / 3600000);
    const m = Math.floor((ms % 3600000) / 60000);
    const s = Math.floor((ms % 60000) / 1000);
    return { h, m, s, ms, pct: Math.min(100, ((86400000 - ms) / 86400000) * 100) };
}

// ═══════════════════════════════════════════════════════════════
// COMPONENT CHÍNH
// ═══════════════════════════════════════════════════════════════

// ══════════════════════════════════════════════════════════════════════════════
// AI EA ADVISORY ENGINE
// Input : radarResult, riskParams (từ unitConfig), neural (trader profile),
//         portfolioSummary (từ RegimeFitScorer)
// Output: { ready, riskLevel, sessionMode, lotAdj, rrMin, budgetAdj, lines[] }
// ══════════════════════════════════════════════════════════════════════════════
function computeEAAdvisory(radarResult, riskParams, neural, portfolioSummary) {
    if (!radarResult || !radarResult.score) {
        return { ready: false };
    }

    const score     = radarResult.score || 50;
    const regime    = (radarResult.regime || '').toUpperCase().replace(/\s+/g, '_');
    const ps        = portfolioSummary || {};

    // ── Đọc base params từ cấu hình EA ──
    const baseLot    = parseFloat(riskParams?.max_lot    || riskParams?.lot_cap      || 0.10);
    const baseRR     = parseFloat(riskParams?.rr_target  || neural?.historical_rr    || 2.0);
    const baseBudget = parseFloat(riskParams?.daily_limit_money || riskParams?.tactical_daily_money || 150);
    const archetype  = (neural?.trader_archetype || 'SNIPER').toUpperCase();

    // ─── 1. LOT MULTIPLIER — dựa trên regime score ────────────
    let lotMult = score >= 75 ? 1.0
                : score >= 60 ? 0.75
                : score >= 45 ? 0.50
                : score >= 30 ? 0.25
                :               0.0;

    // Archetype correction
    if (archetype === 'SNIPER')  lotMult = Math.min(lotMult, 0.75); // Quality > quantity
    if (archetype === 'SCALPER') lotMult = Math.min(lotMult * 0.8, 0.60);
    if (archetype === 'SWINGER') lotMult = Math.min(lotMult, 0.50); // Fewer, bigger
    if (archetype === 'GAMBLER') lotMult = 0.0;                     // Hard block

    // Portfolio penalty: mỗi lệnh CRITICAL → giảm 10%
    if (ps.critical > 0) lotMult = Math.max(0, lotMult - ps.critical * 0.10);

    const lotAdj = +(baseLot * lotMult).toFixed(2);

    // ─── 2. R:R MINIMUM — regime xấu → tăng ngưỡng ────────────
    const rrMin = score >= 70 ? baseRR
                : score >= 55 ? Math.max(baseRR, 2.0)
                : score >= 35 ? Math.max(baseRR, 2.5)
                :               Math.max(baseRR, 3.0);

    // ─── 3. DAILY BUDGET — chỉ dùng % tương ứng score ────────
    const budgetPct = score >= 70 ? 1.00
                    : score >= 55 ? 0.70
                    : score >= 40 ? 0.40
                    : score >= 25 ? 0.20
                    :               0.00;
    const budgetAdj = +(baseBudget * budgetPct).toFixed(0);

    // ─── 4. SESSION MODE ───────────────────────────────────────
    const SESSION_MODES = {
        OPTIMAL:   { icon: '↑↑', label: 'TREND FOLLOW',    desc: 'Theo đà, có thể pyramid. Hold lâu nếu momentum tiếp diễn.' },
        SELECTIVE: { icon: '↑',  label: 'SWING SELECT',    desc: 'Chọn lọc setup A+. Ưu tiên pullback sạch về vùng cầu/cung.' },
        DEFENSIVE: { icon: '→',  label: 'DEFENSIVE',       desc: 'Tối đa 1-2 lệnh. SL chặt hơn 20%. Chốt lời nhanh ≤70% TP.' },
        REDUCE:    { icon: '↓',  label: 'REDUCE & WATCH',  desc: 'Không mở mới. Giữ lệnh đang lời, cân nhắc đóng lệnh lỗ.' },
        HALT:      { icon: '✗',  label: 'TRADING HALT',    desc: 'Nghỉ phiên hôm nay. Bảo toàn vốn tuyệt đối — thị trường không phù hợp.' },
    };
    const modeKey = score >= 70 ? 'OPTIMAL'
                  : score >= 55 ? 'SELECTIVE'
                  : score >= 40 ? 'DEFENSIVE'
                  : score >= 25 ? 'REDUCE'
                  :               'HALT';
    const sessionMode = SESSION_MODES[modeKey];

    // ─── 5. RISK LEVEL TAG ─────────────────────────────────────
    const riskLevel = score >= 70 ? { tag: 'OPTIMAL',  color: '#00ff9d' }
                    : score >= 55 ? { tag: 'NORMAL',   color: '#00e5ff' }
                    : score >= 40 ? { tag: 'ELEVATED', color: '#ffaa00' }
                    : score >= 25 ? { tag: 'HIGH',     color: '#ff7700' }
                    :               { tag: 'EXTREME',  color: '#ff4444' };

    // ─── 6. ADVICE LINES — actionable, ordered by priority ────
    const lines = [];

    // LOT
    if (lotMult === 0)
        lines.push({ lvl: 'crit', icon: '🚫', text: 'KHÔNG VÀO LỆNH — regime quá nguy hiểm cho tài khoản' });
    else if (lotMult <= 0.25)
        lines.push({ lvl: 'warn', icon: '⚠',  text: `Lot tối đa ${lotAdj} (giảm còn ${Math.round(lotMult*100)}% kế hoạch)` });
    else if (lotMult < 1.0)
        lines.push({ lvl: 'info', icon: '📉', text: `Giảm lot: dùng ${lotAdj} thay vì ${baseLot} — regime chưa đủ mạnh` });
    else
        lines.push({ lvl: 'ok',   icon: '✅', text: `Lot bình thường: ${lotAdj} — regime hỗ trợ đầy đủ` });

    // R:R
    if (rrMin > baseRR)
        lines.push({ lvl: 'warn', icon: '📐', text: `Tăng R:R tối thiểu lên 1:${rrMin.toFixed(1)} (kế hoạch: 1:${baseRR.toFixed(1)}) — lọc setup kém` });
    else
        lines.push({ lvl: 'ok',   icon: '📐', text: `R:R kế hoạch 1:${baseRR.toFixed(1)} phù hợp với regime hiện tại` });

    // BUDGET
    if (budgetAdj < baseBudget)
        lines.push({ lvl: 'warn', icon: '💰', text: `Giới hạn ngân sách hôm nay: $${budgetAdj} / $${baseBudget} (${Math.round(budgetPct*100)}%)` });

    // REGIME-SPECIFIC
    const isVolatile = regime.includes('VOLATILE') || regime.includes('RISKY');
    const isTrend    = regime.includes('TREND')    || regime.includes('STRONG') || regime.includes('ACCUMULATION');
    const isRange    = regime.includes('RANGE');
    const isDist     = regime.includes('DISTRIBUTION');

    if (score < 35 || isVolatile)
        lines.push({ lvl: 'crit', icon: '🔴', text: 'Ưu tiên đóng lệnh đang lỗ trước — không để float quá 50% budget' });
    else if (isTrend)
        lines.push({ lvl: 'ok',   icon: '🟢', text: 'Trend mạnh: có thể hold lâu hơn kế hoạch nếu momentum duy trì' });
    else if (isRange)
        lines.push({ lvl: 'info', icon: '🔵', text: 'Range market: chốt lời sớm tại 60-70% TP — tránh reversal' });
    else if (isDist)
        lines.push({ lvl: 'warn', icon: '⚠',  text: 'Distribution: lệnh Long rủi ro cao — ưu tiên Short hoặc không giao dịch' });

    // ARCHETYPE-SPECIFIC
    if (archetype === 'SNIPER' && score >= 65)
        lines.push({ lvl: 'info', icon: '🎯', text: 'Sniper: chờ entry 4H/1H aligned — chất lượng > số lượng' });
    if (archetype === 'SCALPER' && score < 60)
        lines.push({ lvl: 'warn', icon: '⚡', text: 'Scalper: regime yếu — tăng spread filter, dùng limit orders' });

    // PORTFOLIO ALERT
    if (ps.recommendation === 'SCRAM_CONSIDER')
        lines.push({ lvl: 'crit', icon: '☢',  text: `Portfolio cảnh báo: đa số lệnh ngược regime — xem xét SCRAM` });
    else if (ps.recommendation === 'CLOSE_SOME')
        lines.push({ lvl: 'crit', icon: '🔴', text: `Đóng ${ps.toClose || '?'} lệnh misaligned trước khi mở lệnh mới` });
    else if (ps.recommendation === 'REDUCE_SIZE')
        lines.push({ lvl: 'warn', icon: '⚠',  text: `Giảm size ${ps.toReduce || '?'} lệnh đang BORDERLINE` });

    return {
        ready: true,
        archetype,
        riskLevel,
        sessionMode,
        lotAdj,
        lotMult,
        rrMin,
        rrBase: baseRR,
        budgetAdj,
        budgetPct,
        budgetBase: baseBudget,
        lines: lines.slice(0, 5), // max 5 dòng
    };
}

// ─── EAAdvisoryBlock — standalone HTM component ──────────────────────────────
// Render tư vấn thông số EA từ computeEAAdvisory()
// mode: 'compact' (3-chip inline) | 'full' (4-chip + params + advice lines)
function EAAdvisoryBlock({ adv, mode, COLORS = { green:'#00ff9d', cyan:'#00e5ff', yellow:'#ffaa00', red:'#ff3355', muted:'#445566', purple:'#b565ff', orange:'#ff8800' } }) {
    const html = htm.bind(h);
const _rcGetToken = () => localStorage.getItem('za_access_token') || ''; // F-10
    if (!adv || !adv.ready) {
        if (mode === 'compact') return null;
        return html`
            <div style="padding:8px 12px;background:#030508;border-top:1px solid #0d0f14;">
                <div style="font-family:monospace;font-size:7px;color:#2a1a3a;
                             letter-spacing:1px;text-align:center;padding:4px 0;">
                    🤖 AI ADVISOR — Scan regime để nhận tư vấn thông số EA
                </div>
            </div>
        `;
    }

    const rl  = adv.riskLevel;
    const sm  = adv.sessionMode;
    const lvlColor = { ok: COLORS.green, info: COLORS.cyan, warn: '#ffaa00', crit: COLORS.red };

    // ── LOT color ──
    const lotColor = adv.lotMult === 0 ? COLORS.red
                   : adv.lotMult <= 0.50 ? '#ffaa00'
                   : adv.lotMult <= 0.75 ? COLORS.cyan : COLORS.green;

    // ── R:R color ──
    const rrColor  = adv.rrMin > adv.rrBase ? '#ffaa00' : COLORS.green;

    // ── Budget color ──
    const bdgColor = adv.budgetPct < 0.5 ? '#ffaa00' : COLORS.cyan;

    // ════════════════════════
    // COMPACT MODE (3 chips)
    // ════════════════════════
    if (mode === 'compact') return html`
        <div style="display:flex;flex-direction:column;gap:5px;padding-top:5px;border-top:1px solid #0d0f14;">
            <!-- Row: label + risk tag -->
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <span style="font-family:monospace;font-size:6px;color:#2a2a2a;letter-spacing:1px;">
                    🤖 AI ADVISOR (${adv.archetype})
                </span>
                <span style="font-family:monospace;font-size:6px;font-weight:900;
                              padding:1px 5px;border-radius:2px;letter-spacing:1px;
                              background:${rl.color}15;border:1px solid ${rl.color}33;color:${rl.color};">
                    ${rl.tag}
                </span>
            </div>
            <!-- 3-chip param row -->
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:3px;">
                <div style="background:#030508;border:1px solid #0d0f14;border-radius:2px;padding:4px 6px;text-align:center;">
                    <div style="font-family:monospace;font-size:5px;color:#334;letter-spacing:1px;margin-bottom:2px;">LOT</div>
                    <div style="font-family:monospace;font-size:12px;font-weight:900;line-height:1;color:${lotColor};">
                        ${adv.lotAdj > 0 ? adv.lotAdj : '—'}
                    </div>
                    <div style="font-family:monospace;font-size:5px;color:#334;margin-top:1px;">
                        ${Math.round(adv.lotMult*100)}% plan
                    </div>
                </div>
                <div style="background:#030508;border:1px solid #0d0f14;border-radius:2px;padding:4px 6px;text-align:center;">
                    <div style="font-family:monospace;font-size:5px;color:#334;letter-spacing:1px;margin-bottom:2px;">R:R MIN</div>
                    <div style="font-family:monospace;font-size:12px;font-weight:900;line-height:1;color:${rrColor};">
                        1:${adv.rrMin.toFixed(1)}
                    </div>
                    <div style="font-family:monospace;font-size:5px;color:#334;margin-top:1px;">
                        ${adv.rrMin > adv.rrBase ? '↑ tăng' : 'kế hoạch'}
                    </div>
                </div>
                <div style="background:#030508;border:1px solid #0d0f14;border-radius:2px;padding:4px 6px;text-align:center;">
                    <div style="font-family:monospace;font-size:5px;color:#334;letter-spacing:1px;margin-bottom:2px;">SESSION</div>
                    <div style="font-family:monospace;font-size:9px;font-weight:900;line-height:1.2;color:${rl.color};">
                        ${sm.icon} ${sm.label.split(' ')[0]}
                    </div>
                    <div style="font-family:monospace;font-size:5px;color:#334;margin-top:1px;">
                        $${adv.budgetAdj} budget
                    </div>
                </div>
            </div>
        </div>
    `;

    // ════════════════════════
    // FULL MODE (header + 4-chip grid + desc + advice lines)
    // ════════════════════════
    return html`
    <div style="border-top:1px solid #111;background:#020408;">

        <!-- Header: label + risk tag -->
        <div style="padding:6px 12px;background:#030508;border-bottom:1px solid #0d0f14;
                     display:flex;justify-content:space-between;align-items:center;">
            <div style="display:flex;align-items:center;gap:6px;">
                <span style="font-family:monospace;font-size:8px;font-weight:900;
                              letter-spacing:1.5px;color:#b565ff;">🤖 AI ADVISOR</span>
                <span style="font-family:monospace;font-size:6px;color:#334;">
                    ${adv.archetype}
                </span>
            </div>
            <span style="font-family:monospace;font-size:7px;font-weight:900;letter-spacing:1px;
                          padding:2px 7px;border-radius:2px;
                          background:${rl.color}15;border:1px solid ${rl.color}44;color:${rl.color};">
                ${rl.tag}
            </span>
        </div>

        <!-- 4-chip EA param grid -->
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:1px;
                     background:#0d0f14;">
            <!-- LOT -->
            <div style="background:#020305;padding:7px 8px;text-align:center;">
                <div style="font-family:monospace;font-size:6px;color:#334;letter-spacing:1px;margin-bottom:3px;">LOT SIZE</div>
                <div style="font-family:monospace;font-size:16px;font-weight:900;line-height:1;color:${lotColor};">
                    ${adv.lotAdj > 0 ? adv.lotAdj : '—'}
                </div>
                <div style="font-family:monospace;font-size:6px;color:#334;margin-top:2px;">
                    ${Math.round(adv.lotMult*100)}% kế hoạch
                </div>
            </div>
            <!-- R:R MIN -->
            <div style="background:#020305;padding:7px 8px;text-align:center;">
                <div style="font-family:monospace;font-size:6px;color:#334;letter-spacing:1px;margin-bottom:3px;">R:R MIN</div>
                <div style="font-family:monospace;font-size:16px;font-weight:900;line-height:1;color:${rrColor};">
                    1:${adv.rrMin.toFixed(1)}
                </div>
                <div style="font-family:monospace;font-size:6px;color:#334;margin-top:2px;">
                    ${adv.rrMin > adv.rrBase ? `↑ từ 1:${adv.rrBase.toFixed(1)}` : 'giữ kế hoạch'}
                </div>
            </div>
            <!-- BUDGET -->
            <div style="background:#020305;padding:7px 8px;text-align:center;">
                <div style="font-family:monospace;font-size:6px;color:#334;letter-spacing:1px;margin-bottom:3px;">BUDGET</div>
                <div style="font-family:monospace;font-size:16px;font-weight:900;line-height:1;color:${bdgColor};">
                    $${adv.budgetAdj}
                </div>
                <div style="font-family:monospace;font-size:6px;color:#334;margin-top:2px;">
                    ${Math.round(adv.budgetPct*100)}% ngân sách
                </div>
            </div>
            <!-- SESSION -->
            <div style="background:#020305;padding:7px 8px;text-align:center;">
                <div style="font-family:monospace;font-size:6px;color:#334;letter-spacing:1px;margin-bottom:3px;">MODE</div>
                <div style="font-family:monospace;font-size:13px;font-weight:900;line-height:1;color:${rl.color};">
                    ${sm.icon}
                </div>
                <div style="font-family:monospace;font-size:5px;color:#445;margin-top:3px;letter-spacing:.3px;">
                    ${sm.label}
                </div>
            </div>
        </div>

        <!-- Session mode description -->
        <div style="padding:6px 12px;background:#020305;border-bottom:1px solid #0d0f14;">
            <div style="font-family:monospace;font-size:8px;color:#556;line-height:1.6;font-style:italic;">
                ${sm.desc}
            </div>
        </div>

        <!-- Advice lines -->
        <div style="display:flex;flex-direction:column;">
            ${adv.lines.map(a => html`
                <div style="display:flex;align-items:flex-start;gap:8px;
                              padding:5px 12px;border-bottom:1px solid #0a0c10;
                              background:${a.lvl === 'crit' ? '#ff44440a' : a.lvl === 'warn' ? '#ffaa000a' : 'transparent'};">
                    <span style="font-size:9px;flex-shrink:0;margin-top:1px;">${a.icon}</span>
                    <span style="font-family:monospace;font-size:8px;line-height:1.5;
                                  color:${lvlColor[a.lvl] || '#556'};">${a.text}</span>
                </div>
            `)}
        </div>
    </div>
    `;
}

// ─── RegimeFitScorePanel — standalone HTM component ──────────────────────────
// Tách ra ngoài để tránh nested html`` template literals (HTM không hỗ trợ)
function RegimeFitScorePanel({ scoredTrades, portfolioSummary, radarResult, COLORS = { green:'#00ff9d', cyan:'#00e5ff', yellow:'#ffaa00', red:'#ff3355', muted:'#445566', purple:'#b565ff', orange:'#ff8800' }, onOpenScan, advisory }) {
    const html = htm.bind(h);
const _rcGetToken = () => localStorage.getItem('za_access_token') || ''; // F-10
    const ps = portfolioSummary;
    if (!scoredTrades || scoredTrades.length === 0) return null;

    const psColor = !ps.overall ? '#333'
        : ps.overall >= 75 ? COLORS.green
        : ps.overall >= 55 ? COLORS.cyan
        : ps.overall >= 35 ? COLORS.yellow : COLORS.red;

    const REC_MAP = {
        ALL_CLEAR:      { icon: '✅', text: 'Portfolio aligned với regime' },
        MONITOR:        { icon: '👁',  text: 'Theo dõi chặt — có lệnh borderline' },
        REDUCE_SIZE:    { icon: '⚠',  text: 'Giảm size một số lệnh' },
        CLOSE_SOME:     { icon: '🔴', text: 'Cân nhắc đóng lệnh misaligned' },
        SCRAM_CONSIDER: { icon: '☢',  text: 'CẢNH BÁO — đa số lệnh ngược regime' },
        NO_SCAN:        { icon: '?',  text: 'Cần scan regime để chấm điểm' },
        NO_TRADES:      { icon: '—',  text: 'Không có lệnh' },
    };
    const rec = REC_MAP[ps.recommendation] || REC_MAP['MONITOR'];

    return html`
    <div style="background:#080a0f;border:1px solid #1a1a1a;
                border-left:3px solid ${psColor};
                border-radius:3px;flex-shrink:0;overflow:hidden;">

        <!-- Header -->
        <div style="padding:8px 12px;background:#030508;border-bottom:1px solid #111;
                     display:flex;justify-content:space-between;align-items:center;">
            <div style="display:flex;align-items:center;gap:6px;">
                <span style="font-family:monospace;font-size:9px;font-weight:900;
                              letter-spacing:1px;color:#b565ff;">🎯 REGIME FIT SCORE</span>
                ${!radarResult ? html`
                    <span style="font-family:monospace;font-size:7px;color:#334;
                                  background:#1a0a1a;padding:2px 5px;border-radius:2px;">
                        SẼ CHẤM SAU KHI SCAN
                    </span>
                ` : null}
            </div>
            <div style="display:flex;align-items:center;gap:8px;">
                ${ps.critical > 0 ? html`
                    <span style="font-family:monospace;font-size:7px;color:${COLORS.red};
                                  font-weight:900;animation:blink 1s step-end infinite;">
                        ⚠ ${ps.critical} CRITICAL
                    </span>
                ` : null}
                <span style="font-family:monospace;font-size:7px;color:#334;">
                    ${scoredTrades.length} lệnh
                </span>
            </div>
        </div>

        <!-- Portfolio summary -->
        ${ps.overall !== null ? html`
            <div style="padding:8px 12px;border-bottom:1px solid #0d0f14;
                         display:flex;align-items:center;gap:10px;">
                <div style="flex-shrink:0;text-align:center;">
                    <div style="font-family:monospace;font-size:20px;font-weight:900;
                                 line-height:1;color:${psColor};">${ps.overall}</div>
                    <div style="font-family:monospace;font-size:6px;color:#334;
                                 letter-spacing:1px;">PORTFOLIO</div>
                </div>
                <div style="flex:1;">
                    <div style="height:3px;background:#111;border-radius:2px;
                                 overflow:hidden;margin-bottom:5px;">
                        <div style="width:${ps.overall}%;height:100%;background:${psColor};
                                     border-radius:2px;transition:width .8s ease;"></div>
                    </div>
                    <div style="font-family:monospace;font-size:8px;
                                 color:${psColor}cc;line-height:1.4;">
                        ${rec.icon} ${rec.text}
                    </div>
                </div>
                <div style="flex-shrink:0;text-align:center;
                             background:${psColor}15;border:1px solid ${psColor}33;
                             border-radius:3px;padding:4px 8px;">
                    <div style="font-family:monospace;font-size:14px;font-weight:900;
                                 color:${psColor};line-height:1;">${ps.grade && ps.grade.grade || '?'}</div>
                    <div style="font-family:monospace;font-size:6px;color:#334;
                                 letter-spacing:.5px;">${ps.grade && ps.grade.label || ''}</div>
                </div>
            </div>
        ` : null}

        <!-- Individual trades -->
        <div style="max-height:200px;overflow-y:auto;
                     scrollbar-width:thin;scrollbar-color:#b565ff22 #111;">
            ${scoredTrades.map((t, idx) => {
                const sc  = t.regime_fit_score;
                const col = t.regime_fit_color || '#334';
                const hasWarn = t.regime_warnings && t.regime_warnings.length > 0;
                const sideColor = (t.side || '').includes('BUY') ? COLORS.green : COLORS.red;
                const bdEntries = t.score_breakdown ? Object.entries(t.score_breakdown) : [];

                return html`
                <div style="padding:7px 12px;border-bottom:1px solid #0d0f14;
                             border-left:3px solid ${col}44;
                             background:${idx % 2 === 0 ? '#030508' : '#020305'};">

                    <!-- Trade header row -->
                    <div style="display:flex;justify-content:space-between;
                                 align-items:center;margin-bottom:4px;">
                        <div style="display:flex;align-items:center;gap:5px;">
                            <span style="font-family:monospace;font-size:9px;
                                          font-weight:900;color:${COLORS.cyan};">
                                [${t.ticket || t.id || '—'}] ${t.symbol || ''}
                            </span>
                            <span style="font-family:monospace;font-size:8px;
                                          font-weight:900;color:${sideColor};">
                                ${t.side || t.type || ''}
                            </span>
                        </div>
                        <div style="display:flex;align-items:center;gap:5px;">
                            ${sc !== null ? html`
                                <span style="font-family:monospace;font-size:7px;
                                              padding:1px 5px;border-radius:2px;
                                              font-weight:900;background:${col}18;
                                              color:${col};border:1px solid ${col}33;">
                                    ${t.regime_action || ''}
                                </span>
                                <span style="font-family:monospace;font-size:10px;
                                              font-weight:900;color:${col};">
                                    ${sc}<span style="font-size:7px;color:#334;">/100</span>
                                </span>
                            ` : html`
                                <span style="font-family:monospace;font-size:8px;color:#2a2a2a;">
                                    — NO SCAN —
                                </span>
                            `}
                        </div>
                    </div>

                    <!-- Score bar -->
                    ${sc !== null ? html`
                        <div style="height:2px;background:#111;border-radius:1px;
                                     overflow:hidden;margin-bottom:4px;">
                            <div style="width:${Math.min(100,sc)}%;height:100%;
                                         background:${col};border-radius:1px;
                                         transition:width .6s ease;"></div>
                        </div>
                        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:${bdEntries.length ? '4px' : '0'};">
                            <div style="display:flex;gap:6px;">
                                <span style="font-family:monospace;font-size:7px;color:${col};font-weight:900;">
                                    ${t.regime_fit_grade}
                                </span>
                                <span style="font-family:monospace;font-size:7px;color:#445;">
                                    ${t.regime_status || ''}
                                </span>
                                <span style="font-family:monospace;font-size:7px;color:#2a2a2a;">
                                    vs ${t.regime_key || ''}
                                </span>
                            </div>
                            ${hasWarn ? html`
                                <span style="font-family:monospace;font-size:7px;color:${COLORS.yellow};
                                              max-width:110px;overflow:hidden;text-overflow:ellipsis;
                                              white-space:nowrap;">
                                    ⚠ ${t.regime_warnings[0]}
                                </span>
                            ` : null}
                        </div>
                        ${bdEntries.length > 0 ? html`
                            <div style="display:grid;grid-template-columns:repeat(6,1fr);gap:3px;padding-top:4px;border-top:1px solid #0d0f14;">
                                ${bdEntries.map(([k, v]) => html`
                                    <div style="text-align:center;">
                                        <div style="font-family:monospace;font-size:5px;color:#2a2a2a;
                                                     letter-spacing:.3px;margin-bottom:1px;overflow:hidden;">
                                            ${k.replace(/_/g,' ').slice(0,5).toUpperCase()}
                                        </div>
                                        <div style="height:2px;background:#111;border-radius:1px;overflow:hidden;">
                                            <div style="width:${Math.min(100,v)}%;height:100%;border-radius:1px;
                                                         background:${v >= 70 ? COLORS.green : v >= 45 ? COLORS.cyan : v >= 25 ? COLORS.yellow : COLORS.red};"></div>
                                        </div>
                                        <div style="font-family:monospace;font-size:6px;color:#334;margin-top:1px;">${v}</div>
                                    </div>
                                `)}
                            </div>
                        ` : null}
                    ` : null}
                </div>
                `;
            })}
        </div>

        <!-- Footer CTA when no scan -->
        ${!radarResult ? html`
            <div style="padding:8px 12px;text-align:center;border-top:1px solid #111;">
                <span style="font-family:monospace;font-size:8px;color:#2a1a3a;">
                    Scan regime để chấm điểm &nbsp;
                    <span style="color:#b565ff55;cursor:pointer;" onClick=${onOpenScan}>
                        ⚡ SCAN NOW ▸
                    </span>
                </span>
            </div>
        ` : null}

        <!-- ── AI EA Advisory (full) ── -->
        ${h(EAAdvisoryBlock, { adv: advisory, mode: 'full', COLORS })}

    </div>
    `;
}

// ─── RegimeFitDisplayPanel — standalone HTM component (avoids nested template literals) ─
function RegimeFitDisplayPanel({ radarResult, radarAsset, radarTF, radarLoading, COLORS = { green:'#00ff9d', cyan:'#00e5ff', yellow:'#ffaa00', red:'#ff3355', muted:'#445566', purple:'#b565ff', orange:'#ff8800' }, onOpenScan, riskParams, neural }) {
    const html = htm.bind(h);
const _rcGetToken = () => localStorage.getItem('za_access_token') || ''; // F-10
    const rr  = radarResult;
    const _adv = computeEAAdvisory(rr, riskParams || {}, neural || {}, null);
    const sc = rr
        ? (rr.score >= 70 ? COLORS.green : rr.score >= 50 ? COLORS.cyan : rr.score >= 30 ? COLORS.yellow : COLORS.red)
        : '#1a0a2a';
    const regimeLabel = rr ? (rr.regime || '').replace(/_/g, ' ') : null;
    const bdEntries = rr ? Object.entries(rr.breakdown || {}).slice(0, 4) : [];
    const modeMap = { STRONG: 'Trend Following', GOOD: 'Swing / Range', RISKY: 'Reduce Size', AVOID: 'No Trade Zone' };
    const suggestedMode = rr ? (modeMap[rr.regime] || (rr.strategy_hint ? rr.strategy_hint.split('.')[0] : '—')) : null;
    const setShowRadarModal = onOpenScan; // alias for template compat

    return html`
            <div style="background:#020305;border:1px solid #1a1a1a;
                        border-left:3px solid ${sc};
                        border-radius:3px;flex-shrink:0;overflow:hidden;">

                <!-- ── Panel header ── -->
                <div style="padding:7px 11px;background:#030508;border-bottom:1px solid #111;
                             display:flex;justify-content:space-between;align-items:center;">
                    <div style="display:flex;align-items:center;gap:6px;">
                        <div style="width:5px;height:5px;border-radius:50%;
                                     background:${sc};box-shadow:0 0 5px ${sc};
                                     ${rr ? 'animation:blink 2.5s ease-in-out infinite;' : ''}"></div>
                        <span style="font-family:monospace;font-size:8px;font-weight:900;
                                      letter-spacing:1.5px;color:${rr ? sc : '#2a1a3a'};">
                            ⚡ REGIME FIT
                        </span>
                        ${radarLoading ? html`
                            <span style="font-family:monospace;font-size:7px;color:#b565ff66;
                                          animation:blink 0.7s step-end infinite;">SCANNING…</span>
                        ` : null}
                    </div>
                    <div style="display:flex;align-items:center;gap:5px;">
                        ${rr ? html`
                            <span style="font-family:monospace;font-size:7px;color:#334;
                                          letter-spacing:.5px;">
                                ${new Date(rr.scanned_at||Date.now()).toLocaleTimeString('vi',{hour:'2-digit',minute:'2-digit'})}
                            </span>
                        ` : null}
                        <button onClick=${() => setShowRadarModal(true)}
                            style="background:${sc}18;border:1px solid ${sc}44;
                                   color:${sc};padding:3px 9px;font-size:8px;
                                   font-weight:900;cursor:pointer;border-radius:2px;
                                   font-family:monospace;letter-spacing:1px;transition:.15s;">
                            ${rr ? 'RESCAN ▸' : 'SCAN ▸'}
                        </button>
                    </div>
                </div>

                ${rr ? html`
                    <div style="padding:10px 11px;display:flex;flex-direction:column;gap:8px;">

                        <!-- ── Row 1: Score + Regime + Label ── -->
                        <div style="display:flex;align-items:center;gap:10px;">
                            <!-- Big score -->
                            <div style="text-align:center;flex-shrink:0;">
                                <div style="font-family:monospace;font-size:28px;font-weight:900;
                                             line-height:1;color:${sc};">${rr.score}</div>
                                <div style="font-family:monospace;font-size:7px;color:#334;
                                             letter-spacing:1px;margin-top:1px;">/100</div>
                            </div>
                            <!-- Regime info -->
                            <div style="flex:1;min-width:0;">
                                <div style="font-family:monospace;font-size:11px;font-weight:900;
                                             color:${sc};letter-spacing:.5px;
                                             white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                                    ${regimeLabel}
                                </div>
                                <div style="font-family:monospace;font-size:8px;color:#445;
                                             margin-top:2px;letter-spacing:.5px;">
                                    ${rr.label || ''}
                                </div>
                                <div style="font-family:monospace;font-size:7px;color:#334;margin-top:2px;">
                                    ${rr.asset || radarAsset} &nbsp;·&nbsp; ${rr.timeframe || radarTF}
                                    ${rr.session ? html`&nbsp;·&nbsp; ${rr.session}` : null}
                                </div>
                            </div>
                            <!-- Confidence badge -->
                            ${rr.confidence ? html`
                                <div style="text-align:center;flex-shrink:0;">
                                    <div style="font-family:monospace;font-size:7px;color:#334;
                                                 letter-spacing:1px;margin-bottom:2px;">CONF</div>
                                    <div style="font-family:monospace;font-size:9px;font-weight:900;
                                                 color:${rr.confidence==='HIGH'?COLORS.green:rr.confidence==='MEDIUM'?COLORS.cyan:COLORS.yellow};">
                                        ${rr.confidence}
                                    </div>
                                </div>
                            ` : null}
                        </div>

                        <!-- ── Score bar ── -->
                        <div style="height:3px;background:#0a0c12;border-radius:2px;overflow:hidden;">
                            <div style="width:${rr.score}%;height:100%;background:${sc};
                                         border-radius:2px;transition:width .8s ease;"></div>
                        </div>

                        <!-- ── Breakdown bars (compact) ── -->
                        ${bdEntries.length > 0 ? html`
                            <div style="display:flex;flex-direction:column;gap:4px;">
                                ${bdEntries.map(([k, v]) => html`
                                    <div style="display:flex;align-items:center;gap:6px;">
                                        <span style="font-family:monospace;font-size:7px;color:#334;
                                                      width:72px;flex-shrink:0;letter-spacing:.3px;
                                                      white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                                            ${k.replace(/_/g,' ')}
                                        </span>
                                        <div style="flex:1;height:2px;background:#111;border-radius:1px;overflow:hidden;">
                                            <div style="width:${Math.min(100,parseInt(v))}%;height:100%;
                                                         background:${sc}99;border-radius:1px;"></div>
                                        </div>
                                        <span style="font-family:monospace;font-size:8px;font-weight:900;
                                                      color:${sc};min-width:20px;text-align:right;">
                                            ${parseInt(v)}
                                        </span>
                                    </div>
                                `)}
                            </div>
                        ` : null}

                        <!-- ── Risk note (first one, if any) ── -->
                        ${(rr.risk_notes||[]).length > 0 ? html`
                            <div style="padding:5px 8px;background:#ff440008;
                                         border:1px solid #ff440020;border-radius:2px;
                                         font-family:monospace;font-size:8px;
                                         color:#ff444477;line-height:1.5;">
                                ⚠ ${rr.risk_notes[0]}
                                ${rr.risk_notes.length > 1 ? html`
                                    <span style="color:#334;"> +${rr.risk_notes.length-1} more</span>
                                ` : null}
                            </div>
                        ` : null}

                        <!-- ── AI Advisory compact + Deep Analysis CTA ── -->
                        <div style="display:flex;flex-direction:column;gap:5px;padding-top:4px;border-top:1px solid #111;">
                            <!-- compact advisor chips -->
                            ${h(EAAdvisoryBlock, { adv: _adv, mode: 'compact', COLORS })}
                            <!-- deep CTA -->
                            <button onClick=${() => setShowRadarModal(true)}
                                style="background:${sc}10;border:1px solid ${sc}30;
                                       color:${sc};padding:5px;font-size:7px;
                                       font-weight:900;cursor:pointer;border-radius:2px;
                                       font-family:monospace;letter-spacing:.8px;width:100%;">
                                DEEP ANALYSIS ▸
                            </button>
                        </div>
                    </div>
                ` : html`
                    <!-- ── Empty state ── -->
                    <div style="padding:14px 12px;text-align:center;">
                        <div style="font-size:24px;opacity:.06;margin-bottom:8px;">⚡</div>
                        <div style="font-family:monospace;font-size:9px;color:#2a1a3a;
                                     line-height:1.8;">
                            Chưa có dữ liệu regime<br/>
                            <span style="color:#b565ff44;cursor:pointer;"
                                  onClick=${() => setShowRadarModal(true)}>
                                Bấm SCAN ▸ để phân tích
                            </span>
                        </div>
                    </div>
                `}
            </div>
    `;
}

export default function RightColumn({ globalStatus, unitsConfig, activeTrades, onOpenSetup, onOpenAiBudget, COLORS = {} }) {
    const C = { green:'#00ff9d', cyan:'#00e5ff', yellow:'#ffaa00', red:'#ff3355', muted:'#445566', purple:'#b565ff', orange:'#ff8800', ...COLORS };
    const accountId = localStorage.getItem('zarmor_id') || 'MainUnit';
    const unitConfig = unitsConfig?.[accountId] || unitsConfig?.['MainUnit'] || {};
    const riskParams = unitConfig?.risk_params || {};
    const neural = unitConfig?.neural_profile || {};

    const [isArmed, setIsArmed] = useState(false);
    const [systemLogs, setSystemLogs] = useState([]);
    const [rollover, setRollover] = useState({ h: 0, m: 0, s: 0, pct: 0 });
    const [activeLogTab, setActiveLogTab] = useState('all');
    const logsEndRef = useRef(null);

    // ── Radar / RegimeFit Scanner state ──────────────────────
    const [radarResult,    setRadarResult]    = useState(null);
    const [radarLoading,   setRadarLoading]   = useState(false);
    const [showRadarModal, setShowRadarModal] = useState(false);
    const [radarAsset,     setRadarAsset]     = useState('GOLD');
    const [radarTF,        setRadarTF]        = useState('H1');
    const [radarEmail,     setRadarEmail]     = useState('');
    const [pendingApply,   setPendingApply]   = useState(false);
    const [livePrices,     setLivePrices]     = useState({});


    // ── License status: ok | warning | expired | invalid ─────
    const [licenseStatus,   setLicenseStatus]   = useState('ok');
    const [licenseDaysLeft, setLicenseDaysLeft] = useState(null);
    useEffect(() => {
        const checkLic = () => {
            const licKey    = localStorage.getItem('zarmor_license_key');
            const expiresAt = localStorage.getItem('zarmor_expires_at');
            if (!licKey)    { setLicenseStatus('invalid'); setLicenseDaysLeft(null); return; }
            if (!expiresAt) { setLicenseStatus('ok');      setLicenseDaysLeft(null); return; }
            const days = Math.ceil((new Date(expiresAt) - Date.now()) / 86400000);
            setLicenseDaysLeft(days);
            setLicenseStatus(days <= 0 ? 'expired' : days <= 3 ? 'warning' : 'ok');
        };
        checkLic();
        const iv = setInterval(checkLic, 60000);
        return () => clearInterval(iv);
    }, []);

    // ── ARM check ────────────────────────────────────────────
    useEffect(() => {
        const check = () => {
            const t = localStorage.getItem(`zarmor_hardlock_${accountId}`);
            setIsArmed(!!(t && parseInt(t) > Date.now()));
        };
        check();
        const intv = setInterval(check, 1000);
        return () => clearInterval(intv);
    }, [accountId]);

    // ── Rollover countdown ───────────────────────────────────
    useEffect(() => {
        const rolloverHour = Number(riskParams.rollover_hour) || 0;
        const tick = () => setRollover(getRolloverCountdown(rolloverHour));
        tick();
        const intv = setInterval(tick, 1000);
        return () => clearInterval(intv);
    }, [riskParams.rollover_hour]);

    // ── [FIX] Audit logs — event-driven, không polling ───────
    useEffect(() => {
        const loadLogs = () => setSystemLogs(loadAuditLogs(accountId));
        loadLogs();
        // storage event fires khi tab khác thay đổi localStorage
        const handler = (e) => { if (e.key?.includes(`zarmor_audit_${accountId}`)) loadLogs(); };
        window.addEventListener('storage', handler);
        // Custom event từ aiAgentEngine khi ghi trade/session
        const customHandler = () => loadLogs();
        window.addEventListener('zarmor_log_updated', customHandler);
        return () => {
            window.removeEventListener('storage', handler);
            window.removeEventListener('zarmor_log_updated', customHandler);
        };
    }, [accountId]);

    // Auto-scroll logs
    useEffect(() => {
        // Chỉ scroll trong container log, không scroll page
        if (logsEndRef.current) {
            const container = logsEndRef.current.closest('[data-log-container]');
            if (container) container.scrollTop = container.scrollHeight;
        }
    }, [systemLogs]);

    // ── Radar: load cache + scan function ───────────────────────
    useEffect(() => {
        try {
            const cached = JSON.parse(localStorage.getItem('zarmor_radar_last') || 'null');
            if (cached && Date.now() - cached.ts < 600_000) {
                setRadarResult(cached.data);
                setRadarAsset(cached.asset || 'GOLD');
                setRadarTF(cached.tf || 'H1');
            }
        } catch {}
    }, []);

    // ── Deep RegimeFit: đọc URL params từ scan.html → mở modal tự động ────────
    useEffect(() => {
        const params = new URLSearchParams(window.location.search);
        // F-11: Whitelist URL params before use
        const _VALID_ASSETS = ['EURUSD','GBPUSD','USDJPY','XAUUSD','BTCUSD','ETHUSD','USDCAD','AUDUSD','USDCHF','NZDUSD','US30','US100','GBPJPY','EURJPY'];
        const _VALID_TFS    = ['M1','M5','M15','M30','H1','H4','D1','W1'];
        const _rawA = params.get('radar_asset'); const asset = _VALID_ASSETS.includes(_rawA) ? _rawA : null;
        const _rawTF = params.get('radar_tf');   const tf    = _VALID_TFS.includes(_rawTF)    ? _rawTF  : null;
        const open   = params.get('open_regime');
        const apply  = params.get('open_apply');
        if (asset) setRadarAsset(asset.toUpperCase());
        if (tf)    setRadarTF(tf.toUpperCase());
        if (apply === '1') setPendingApply(true);
        if (open === '1') {
            // Delay nhỏ để component mount xong trước khi mở modal
            setTimeout(() => setShowRadarModal(true), 300);
            // Xóa param khỏi URL để tránh re-open khi refresh
            const clean = new URL(window.location.href);
            clean.searchParams.delete('open_regime');
            clean.searchParams.delete('open_apply');
            window.history.replaceState({}, '', clean.toString());
        }
    }, []);

    const _TWELVE_MAP = [
        {id:'GOLD',sym:'XAU/USD'},{id:'SILVER',sym:'XAG/USD'},{id:'OIL',sym:'WTI/USD'},
        {id:'BTC',sym:'BTC/USD'},{id:'ETH',sym:'ETH/USD'},{id:'SOL',sym:'SOL/USD'},
        {id:'NASDAQ',sym:'NDX'},{id:'SP500',sym:'SPX'},{id:'DJI',sym:'DJI'},
        {id:'EURUSD',sym:'EUR/USD'},{id:'GBPUSD',sym:'GBP/USD'},{id:'USDJPY',sym:'USD/JPY'},
        {id:'AUDUSD',sym:'AUD/USD'},{id:'USDCAD',sym:'USD/CAD'},
    ];
    // [DISABLED] /radar/prices endpoint not yet implemented on server
    // useEffect(function() {
    //     function sync() {
    //         var syms = _TWELVE_MAP.map(function(s){return encodeURIComponent(s.sym);}).join(',');
    //         fetch(window.location.origin+'/radar/prices?symbols='+syms)
    //         .then(function(r){return r.json();}).then(function(data){
    //             var prices=data.prices||data; var out={};
    //             _TWELVE_MAP.forEach(function(m){var p=prices[m.sym]||prices[m.id];
    //                 if(p) out[m.id]={price:parseFloat(p.price||p.close||p),change:parseFloat(p.change_percent||0)};});
    //             if(Object.keys(out).length) setLivePrices(out);
    //         }).catch(function(){});
    //     }
    //     sync(); var iv=setInterval(sync,30000); return function(){clearInterval(iv);};
    // }, []);
    const runRadarScan = async () => {
        setRadarLoading(true);
        try {
            const origin = window.location.origin;
            const res = await fetch(`${origin}/radar/scan`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${_rcGetToken()}` },
                body: JSON.stringify({
                    asset: radarAsset, timeframe: radarTF,
                    email: radarEmail || null,
                    send_report: !!radarEmail
                })
            });
            const data = await res.json();
            setRadarResult(data);
            localStorage.setItem('zarmor_radar_last', JSON.stringify({
                data, ts: Date.now(), asset: radarAsset, tf: radarTF
            }));
        } catch(e) {
            console.error('[RADAR]', e);
        } finally {
            setRadarLoading(false);
        }
    };

    // ── Risk Metrics (tính toán nhất quán) ───────────────────
    const currentBalance = globalStatus?.balance || 10000;
    const dailyLimit = parseFloat(riskParams?.daily_limit_money) || parseFloat(riskParams?.tactical_daily_money) || 150;
    const maxDdPct = parseFloat(riskParams?.max_dd) || 10.0;
    const floatingLoss = Math.abs(globalStatus?.total_stl || 0);
    const totalPnl = globalStatus?.total_pnl || 0;
    const dailyUsed = totalPnl < 0 ? Math.abs(totalPnl) + floatingLoss : floatingLoss;
    const currentDdPct = (dailyUsed / (currentBalance || 1)) * 100;
    const budgetPct = Math.min(100, Math.max(0, (dailyUsed / dailyLimit) * 100));
    const ddBarPct = Math.min(100, Math.max(0, (currentDdPct / maxDdPct) * 100));
    const budgetRemaining = Math.max(0, dailyLimit - dailyUsed);
    const ddRemaining = Math.max(0, maxDdPct - currentDdPct);

    const budgetColor = budgetPct >= 95 ? C.red : budgetPct > 75 ? C.yellow : C.cyan;
    const ddColor = ddBarPct >= 80 ? C.red : ddBarPct >= 60 ? C.yellow : C.green;

    // ── AI Agent data ─────────────────────────────────────────
    const sessions = useMemo(() => getSessionHistory(accountId), [accountId, isArmed]);
    const todaySession = useMemo(() => getTodaySession(accountId), [accountId, isArmed]);
    const last5 = sessions.slice(-5);
    const avgCompliance = last5.length ? Math.round(last5.reduce((s, x) => s + (x.compliance_score || 80), 0) / last5.length) : null;
    const complianceColor = !avgCompliance ? '#444' : avgCompliance >= 85 ? C.green : avgCompliance >= 60 ? C.yellow : C.red;

    // Quick stats: Hôm nay vs lịch sử
    const historyWR = sessions.length > 0 ? sessions.reduce((s, x) => s + (x.actual_wr || 0), 0) / sessions.length : null;
    const historyPnl = sessions.length > 0 ? sessions.reduce((s, x) => s + (x.pnl || 0), 0) / sessions.length : null;
    const todayWR = activeTrades?.length > 0 ? null : null; // từ globalStatus nếu có

    // ── RegimeFit Scoring Engine ──────────────────────────────
    // Chấm điểm tất cả lệnh active dựa trên radarResult mới nhất
    const scoredTrades = useMemo(() =>
        scoreAllTrades(activeTrades, radarResult, riskParams, neural),
        [activeTrades, radarResult]
    );
    const portfolioSummary = useMemo(() =>
        portfolioRegimeSummary(scoredTrades),
        [scoredTrades]
    );

    // ── AI EA Advisory — tư vấn thông số EA input ────────────
    const eaAdvisory = useMemo(() =>
        computeEAAdvisory(radarResult, riskParams, neural, portfolioSummary),
        [radarResult, riskParams, neural, portfolioSummary]
    );

    // ── Compliance alerts (đọc từ current session) ───────────
    const violations = todaySession?.violations || [];
    const hasAlerts = violations.length > 0 || budgetPct >= 90 || ddBarPct >= 80;

    // ── Log filter ────────────────────────────────────────────
    const filteredLogs = useMemo(() => {
        const logs = systemLogs.length > 0 ? systemLogs : [
            { time: 'LIVE', type: 'WARN', text: isArmed ? 'System Armed. AI Guard active.' : 'System Disarmed. Thiết lập cấu hình để bắt đầu.' }
        ];
        if (activeLogTab === 'violations') return logs.filter(l => ['COMPLIANCE_VIOL', 'DD_WARNING', 'WARN', 'CRIT'].includes(l.type));
        if (activeLogTab === 'trades') return logs.filter(l => ['TRADE_WIN', 'TRADE_LOSS', 'SESSION_OPEN', 'SESSION_CLOSE', 'TARGET_REACHED'].includes(l.type));
        return logs;
    }, [systemLogs, activeLogTab, isArmed]);

    // ── STYLES ────────────────────────────────────────────────
    const tabBtn = (id) => `padding:5px 10px; border:none; border-bottom:2px solid ${activeLogTab === id ? C.cyan : 'transparent'}; background:transparent; color:${activeLogTab === id ? C.cyan : '#444'}; font-size:8px; font-weight:900; letter-spacing:0.5px; cursor:pointer;`;

    return html`
    <div style="display:flex;flex-direction:column;gap:8px;height:100%;width:100%;overflow-y:auto;overflow-x:hidden;overscroll-behavior:contain;-webkit-overflow-scrolling:touch;scrollbar-width:thin;scrollbar-color:#1a1a1a #0a0a0a;">

        <!-- ─── ACTION BUTTONS ─── -->
        <div style="display:flex;gap:8px;flex-shrink:0;flex-direction:column;">

            ${(licenseStatus === 'expired' || licenseStatus === 'invalid') ? html`
                <div style="background:#ff000012;border:1px solid #ff000066;border-radius:3px;padding:8px 12px;display:flex;align-items:center;gap:8px;animation:blinker 1s linear infinite;">
                    <span style="font-size:14px;">🔴</span>
                    <div>
                        <div style="font-size:9px;color:#ff4444;font-weight:900;letter-spacing:1px;">
                            ${licenseStatus === 'expired' ? 'LICENSE ĐÃ HẾT HẠN' : 'CHƯA CÓ LICENSE HỢP LỆ'}
                        </div>
                        <div style="font-size:8px;color:#ff444488;margin-top:2px;">Mở Account Setup để cập nhật key mới</div>
                    </div>
                </div>
            ` : null}

            ${licenseStatus === 'warning' ? html`
                <div style="background:#ffaa0012;border:1px solid #ffaa0066;border-radius:3px;padding:8px 12px;display:flex;align-items:center;gap:8px;animation:blinker 1.5s linear infinite;">
                    <span style="font-size:14px;">⚠️</span>
                    <div>
                        <div style="font-size:9px;color:#ffaa00;font-weight:900;letter-spacing:1px;">LICENSE SẮP HẾT HẠN</div>
                        <div style="font-size:8px;color:#ffaa0088;margin-top:2px;">Còn ${licenseDaysLeft} ngày — Gia hạn ngay!</div>
                    </div>
                </div>
            ` : null}

            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;">
            <button onClick=${onOpenSetup}
                style="background:${licenseStatus==='ok'?'#0a0c10':licenseStatus==='warning'?'#ffaa0012':'#ff00001a'};border:1px solid ${licenseStatus==='ok'?'#2a2a2a':licenseStatus==='warning'?'#ffaa0066':'#ff444466'};color:${licenseStatus==='ok'?'#888':licenseStatus==='warning'?'#ffaa00':'#ff4444'};padding:10px;font-size:9px;font-weight:bold;cursor:pointer;border-radius:3px;transition:0.3s;letter-spacing:0.5px;animation:${licenseStatus!=='ok'?'blinker 1.5s linear infinite':'none'};">
                ⚙️ ACCOUNT SETUP${licenseStatus==='expired'?' 🔴':licenseStatus==='warning'?(' ⚠️ '+licenseDaysLeft+'d'):''}
            </button>
            <button onClick=${onOpenAiBudget}
                style="background:${C.cyan}0a;border:1px solid ${C.cyan}44;color:${C.cyan};padding:10px;font-size:9px;font-weight:bold;cursor:pointer;border-radius:3px;transition:0.3s;box-shadow:inset 0 0 8px ${C.cyan}11;letter-spacing:0.5px;">
                🛡️ AI GUARD
            </button>
            <button onClick=${() => setShowRadarModal(true)}
                style="background:#b565ff0a;border:1px solid #b565ff44;color:#b565ff;padding:10px;font-size:9px;font-weight:bold;cursor:pointer;border-radius:3px;transition:0.3s;letter-spacing:0.5px;${radarResult ? 'box-shadow:inset 0 0 8px #b565ff11;' : ''}">
                🎯 REGIME FIT${radarResult ? ' ●' : ''}
            </button>
            </div>
        </div>

        <!-- ─── AI AGENT STATUS TICKER ─── -->
        <div style="background:#020305;border:1px solid #1a1a1a;border-left:3px solid ${isArmed ? (hasAlerts ? C.yellow : C.green) : '#333'};border-radius:3px;padding:10px 12px;flex-shrink:0;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <span style="font-size:9px;color:${isArmed ? C.cyan : '#444'};font-weight:900;letter-spacing:1px;">🤖 AI AGENT STATUS</span>
                <div style="display:flex;align-items:center;gap:5px;">
                    <div style="width:5px;height:5px;background:${isArmed ? C.green : C.red};border-radius:50%;box-shadow:0 0 6px ${isArmed ? C.green : C.red};"></div>
                    <span style="font-size:8px;color:#555;font-weight:bold;">${isArmed ? 'ARMED' : 'OFFLINE'}</span>
                </div>
            </div>

            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;">
                <div style="background:#05070a;padding:6px 8px;border-radius:2px;text-align:center;">
                    <div style="font-size:8px;color:#333;margin-bottom:2px;">DNA SCORE</div>
                    ${avgCompliance ? html`
                        <div style="font-size:14px;color:${complianceColor};font-weight:900;font-family:monospace;">${avgCompliance}</div>
                        <div style="font-size:7px;color:#333;">/100</div>
                    ` : html`<div style="font-size:10px;color:#222;font-style:italic;">—</div>`}
                </div>
                <div style="background:#05070a;padding:6px 8px;border-radius:2px;text-align:center;">
                    <div style="font-size:8px;color:#333;margin-bottom:2px;">SESSIONS</div>
                    <div style="font-size:14px;color:#888;font-weight:900;font-family:monospace;">${sessions.length}</div>
                    <div style="font-size:7px;color:#333;">lịch sử</div>
                </div>
                <div style="background:#05070a;padding:6px 8px;border-radius:2px;text-align:center;">
                    <div style="font-size:8px;color:#333;margin-bottom:2px;">ALERTS</div>
                    <div style="font-size:14px;color:${violations.length > 0 ? C.red : C.green};font-weight:900;font-family:monospace;">${violations.length}</div>
                    <div style="font-size:7px;color:#333;">vi phạm</div>
                </div>
            </div>

            <!-- Compliance Alert Summary -->
            ${violations.length > 0 ? html`
                <div style="margin-top:8px;background:${C.red}0a;border:1px solid ${C.red}33;border-radius:2px;padding:6px 8px;">
                    ${violations.slice(0, 2).map(v => html`
                        <div style="font-size:8px;color:${C.red};line-height:1.5;">⚠ ${v.detail || v.type}</div>
                    `)}
                    ${violations.length > 2 ? html`<div style="font-size:7px;color:#444;font-style:italic;">+${violations.length - 2} vi phạm khác</div>` : null}
                </div>
            ` : isArmed ? html`
                <div style="margin-top:8px;background:${C.green}08;border:1px solid ${C.green}22;border-radius:2px;padding:6px 8px;font-size:8px;color:${C.green}88;text-align:center;">
                    ✅ Tuân thủ tốt — Không vi phạm
                </div>
            ` : null}
        </div>

        <!-- ─── REGIME FIT DISPLAY PANEL ─── -->
        ${h(RegimeFitDisplayPanel, {
            radarResult, radarAsset, radarTF, radarLoading, C,
            onOpenScan: () => setShowRadarModal(true),
            riskParams, neural,
        })}

                <!-- ─── DEFENSE SHIELD ─── -->
        <div style="background:#020305;border:1px solid #1a1a1a;border-radius:3px;flex-shrink:0;overflow:hidden;">
            <div style="padding:9px 12px;border-bottom:1px solid #111;display:flex;justify-content:space-between;align-items:center;background:#030507;">
                <div style="font-size:10px;color:${C.cyan};font-weight:900;letter-spacing:1px;display:flex;align-items:center;gap:5px;">
                    <span>🛡️</span> DEFENSE SHIELD
                </div>
                <div style="display:flex;align-items:center;gap:10px;">
                    <!-- Rollover countdown -->
                    <div style="font-size:8px;color:#333;font-family:monospace;">
                        ROLLOVER: <span style="color:${rollover.h < 1 ? C.yellow : '#444'};">${rollover.h}h ${rollover.m}m</span>
                    </div>
                    <div style="width:5px;height:5px;background:${isArmed ? C.green : C.red};border-radius:50%;box-shadow:0 0 6px ${isArmed ? C.green : C.red};"></div>
                    <span style="font-size:8px;color:#555;">${isArmed ? 'ARMED' : 'OFFLINE'}</span>
                </div>
            </div>

            <div style="padding:12px;display:flex;flex-direction:column;gap:12px;background:#03050a;">

                <!-- Daily Budget Bar -->
                <div>
                    <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:5px;">
                        <span style="font-size:8px;color:#555;font-weight:bold;letter-spacing:0.5px;">⚔️ DAILY BUDGET</span>
                        <div style="text-align:right;">
                            <span style="font-size:10px;color:${budgetColor};font-weight:bold;font-family:monospace;">$${dailyUsed.toFixed(2)}</span>
                            <span style="font-size:8px;color:#333;"> / $${dailyLimit.toFixed(2)}</span>
                        </div>
                    </div>
                    <div style="width:100%;height:7px;background:#111;overflow:hidden;border-radius:3px;border:1px solid #1a1a1a;">
                        <div style="width:${budgetPct}%;height:100%;background:${budgetColor};box-shadow:0 0 6px ${budgetColor}66;transition:width 0.5s ease-out;border-radius:3px;"></div>
                    </div>
                    <div style="display:flex;justify-content:space-between;margin-top:3px;">
                        <span style="font-size:7px;color:#333;">${budgetPct.toFixed(0)}% dùng</span>
                        <span style="font-size:7px;color:${budgetRemaining < dailyLimit * 0.15 ? C.red : '#333'};">còn $${budgetRemaining.toFixed(0)}</span>
                    </div>
                </div>

                <!-- DD Bar -->
                <div>
                    <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:5px;">
                        <span style="font-size:8px;color:#555;font-weight:bold;letter-spacing:0.5px;">☠️ STRUCTURAL CAPACITY (DD)</span>
                        <div style="text-align:right;">
                            <span style="font-size:10px;color:${ddColor};font-weight:bold;font-family:monospace;">${currentDdPct.toFixed(2)}%</span>
                            <span style="font-size:8px;color:#333;"> / ${maxDdPct.toFixed(1)}%</span>
                        </div>
                    </div>
                    <div style="width:100%;height:7px;background:#111;overflow:hidden;border-radius:3px;border:1px solid #1a1a1a;">
                        <div style="width:${ddBarPct}%;height:100%;background:${ddColor};box-shadow:0 0 6px ${ddColor}66;transition:width 0.5s ease-out;border-radius:3px;"></div>
                    </div>
                    <div style="display:flex;justify-content:space-between;margin-top:3px;">
                        <span style="font-size:7px;color:#333;">${ddBarPct.toFixed(0)}% capacity</span>
                        <span style="font-size:7px;color:${ddRemaining < 2 ? C.red : '#333'};">buffer ${ddRemaining.toFixed(2)}%</span>
                    </div>
                </div>

                <!-- Session Contract Quick View -->
                ${isArmed && todaySession ? html`
                    <div style="border-top:1px solid #111;padding-top:8px;display:flex;justify-content:space-between;">
                        <div style="text-align:center;">
                            <div style="font-size:7px;color:#333;">COMPLIANCE</div>
                            <div style="font-size:12px;color:${todaySession.compliance_score >= 80 ? C.green : C.yellow};font-weight:900;font-family:monospace;">${todaySession.compliance_score || 100}%</div>
                        </div>
                        <div style="text-align:center;">
                            <div style="font-size:7px;color:#333;">WR KẾ HOẠCH</div>
                            <div style="font-size:12px;color:${C.cyan};font-weight:900;font-family:monospace;">${todaySession.contract?.planned_wr || 55}%</div>
                        </div>
                        <div style="text-align:center;">
                            <div style="font-size:7px;color:#333;">R:R KẾ HOẠCH</div>
                            <div style="font-size:12px;color:${C.cyan};font-weight:900;font-family:monospace;">1:${todaySession.contract?.planned_rr || 2.0}</div>
                        </div>
                        <div style="text-align:center;">
                            <div style="font-size:7px;color:#333;">SESSION</div>
                            <div style="font-size:12px;color:#888;font-weight:900;font-family:monospace;">#${sessions.length + 1}</div>
                        </div>
                    </div>
                ` : !isArmed ? html`
                    <div style="text-align:center;font-size:8px;color:#222;font-style:italic;padding:4px;">Arm hệ thống trong MacroModal để kích hoạt</div>
                ` : null}
            </div>
        </div>

        <!-- ─── QUICK STATS vs HISTORY ─── -->
        ${sessions.length >= 3 ? html`
            <div style="background:#020305;border:1px solid #1a1a1a;border-radius:3px;padding:10px 12px;flex-shrink:0;">
                <div style="font-size:9px;color:#555;font-weight:bold;letter-spacing:1px;margin-bottom:8px;">📈 HÔM NAY VS LỊCH SỬ (TB ${sessions.length} phiên)</div>
                <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;">
                    ${[
                        {
                            label: 'WR TB',
                            today: null,
                            hist: historyWR !== null ? `${historyWR.toFixed(0)}%` : '—',
                            color: C.cyan
                        },
                        {
                            label: 'PnL TB',
                            today: `$${(totalPnl || 0).toFixed(0)}`,
                            hist: historyPnl !== null ? `$${historyPnl.toFixed(0)}` : '—',
                            color: totalPnl >= 0 ? C.green : C.red,
                            histColor: historyPnl !== null ? (historyPnl >= 0 ? C.green : C.red) : '#444'
                        },
                        {
                            label: 'COMPLIANCE',
                            today: todaySession ? `${todaySession.compliance_score}%` : '—',
                            hist: avgCompliance !== null ? `${avgCompliance}%` : '—',
                            color: complianceColor
                        }
                    ].map(s => html`
                        <div style="background:#05070a;padding:6px 8px;border-radius:2px;text-align:center;">
                            <div style="font-size:7px;color:#333;margin-bottom:4px;">${s.label}</div>
                            ${s.today ? html`
                                <div style="font-size:11px;color:${s.color};font-weight:900;font-family:monospace;">${s.today}</div>
                                <div style="font-size:7px;color:#333;margin-top:1px;">tb: ${s.hist}</div>
                            ` : html`
                                <div style="font-size:11px;color:${s.histColor || s.color};font-weight:900;font-family:monospace;">${s.hist}</div>
                                <div style="font-size:7px;color:#333;margin-top:1px;">${sessions.length} phiên</div>
                            `}
                        </div>
                    `)}
                </div>
            </div>
        ` : null}

        <!-- ─── REGIME FIT SCORE ─── -->
        ${scoredTrades && scoredTrades.length > 0 ? html`
            ${h(RegimeFitScorePanel, {
                scoredTrades,
                portfolioSummary,
                radarResult,
                C,
                onOpenScan: () => setShowRadarModal(true),
                advisory: eaAdvisory,
            })}
        ` : null}

                <!-- ─── SYSTEM AUDIT LOG ─── -->
        <div style="background:#020305;border:1px solid #1a1a1a;border-radius:3px;display:flex;flex-direction:column;min-height:140px;max-height:320px;overflow:hidden;">

            <!-- Log header + tabs -->
            <div style="background:#030507;padding:8px 12px;border-bottom:1px solid #111;display:flex;justify-content:space-between;align-items:center;flex-shrink:0;">
                <div style="font-size:9px;font-weight:bold;color:#555;letter-spacing:1px;">[›] AUDIT LOG</div>
                <div style="display:flex;align-items:center;gap:8px;">
                    <span style="font-size:8px;color:${C.green};opacity:0.7;">⏺ LIVE</span>
                    ${systemLogs.length > 0 ? html`
                        <div style="display:flex;gap:0;background:#0a0c10;border:1px solid #1a1a1a;border-radius:2px;">
                            <button style=${tabBtn('all')} onClick=${() => setActiveLogTab('all')}>ALL</button>
                            <button style=${tabBtn('violations')} onClick=${() => setActiveLogTab('violations')}>WARN</button>
                            <button style=${tabBtn('trades')} onClick=${() => setActiveLogTab('trades')}>TRADES</button>
                        </div>
                    ` : null}
                </div>
            </div>

            <!-- Log entries -->
            <div data-log-container="true" style="flex:1;padding:8px;overflow-y:auto;font-family:'Courier New',monospace;font-size:10px;display:flex;flex-direction:column;gap:4px;scrollbar-width:thin;scrollbar-color:#333 #111;background:#030507;">
                ${filteredLogs.map((log, i) => {
                    const cfg = LOG_CONFIG[log.type] || LOG_CONFIG['INFO'];
                    const isCrit = ['CRIT', 'COMPLIANCE_VIOL', 'TRADE_LOSS', 'DD_WARNING'].includes(log.type);
                    const isGood = ['TRADE_WIN', 'SESSION_OPEN', 'TARGET_REACHED'].includes(log.type);
                    const lineColor = isCrit ? C.red : isGood ? C.green : log.type === 'WARN' || log.type === 'OVERRIDE_UP' ? C.yellow : '#666';

                    return html`
                        <div style="display:flex;gap:6px;padding:5px 6px;background:${cfg.dark};border-left:2px solid ${lineColor}44;border-radius:2px;">
                            <span style="color:#333;font-size:8px;min-width:50px;flex-shrink:0;">[${log.time}]</span>
                            <span style="color:${lineColor};font-size:8px;min-width:46px;flex-shrink:0;">${cfg.icon} ${cfg.label}</span>
                            <span style="color:#888;font-size:9px;line-height:1.4;word-break:break-word;">${log.text}</span>
                        </div>
                    `;
                })}
                <!-- Blinking cursor -->
                <div style="display:flex;gap:8px;padding:3px 6px;opacity:0.5;">
                    <span style="color:#333;font-size:8px;">[LIVE]</span>
                    <span style="color:${C.green};animation:blink 1s step-end infinite;font-size:9px;">_</span>
                </div>
                <div ref=${logsEndRef}></div>
            </div>
        </div>

        <!-- ─── REGIME FIT MODAL (RegimeFitModal component) ─── -->
        ${showRadarModal ? h(RegimeFitModal, {
                scanData:      radarResult,
                radarAsset,    radarTF,      radarEmail,   radarLoading,
                setRadarAsset, setRadarTF,   setRadarEmail,
                runRadarScan,
                COLORS: C,
                onClose: () => setShowRadarModal(false),
                advisory: eaAdvisory,
                pendingApply,
                onApplyDone: () => setPendingApply(false),
                livePrices: livePrices,
        }) : null}

        <style>
            @keyframes blink { 50% { opacity: 0; } }
        </style>

    </div>
    `;
}