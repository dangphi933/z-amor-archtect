import { h } from 'preact';
import { useState, useEffect, useRef, useMemo } from 'preact/hooks';
import htm from 'htm';
import Chart from 'https://cdn.jsdelivr.net/npm/chart.js/auto/+esm';
// BUG E FIX: Import openSession từ aiAgentEngine thay vì dùng local copy
// Local copy thiếu: archetype, kelly_mode, profit_lock_pct, max_daily_dd_pct snapshot
import { openSession } from './aiAgentEngine.js';

const html = htm.bind(h);
const _mmGetToken = () => localStorage.getItem('za_access_token') || ''; // F-07

const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://127.0.0.1:8000'
    : `http://${window.location.hostname}:8000`;

// ─── HELPER: Load lịch sử từ AI Agent Engine ─────────────────
function loadSessions(accountId) {
    try { return JSON.parse(localStorage.getItem(`zarmor_sessions_${accountId}`) || '[]'); } catch { return []; }
}
function loadTrades(accountId) {
    try { return JSON.parse(localStorage.getItem(`zarmor_trades_${accountId}`) || '[]'); } catch { return []; }
}
const fmt = (v) => parseFloat(v || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// ─── PATTERN HEATMAP (7 ngày × 24 giờ) ─────────────────────
function buildHeatmap(trades) {
    const grid = {};
    trades.forEach(t => {
        const d = t.day_of_week ?? new Date(t.timestamp || Date.now()).getDay();
        const h = t.hour_of_day ?? new Date(t.timestamp || Date.now()).getHours();
        const k = `${d}_${h}`;
        if (!grid[k]) grid[k] = { wins: 0, total: 0 };
        grid[k].total++;
        if (t.result === 'WIN') grid[k].wins++;
    });
    return grid;
}
const DAY_LABELS = ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7'];

// ─── DNA RADAR (pure CSS bars) ───────────────────────────────
function calcDNA(sessions, trades) {
    if (!sessions.length) return null;
    const wins = trades.filter(t => t.result === 'WIN').length;
    const actualWR = trades.length ? (wins / trades.length) * 100 : 0;
    const rrArr = trades.filter(t => t.actual_rr > 0).map(t => t.actual_rr);
    const avgRR = rrArr.length ? rrArr.reduce((a, b) => a + b, 0) / rrArr.length : 0;
    const rrStd = rrArr.length > 1 ? Math.sqrt(rrArr.reduce((s, r) => s + Math.pow(r - avgRR, 2), 0) / rrArr.length) : 0;
    const consistency = Math.max(0, Math.min(100, 100 - rrStd * 20));
    const discipline = sessions.reduce((s, x) => s + (x.compliance_score || 80), 0) / sessions.length;
    const riskControl = (sessions.filter(s => (s.actual_max_dd_hit || 0) < (s.contract?.max_dd || 10)).length / sessions.length) * 100;
    const kellyArr = sessions.map(s => { const w = (s.actual_wr || 50) / 100, r = s.actual_rr_avg || 1.5; return w - (1 - w) / r; });
    const edgeStrength = Math.max(0, Math.min(100, (kellyArr.reduce((a, b) => a + b, 0) / kellyArr.length) * 200));
    let recovery = 75;
    for (let i = 1; i < sessions.length; i++) if (sessions[i - 1].pnl < 0) recovery += sessions[i].pnl > 0 ? 5 : -5;
    recovery = Math.max(0, Math.min(100, recovery));
    const hourMap = {};
    trades.forEach(t => { const h = t.hour_of_day ?? 0; if (!hourMap[h]) hourMap[h] = { w: 0, n: 0 }; hourMap[h].n++; if (t.result === 'WIN') hourMap[h].w++; });
    const wrByHour = Object.values(hourMap).map(b => b.w / b.n);
    const timing = wrByHour.length > 1 ? Math.min(100, (Math.max(...wrByHour) - Math.min(...wrByHour)) * 100 + 50) : 60;
    const overall = Math.round((consistency + discipline + riskControl + edgeStrength + recovery + timing) / 6);
    return { consistency, discipline, riskControl, edgeStrength, recovery, timing, overall, actualWR: actualWR.toFixed(1), avgRR: avgRR.toFixed(2), sessionCount: sessions.length, tradeCount: trades.length };
}

// ═══════════════════════════════════════════════════════════════
// COMPONENT CHÍNH
// ═══════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════
// STRATEGY INTELLIGENCE ZONES — MacroModal Extension
// ═══════════════════════════════════════════════════════════════════════
// Rules:
//   ✅ Zero backend calls          ✅ Zero live state mutation
//   ✅ Read-only account snapshot  ✅ Z formula untouched (no max())
//   ✅ Isolated state per zone     ✅ No external lib dependencies
// ═══════════════════════════════════════════════════════════════════════

// ─────────────────────────────────────────────────────────────────────
// ZONE 1: StrategyRegimeZone
// Pure derived state. Z + regime → tactical profile + rules.
// No hooks, no API, no mutation. Renders inline via htm.
// ─────────────────────────────────────────────────────────────────────
function StrategyRegimeZone({ z, state, marginPct, dbuPct, COLORS }) {
    const zn = parseFloat(z) || 0;

    // Thresholds mirror backend state machine exactly — no drift risk
    const profile = (() => {
        if (zn >= 0.85 || state === 'CRITICAL_BREACH' || state === 'ACCOUNT_LIQUIDATION')
            return {
                name: 'SURVIVAL MODE', color: '#ff2222', icon: '🆘',
                allow: false,
                desc: 'Hệ thống ngưỡng nguy hiểm tối đa. Ưu tiên tuyệt đối: đóng lệnh, bảo toàn vốn.',
                rules: [
                    'Đóng toàn bộ lệnh lỗ lớn nhất ngay lập tức',
                    'Nếu có lệnh lãi: trailing stop về breakeven',
                    'Volume tối đa: micro-lot duy nhất',
                    'Chờ Z < 0.60 mới xem xét mở lệnh mới',
                ],
            };
        if (zn >= 0.60)
            return {
                name: 'SCALPING COMPRESSION', color: '#ff8800', icon: '⚡',
                allow: true,
                desc: 'Áp lực cao. Chỉ scalp nhanh SL cực chặt. Không hold qua đêm, không pyramid.',
                rules: [
                    'SL tối đa: 0.5% risk per trade',
                    'Chốt TP ngay khi đạt 1R — không tham',
                    'Tối đa 2 lệnh mở đồng thời',
                    'Không trade ngược xu hướng lớn',
                ],
            };
        if (zn >= 0.30)
            return {
                name: 'CONTROLLED PULLBACK', color: '#f0e130', icon: '🎯',
                allow: true,
                desc: 'Vùng vận hành chuẩn — GOLDILOCKS zone. Giao dịch bình thường với discipline.',
                rules: [
                    'Risk per trade: 0.5–1.0%',
                    'Tuân thủ SL/TP đúng theo plan',
                    'Cho phép 3–4 lệnh đồng thời',
                    'Pyramid vào lệnh thắng khi đạt 2R',
                ],
            };
        return {
            name: 'AGGRESSIVE EXPANSION', color: '#00e5ff', icon: '🚀',
            allow: true,
            desc: 'Z thấp — vùng tự do chiến thuật. Tăng size, tìm setup high-conviction.',
            rules: [
                'Risk per trade lên đến 1.5–2.0%',
                'Pyramid vào position khi lệnh chạy tốt',
                'Tìm setup break + retest chất lượng cao',
                'Cho phép 5–6 lệnh nếu không tương quan',
            ],
        };
    })();

    const zBarPct = Math.min(zn / 1.5 * 100, 100);
    const zColor  = zn < 0.30 ? COLORS.cyan : zn < 0.60 ? COLORS.green : zn < 0.85 ? '#ff8800' : '#ff2222';
    const sigGrid = [
        { label: 'Z LOAD',  val: (zn * 100).toFixed(1) + '%', color: zColor,
          sub: zn < 0.30 ? 'Thấp ✓' : zn < 0.60 ? 'Bình thường' : zn < 0.85 ? 'Cao ⚠' : 'Nguy hiểm 🆘' },
        { label: 'MARGIN',  val: parseFloat(marginPct || 0).toFixed(1) + '%',
          color: marginPct > 30 ? '#ff8800' : marginPct > 15 ? '#f0e130' : COLORS.green,
          sub: marginPct > 30 ? 'Cao — giảm size' : 'OK' },
        { label: 'BUDGET',  val: parseFloat(dbuPct || 0).toFixed(1) + '%',
          color: dbuPct > 80 ? '#ff2222' : dbuPct > 50 ? '#ff8800' : COLORS.green,
          sub: dbuPct > 80 ? 'Cạn kiệt' : dbuPct > 50 ? 'Thận trọng' : 'Còn nhiều' },
        { label: 'STATE',   val: (state || 'OPTIMAL').split('_')[0],
          color: (state||'').includes('CRITICAL')||(state||'').includes('LIQUID') ? '#ff2222'
               : (state||'').includes('TURB') ? '#ff8800'
               : (state||'').includes('KINET') ? '#f0e130' : COLORS.green,
          sub: state || 'OPTIMAL_FLOW' },
    ];

    return html`
        <div style="padding:20px;overflow-y:auto;flex:1;">

            <div style="font-size:11px;color:#888;font-weight:bold;letter-spacing:1px;margin-bottom:4px;">⚔️ STRATEGY REGIME INTELLIGENCE</div>
            <div style="font-size:9px;color:#444;font-style:italic;margin-bottom:16px;">Phân tích chiến thuật từ Z-vector + regime. Pure derived state — zero API.</div>

            <!-- Profile badge -->
            <div style="background:#05070a;border:2px solid ${profile.color}33;border-left:4px solid ${profile.color};border-radius:4px;padding:16px 20px;margin-bottom:14px;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                    <div style="display:flex;align-items:center;gap:12px;">
                        <span style="font-size:26px;">${profile.icon}</span>
                        <div>
                            <div style="font-size:13px;font-weight:900;color:${profile.color};letter-spacing:1.5px;">${profile.name}</div>
                            <div style="font-size:8px;color:#444;margin-top:2px;letter-spacing:0.5px;">
                                ${state || 'OPTIMAL_FLOW'} &nbsp;·&nbsp; ${profile.allow ? '✅ CÓ THỂ MỞ LỆNH' : '🚫 KHÔNG MỞ LỆNH MỚI'}
                            </div>
                        </div>
                    </div>
                    <div style="text-align:right;">
                        <div style="font-size:8px;color:#555;letter-spacing:1px;">Z-PRESSURE</div>
                        <div style="font-size:22px;font-weight:900;color:${zColor};font-family:monospace;line-height:1;">${zn.toFixed(4)}</div>
                    </div>
                </div>
                <!-- Z bar with zone markers -->
                <div style="position:relative;width:100%;height:6px;background:#111;border-radius:3px;overflow:hidden;margin-bottom:6px;">
                    <div style="position:absolute;left:20%;top:0;width:1px;height:100%;background:#ffffff15;"></div>
                    <div style="position:absolute;left:40%;top:0;width:1px;height:100%;background:#ffffff15;"></div>
                    <div style="position:absolute;left:57%;top:0;width:1px;height:100%;background:#ffffff15;"></div>
                    <div style="width:${zBarPct}%;height:100%;background:linear-gradient(90deg,${COLORS.cyan},${COLORS.green} 30%,#ff8800 60%,#ff2222);border-radius:3px;transition:width 0.4s;"></div>
                </div>
                <div style="display:flex;justify-content:space-between;font-size:7px;color:#2a2a2a;margin-bottom:10px;">
                    <span>0 EXPAND</span><span>0.30</span><span>0.60</span><span>0.85</span><span>1.5 MAX</span>
                </div>
                <div style="font-size:9px;color:#666;line-height:1.6;">${profile.desc}</div>
            </div>

            <!-- Tactical rules -->
            <div style="background:#05070a;border:1px solid #111;border-radius:4px;padding:14px;margin-bottom:14px;">
                <div style="font-size:9px;color:${profile.color};font-weight:bold;margin-bottom:8px;letter-spacing:1px;">📋 QUY TẮC CHIẾN THUẬT HIỆN TẠI</div>
                ${profile.rules.map((r, i) => html`
                    <div style="display:flex;gap:8px;padding:5px 0;border-bottom:1px solid #0a0a0a;">
                        <span style="color:${profile.color};font-size:9px;font-weight:bold;min-width:14px;">${i + 1}.</span>
                        <span style="font-size:9px;color:#777;line-height:1.4;">${r}</span>
                    </div>
                `)}
            </div>

            <!-- Signal grid -->
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
                ${sigGrid.map(m => html`
                    <div style="background:#05070a;border:1px solid #111;border-radius:3px;padding:10px 12px;">
                        <div style="font-size:8px;color:#444;letter-spacing:1px;margin-bottom:2px;">${m.label}</div>
                        <div style="font-size:${m.val.length > 7 ? '12' : '17'}px;font-weight:900;color:${m.color};font-family:monospace;">${m.val}</div>
                        <div style="font-size:8px;color:#555;margin-top:2px;">${m.sub}</div>
                    </div>
                `)}
            </div>
        </div>
    `;
}


// ─────────────────────────────────────────────────────────────────────
// ZONE 2: SimulationZone (Shadow Strategy Lab)
// 200-run Monte Carlo. Deferred via setTimeout — non-blocking.
// Snapshot cloned read-only. Zero backend, zero DB, zero live mutation.
// ─────────────────────────────────────────────────────────────────────
function SimulationZone({ snapshot, COLORS }) {
    const [simWR,     setSimWR]     = useState(parseFloat(snapshot.winRate) || 50);
    const [simRR,     setSimRR]     = useState(parseFloat(snapshot.rr) || 1.5);
    const [simRisk,   setSimRisk]   = useState(0.5);
    const [simTrades, setSimTrades] = useState(20);
    const [result,    setResult]    = useState(null);
    const [running,   setRunning]   = useState(false);

    // Monte Carlo engine — runs in deferred task so UI updates first
    const runSim = () => {
        setRunning(true);
        setResult(null);
        setTimeout(() => {
            const RUNS      = 200;
            const eq0       = parseFloat(snapshot.equity)      || 100000;
            const budget    = parseFloat(snapshot.dailyBudget) || 1000;
            const floor     = parseFloat(snapshot.accountFloor)|| eq0 * 0.90;
            const riskAmt   = eq0 * (simRisk / 100);
            const winP      = simWR / 100;
            const wL = parseFloat(snapshot.wLoss)    || 0.4;
            const wG = parseFloat(snapshot.wGive)    || 0.2;

            let dbBreaches = 0, flBreaches = 0, maxZSeen = 0;
            const finals = [], paths = [];

            for (let run = 0; run < RUNS; run++) {
                let eq = eq0, dailyLoss = 0, peak = eq0;
                let dbHit = false, flHit = false;
                const path = [eq];

                for (let t = 0; t < simTrades; t++) {
                    const win    = Math.random() < winP;
                    const delta  = win ? riskAmt * simRR : -riskAmt;
                    eq += delta;
                    if (delta < 0) dailyLoss += Math.abs(delta);
                    if (eq > peak) peak = eq;
                    if (dailyLoss >= budget && !dbHit) dbHit = true;
                    if (eq <= floor  && !flHit)        flHit = true;
                    path.push(Math.max(eq, floor * 0.985));
                }

                // Approx Z using adaptive weights (loss + giveback dims only — no backend)
                const lc = Math.min(1.0, dailyLoss / Math.max(budget, 1));
                const maxP = Math.max(0, peak - eq0);
                const gb   = Math.max(0, peak - eq);
                const gc   = maxP > 0 ? Math.min(1.0, gb / (maxP * 0.4)) : 0;
                const zSim = Math.min(1.5, wL * lc + wG * gc);
                if (zSim > maxZSeen) maxZSeen = zSim;

                finals.push(eq);
                if (dbHit) dbBreaches++;
                if (flHit) flBreaches++;
                if (run < 8) paths.push(path);
            }

            finals.sort((a, b) => a - b);
            const p10 = finals[Math.floor(RUNS * 0.10)];
            const p50 = finals[Math.floor(RUNS * 0.50)];
            const p90 = finals[Math.floor(RUNS * 0.90)];

            setResult({
                dbPct: (dbBreaches / RUNS * 100).toFixed(1),
                flPct: (flBreaches / RUNS * 100).toFixed(1),
                maxZ:  Math.min(1.5, maxZSeen).toFixed(4),
                p10: p10.toFixed(0), p50: p50.toFixed(0), p90: p90.toFixed(0),
                expDD: Math.max(0, eq0 - p50).toFixed(0),
                paths, runs: RUNS,
            });
            setRunning(false);
        }, 10);
    };

    // SVG sparkline — pure inline, no Chart.js, no lib
    const Sparkline = ({ paths, eq0, budget, floor }) => {
        if (!paths?.length) return html`<div></div>`;
        const all  = paths.flat();
        const minV = Math.min(...all, floor) * 0.998;
        const maxV = Math.max(...all, eq0)   * 1.002;
        const W = 280, H = 72;
        const sx = (i, n) => (i / Math.max(n - 1, 1)) * W;
        const sy = v => H - ((v - minV) / Math.max(maxV - minV, 1)) * H;
        return html`
            <svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" style="width:100%;height:72px;">
                <line x1="0" y1="${sy(eq0)}"          x2="${W}" y2="${sy(eq0)}"          stroke="#ffffff18" stroke-width="1"/>
                <line x1="0" y1="${sy(eq0 - budget)}" x2="${W}" y2="${sy(eq0 - budget)}" stroke="#ff880066" stroke-width="1" stroke-dasharray="4,3"/>
                <line x1="0" y1="${sy(floor)}"         x2="${W}" y2="${sy(floor)}"         stroke="#ff222266" stroke-width="1.5" stroke-dasharray="2,4"/>
                ${paths.map(path => {
                    const fin = path[path.length - 1];
                    const col = fin >= eq0 ? COLORS.cyan + '70' : fin >= floor ? COLORS.yellow + '55' : COLORS.red + '55';
                    const pts = path.map((v,i) => `${sx(i,path.length).toFixed(1)},${sy(v).toFixed(1)}`).join(' ');
                    return html`<polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.5" stroke-linejoin="round"/>`;
                })}
                <text x="3" y="${sy(eq0)-3}"          font-size="7" fill="#ffffff33">START</text>
                <text x="3" y="${sy(eq0-budget)-3}"   font-size="7" fill="#ff880099">BUDGET</text>
                <text x="3" y="${sy(floor)-3}"         font-size="7" fill="#ff222299">FLOOR</text>
            </svg>
        `;
    };

    const slCss = `width:100%;accent-color:${COLORS.cyan};`;
    const db = parseFloat(result?.dbPct || 0), fl = parseFloat(result?.flPct || 0);
    const advice = !result ? '' :
        db > 30 ? '⚠️ Xác suất thủng budget >30% — giảm risk/trade ngay.' :
        fl > 5  ? '🆘 Xác suất thủng Account Floor >5% — nguy hiểm!' :
        db < 5  ? '✅ Cấu hình ổn định. Risk trong ngưỡng bền vững.' :
                  '🟡 Chấp nhận được. Monitor Z-pressure liên tục.';

    return html`
        <div style="padding:20px;overflow-y:auto;flex:1;">
            <div style="font-size:11px;color:#888;font-weight:bold;letter-spacing:1px;margin-bottom:4px;">🔬 SHADOW STRATEGY LAB — MONTE CARLO</div>
            <div style="font-size:9px;color:#444;font-style:italic;margin-bottom:16px;">200 simulations — client-side only. Snapshot tĩnh. KHÔNG ghi DB, KHÔNG ảnh hưởng tài khoản.</div>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:16px;">

                <!-- Snapshot readonly -->
                <div style="background:#05070a;border:1px solid #1a1a1a;border-radius:4px;padding:14px;">
                    <div style="font-size:9px;color:#555;font-weight:bold;letter-spacing:1px;margin-bottom:10px;">📸 ACCOUNT SNAPSHOT (READ-ONLY)</div>
                    ${[
                        { l:'Equity',        v:'$'+parseFloat(snapshot.equity||0).toLocaleString('en-US',{minimumFractionDigits:2}) },
                        { l:'Z-Pressure',    v:parseFloat(snapshot.z||0).toFixed(4) },
                        { l:'Daily Budget',  v:'$'+parseFloat(snapshot.dailyBudget||0).toFixed(0) },
                        { l:'Account Floor', v:'$'+parseFloat(snapshot.accountFloor||0).toFixed(0) },
                        { l:'Regime',        v:snapshot.state||'N/A' },
                        { l:'Margin',        v:parseFloat(snapshot.marginPct||0).toFixed(1)+'%' },
                    ].map(x => html`
                        <div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #0a0a0a;">
                            <span style="font-size:8px;color:#333;">${x.l}</span>
                            <span style="font-size:9px;color:#aaa;font-family:monospace;font-weight:bold;">${x.v}</span>
                        </div>
                    `)}
                </div>

                <!-- Inputs -->
                <div style="background:#05070a;border:1px solid ${COLORS.cyan}22;border-radius:4px;padding:14px;">
                    <div style="font-size:9px;color:${COLORS.cyan};font-weight:bold;letter-spacing:1px;margin-bottom:10px;">⚙️ THAM SỐ MÔ PHỎNG</div>
                    ${[
                        { label:'WIN RATE', val:simWR, min:20, max:80, step:1, unit:'%', set:setSimWR },
                        { label:'R:R RATIO', val:simRR, min:0.5, max:5, step:0.1, unit:'', set:setSimRR },
                        { label:'RISK / TRADE', val:simRisk, min:0.1, max:3, step:0.1, unit:'%', set:setSimRisk },
                        { label:'SỐ LỆNH', val:simTrades, min:5, max:50, step:1, unit:'', set:setSimTrades },
                    ].map(s => html`
                        <div style="margin-bottom:10px;">
                            <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
                                <span style="font-size:8px;color:#555;letter-spacing:0.5px;">${s.label}</span>
                                <span style="font-size:10px;color:${COLORS.cyan};font-weight:bold;font-family:monospace;">${s.val}${s.unit}</span>
                            </div>
                            <input type="range" min="${s.min}" max="${s.max}" step="${s.step}" value="${s.val}"
                                onInput=${e => s.set(parseFloat(e.target.value))} style="${slCss}"/>
                        </div>
                    `)}
                    <button onClick=${runSim} disabled=${running}
                        style="width:100%;padding:8px;background:${running?'#111':COLORS.cyan+'18'};border:1px solid ${running?'#222':COLORS.cyan};color:${running?'#333':COLORS.cyan};font-size:10px;font-weight:900;letter-spacing:1px;cursor:${running?'wait':'pointer'};border-radius:2px;transition:0.2s;">
                        ${running ? '⏳ ĐANG TÍNH 200 RUNS...' : '▶ CHẠY MÔ PHỎNG'}
                    </button>
                </div>
            </div>

            <!-- Results -->
            ${result ? html`
                <div style="background:#05070a;border:1px solid #1a1a1a;border-radius:4px;padding:16px;">
                    <div style="font-size:9px;color:${COLORS.cyan};font-weight:bold;letter-spacing:1px;margin-bottom:12px;">📊 KẾT QUẢ — ${result.runs} SIMULATIONS</div>
                    <div style="background:#030507;border:1px solid #111;border-radius:3px;padding:10px;margin-bottom:12px;">
                        <div style="font-size:8px;color:#333;margin-bottom:4px;">8 kịch bản mẫu &nbsp;·&nbsp; <span style="color:#ff222299;">─── Floor</span> &nbsp; <span style="color:#ff880099;">- - Budget</span></div>
                        ${Sparkline({ paths:result.paths, eq0:snapshot.equity, budget:snapshot.dailyBudget, floor:snapshot.accountFloor })}
                    </div>
                    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:12px;">
                        ${[
                            { l:'BREACH BUDGET', v:result.dbPct+'%', c:db>20?'#ff2222':db>10?'#ff8800':COLORS.green, s:`${Math.round(db*2)}/200 runs` },
                            { l:'BREACH FLOOR',  v:result.flPct+'%', c:fl>5?'#ff2222':fl>0?'#ff8800':COLORS.green, s:`${Math.round(fl*2)}/200 runs` },
                            { l:'MAX Z EST.',    v:result.maxZ, c:parseFloat(result.maxZ)>0.85?'#ff2222':parseFloat(result.maxZ)>0.6?'#ff8800':COLORS.cyan, s:'adaptive weighted' },
                            { l:'P10 WORST',     v:'$'+result.p10, c:'#888', s:'worst 10%' },
                            { l:'P50 MEDIAN',    v:'$'+result.p50, c:COLORS.cyan, s:'median' },
                            { l:'P90 BEST',      v:'$'+result.p90, c:COLORS.green, s:'best 10%' },
                        ].map(m => html`
                            <div style="background:#030507;border:1px solid #0f0f0f;border-radius:3px;padding:8px;text-align:center;">
                                <div style="font-size:7px;color:#333;margin-bottom:3px;">${m.l}</div>
                                <div style="font-size:12px;font-weight:900;color:${m.c};font-family:monospace;">${m.v}</div>
                                <div style="font-size:7px;color:#333;margin-top:2px;">${m.s}</div>
                            </div>
                        `)}
                    </div>
                    <div style="background:#030507;border:1px solid #1a1a1a;border-radius:3px;padding:9px;font-size:9px;color:#555;line-height:1.5;">
                        <span style="color:#888;font-weight:bold;">Expected DD (P50): </span>
                        <span style="color:${COLORS.yellow};font-family:monospace;font-weight:bold;">-$${result.expDD}</span>
                        &nbsp;·&nbsp; ${advice}
                    </div>
                </div>
            ` : html`
                <div style="text-align:center;padding:50px 20px;color:#1a1a1a;border:1px dashed #111;border-radius:4px;">
                    <div style="font-size:36px;margin-bottom:10px;">🔬</div>
                    <div style="color:#333;font-size:10px;">Điều chỉnh tham số và nhấn <span style="color:${COLORS.cyan};font-weight:bold;">RUN</span>.</div>
                    <div style="color:#1a1a1a;font-size:8px;margin-top:6px;">200 runs — client-side, không ảnh hưởng tài khoản thực.</div>
                </div>
            `}
        </div>
    `;
}


// ─────────────────────────────────────────────────────────────────────
// ZONE 3: StrategyStressTestZone
// Parameter sensitivity → projected Z using simplified linear model.
// Model: loss_comp ≈ 1/trades_before_breach  |  margin_comp ≈ leverage/50
// Adaptive weights from live snapshot preserved. Live Z never touched.
// ─────────────────────────────────────────────────────────────────────
function StrategyStressTestZone({ snapshot, COLORS }) {
    const [stRisk,     setStRisk]     = useState(0.5);
    const [stBudget,   setStBudget]   = useState(parseFloat(snapshot.dailyBudget) || 1000);
    const [stLeverage, setStLeverage] = useState(parseFloat(snapshot.marginPct) || 5);

    // Read adaptive weights from snapshot — never altered
    const wL = parseFloat(snapshot.wLoss)    || 0.4;
    const wG = parseFloat(snapshot.wGive)    || 0.2;
    const wA = parseFloat(snapshot.wAccount) || 0.3;
    const wM = parseFloat(snapshot.wMargin)  || 0.1;
    // giveback + account components from live snapshot (frozen)
    const giveComp = parseFloat(snapshot.giveComp) || 0;
    const accComp  = parseFloat(snapshot.accComp)  || 0;

    // Projection: simplified linear scaling on loss_comp + margin_comp
    // Does NOT replace live adaptive vector engine
    const projectZ = (risk, budget, leverage) => {
        const riskAmt = parseFloat(snapshot.equity) * (risk / 100);
        const ttb     = budget / Math.max(riskAmt, 0.01);   // trades to budget breach
        const lc      = Math.min(1.0, 1.0 / Math.max(ttb, 1));
        const mc      = Math.min(1.0, leverage / 50.0);
        // Z = weighted sum (same formula structure as backend, no max())
        return Math.min(1.5, Math.max(0, wL*lc + wG*giveComp + wA*accComp + wM*mc));
    };

    const zC = z => z < 0.30 ? COLORS.cyan : z < 0.60 ? COLORS.green : z < 0.85 ? '#ff8800' : '#ff2222';
    const zL = z => z < 0.30 ? 'SAFE' : z < 0.60 ? 'NORMAL' : z < 0.85 ? 'WARN' : 'DANGER';

    const liveZ    = parseFloat(snapshot.z) || 0;
    const curZ     = projectZ(stRisk, stBudget, stLeverage);
    const delta    = curZ - liveZ;
    const dColor   = delta > 0.1 ? '#ff8800' : delta < -0.1 ? COLORS.green : '#888';

    const riskPts  = [0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0];
    const bdMults  = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0];
    const slCss    = `width:100%;accent-color:${COLORS.cyan};`;
    const budBase  = parseFloat(snapshot.dailyBudget) || 1000;

    return html`
        <div style="padding:20px;overflow-y:auto;flex:1;">
            <div style="font-size:11px;color:#888;font-weight:bold;letter-spacing:1px;margin-bottom:4px;">📐 STRATEGY STRESS TEST — SENSITIVITY PROJECTION</div>
            <div style="font-size:9px;color:#444;font-style:italic;margin-bottom:16px;">
                Chiếu Z theo tham số. Linear approximation — KHÔNG thay đổi Z thực, KHÔNG gọi backend.
                Adaptive weights từ live engine được giữ nguyên.
            </div>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:16px;">

                <!-- Sliders -->
                <div style="background:#05070a;border:1px solid ${COLORS.cyan}22;border-radius:4px;padding:16px;">
                    <div style="font-size:9px;color:${COLORS.cyan};font-weight:bold;letter-spacing:1px;margin-bottom:12px;">🎛️ ĐIỀU CHỈNH THAM SỐ</div>

                    ${[
                        { label:'RISK PER TRADE', val:stRisk, min:0.1, max:3, step:0.05, unit:'%', set:setStRisk },
                        { label:'DAILY LOSS LIMIT', val:stBudget, min:Math.max(50,Math.round(budBase*0.1)), max:Math.round(budBase*2.5), step:10, unit:'$', pre:'$', set:setStBudget },
                        { label:'LEVERAGE / MARGIN%', val:stLeverage, min:1, max:50, step:1, unit:'%', set:setStLeverage },
                    ].map(s => html`
                        <div style="margin-bottom:12px;">
                            <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
                                <span style="font-size:8px;color:#555;">${s.label}</span>
                                <span style="font-size:10px;color:${COLORS.cyan};font-weight:bold;font-family:monospace;">${s.pre||''}${s.val}${s.unit!=='$'?s.unit:''}</span>
                            </div>
                            <input type="range" min="${s.min}" max="${s.max}" step="${s.step}" value="${s.val}"
                                onInput=${e => s.set(parseFloat(e.target.value))} style="${slCss}"/>
                            <div style="display:flex;justify-content:space-between;font-size:7px;color:#222;">
                                <span>${s.pre||''}${s.min}</span><span>${s.pre||''}${s.max}</span>
                            </div>
                        </div>
                    `)}
                </div>

                <!-- Live Z readout -->
                <div style="background:#05070a;border:1px solid ${zC(curZ)}33;border-radius:4px;padding:16px;display:flex;flex-direction:column;justify-content:center;align-items:center;gap:8px;">
                    <div style="font-size:8px;color:#444;letter-spacing:2px;">PROJECTED Z-PRESSURE</div>
                    <div style="font-size:34px;font-weight:900;color:${zC(curZ)};font-family:monospace;line-height:1;">${curZ.toFixed(4)}</div>
                    <div style="font-size:10px;font-weight:bold;color:${zC(curZ)};letter-spacing:2px;">${zL(curZ)}</div>
                    <div style="width:100%;height:5px;background:#111;border-radius:3px;overflow:hidden;">
                        <div style="width:${Math.min(curZ/1.5*100,100)}%;height:100%;background:linear-gradient(90deg,${COLORS.cyan},${COLORS.green} 30%,#ff8800 60%,#ff2222);transition:width 0.3s;"></div>
                    </div>
                    <div style="font-size:8px;color:#444;text-align:center;">
                        Live Z: <span style="color:${COLORS.cyan};font-family:monospace;">${liveZ.toFixed(4)}</span>
                        &nbsp;Δ <span style="color:${dColor};font-weight:bold;font-family:monospace;">${delta>=0?'+':''}${delta.toFixed(4)}</span>
                    </div>
                    <!-- Adaptive weights display (read-only mirror) -->
                    <div style="width:100%;display:flex;gap:3px;margin-top:4px;">
                        ${[
                            {l:'LOSS',c:COLORS.red||'#ff4444',w:wL},
                            {l:'GIVE',c:COLORS.yellow||'#f0e130',w:wG},
                            {l:'ACC', c:'#ff8800',w:wA},
                            {l:'MAR', c:COLORS.purple||'#b565ff',w:wM},
                        ].map(wt => html`
                            <div style="flex:1;background:#0a0a0a;border:1px solid #1a1a1a;border-radius:2px;padding:3px;text-align:center;">
                                <div style="font-size:6px;color:#333;">${wt.l}</div>
                                <div style="font-size:9px;color:${wt.c};font-family:monospace;font-weight:bold;">${(wt.w*100).toFixed(0)}%</div>
                            </div>
                        `)}
                    </div>
                </div>
            </div>

            <!-- Sensitivity table: risk% → Z -->
            <div style="background:#05070a;border:1px solid #111;border-radius:4px;padding:14px;margin-bottom:14px;">
                <div style="font-size:9px;color:#555;font-weight:bold;letter-spacing:1px;margin-bottom:10px;">📊 NHẠY CẢM — RISK PER TRADE → PROJECTED Z</div>
                <table style="width:100%;border-collapse:collapse;font-size:9px;">
                    <thead>
                        <tr style="border-bottom:1px solid #1a1a1a;">
                            <th style="padding:5px 8px;color:#444;text-align:left;">Risk %</th>
                            <th style="padding:5px 8px;color:#444;text-align:center;">Z Chiếu</th>
                            <th style="padding:5px 8px;color:#444;text-align:center;">Zone</th>
                            <th style="padding:5px 8px;color:#444;text-align:right;">Lệnh → Breach</th>
                            <th style="padding:5px 8px;color:#444;text-align:right;">Risk $</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${riskPts.map(r => {
                            const pz   = projectZ(r, stBudget, stLeverage);
                            const rAmt = parseFloat(snapshot.equity) * r / 100;
                            const ttb  = Math.ceil(stBudget / Math.max(rAmt, 0.01));
                            const cur  = Math.abs(r - stRisk) < 0.08;
                            return html`
                                <tr style="border-bottom:1px solid #0a0a0a;background:${cur?COLORS.cyan+'08':'transparent'};">
                                    <td style="padding:5px 8px;color:${cur?COLORS.cyan:'#666'};font-weight:${cur?'bold':'normal'};font-family:monospace;">
                                        ${r}% ${cur?'◀':''}
                                    </td>
                                    <td style="padding:5px 8px;text-align:center;color:${zC(pz)};font-weight:bold;font-family:monospace;">${pz.toFixed(4)}</td>
                                    <td style="padding:5px 8px;text-align:center;">
                                        <span style="background:${zC(pz)}22;color:${zC(pz)};padding:2px 7px;border-radius:2px;font-size:8px;font-weight:bold;">${zL(pz)}</span>
                                    </td>
                                    <td style="padding:5px 8px;text-align:right;color:#555;font-family:monospace;">${ttb>9999?'∞':ttb}</td>
                                    <td style="padding:5px 8px;text-align:right;color:#444;font-family:monospace;">$${rAmt.toFixed(0)}</td>
                                </tr>
                            `;
                        })}
                    </tbody>
                </table>
            </div>

            <!-- Budget sensitivity cards -->
            <div style="background:#05070a;border:1px solid #111;border-radius:4px;padding:14px;">
                <div style="font-size:9px;color:#555;font-weight:bold;letter-spacing:1px;margin-bottom:10px;">📊 NHẠY CẢM — DAILY BUDGET → PROJECTED Z</div>
                <div style="display:flex;gap:6px;flex-wrap:wrap;">
                    ${bdMults.map(m => {
                        const b   = Math.round(budBase * m);
                        const pz  = projectZ(stRisk, b, stLeverage);
                        const cur = Math.abs(b - stBudget) < stBudget * 0.12;
                        return html`
                            <div style="flex:1;min-width:72px;background:#030507;border:1px solid ${cur?COLORS.cyan+'55':'#0f0f0f'};border-radius:3px;padding:8px;text-align:center;">
                                <div style="font-size:7px;color:#333;margin-bottom:1px;">${m>=1?'×'+m:'-'+Math.round((1-m)*100)+'%'}</div>
                                <div style="font-size:8px;color:#333;font-family:monospace;margin-bottom:3px;">$${b}</div>
                                <div style="font-size:13px;font-weight:900;color:${zC(pz)};font-family:monospace;">${pz.toFixed(3)}</div>
                                <div style="font-size:7px;color:${zC(pz)};margin-top:1px;">${zL(pz)}</div>
                            </div>
                        `;
                    })}
                </div>
            </div>
        </div>
    `;
}

export default function MacroModal({ globalStatus, unitsConfig, myUnitConfig, activeSetup, COLORS, onClose, fetchData }) {
    const accountId = activeSetup || 'MainUnit';
    const targetConfig = myUnitConfig || (unitsConfig?.[accountId] || unitsConfig?.['MainUnit'] || {});
    const riskParams = targetConfig.risk_params || {};
    const neural = targetConfig.neural_profile || {};
    const macroMetrics = globalStatus?.macro_metrics || {};

    // ── AI History ────────────────────────────────────────────
    const sessions = useMemo(() => loadSessions(accountId), [accountId]);
    const trades   = useMemo(() => loadTrades(accountId),   [accountId]);
    const dna      = useMemo(() => calcDNA(sessions, trades), [sessions, trades]);
    const heatmap  = useMemo(() => buildHeatmap(trades), [trades]);

    // ── Raw data (Đưa lên TRƯỚC Hooks để khai báo logic tuần tự) ───
    const initialCapital = macroMetrics.initial_capital || 10000;
    const currentBalance = globalStatus?.balance || initialCapital;
    const totalPnl = globalStatus?.total_pnl || 0;
    const floatingLoss = Math.abs(globalStatus?.total_stl || 0);
    const projectedReward = globalStatus?.total_tp_reward || 0;
    const hardLimitPct = riskParams.max_dd || 10.0;
    const conversionRatio = floatingLoss > 0 ? projectedReward / floatingLoss : (projectedReward > 0 ? Infinity : 0);
    const actualDailyLimit = parseFloat(riskParams.daily_limit_money) || parseFloat(riskParams.tactical_daily_money) || 150;
    // ── Hiến Pháp: chỉ đọc từ SetupModal, không chỉnh ở đây ─────
    const constitutionMaxDailyDdPct = parseFloat(riskParams.max_daily_dd_pct) || 5.0;
    const constitutionMaxDailyDd$   = currentBalance * constitutionMaxDailyDdPct / 100;

    // ── State ─────────────────────────────────────────────────
    const [isArmed, setIsArmed]   = useState(false);
    // BUG H FIX: Zone B lock — chỉ Contract fields bị lock, không phải toàn bộ modal
    // Zone A (Sandbox): expectedWR, expectedRR, targetProfit, timeframe — KHÔNG BAO GIỜ lock
    // Zone B (Contract): dailyBudget, profitLockPct — lock sau ARM đến Rollover
    const [contractLocked, setContractLocked] = useState(false);

    // Zone A — Sandbox inputs (luôn chỉnh được, chỉ ảnh hưởng chart)
    const [targetProfit, setTargetProfit] = useState(riskParams.target_profit || '');
    const [timeframe, setTimeframe]       = useState(riskParams.target_timeframe || 'DAY');
    const [expectedWR, setExpectedWR]     = useState(neural.historical_win_rate || 40);
    const [expectedRR, setExpectedRR]     = useState(neural.historical_rr || 1.5);

    // Zone B — Contract inputs (lock sau ARM)
    const [dailyBudget, setDailyBudget]     = useState(actualDailyLimit);
    const [profitLockPct, setProfitLockPct] = useState(riskParams.profit_lock_pct || 40);
    // 3-source budget selector: 'pct' | 'ai' | 'manual'
    const [budgetMode, setBudgetMode]       = useState('pct');

    // BUG H FIX: ddType và maxDdPct KHÔNG còn là state ở MacroModal
    // Chúng thuộc SetupModal (owner: Hiến Pháp). MacroModal chỉ HIỂN THỊ readonly.
    // Đọc trực tiếp từ riskParams (đã được SetupModal ghi vào DB)
    // const [ddType, setDdType]       = useState(...)  ← ĐÃ XÓA
    // const [maxDdPct, setMaxDdPct]   = useState(...)  ← ĐÃ XÓA

    const [isCalculating, setIsCalculating] = useState(false);
    const [aiReport, setAiReport]           = useState(null);
    const [isSaving, setIsSaving]           = useState(false);
    const [chartBudget, setChartBudget]     = useState(actualDailyLimit);
    const [armedBudget, setArmedBudget]     = useState(parseFloat(riskParams.daily_limit_money) || actualDailyLimit);
    const [continuumTf, setContinuumTf]     = useState('H1');
    const [activeRightTab, setActiveRightTab] = useState('charts');
    const calcTimerRef = useRef(null);

    // ── Dual-layer DD computed — đọc từ SetupModal qua riskParams ──────────
    // BUG H FIX: Dùng riskParams.dd_type / riskParams.max_dd (từ SetupModal/DB)
    // thay vì local state ddType/maxDdPct đã bị xóa
    const ddType   = riskParams.dd_type || 'STATIC';
    const maxDdPct = parseFloat(riskParams.max_dd) || 10;

    // Tầng 1: Account floor
    const physics = globalStatus?.physics || {};
    const accountPeak      = physics.account_peak || currentBalance;
    const accountHardFloor = physics.account_hard_floor || (currentBalance * (1 - maxDdPct / 100));
    const accountBufferPct = physics.account_buffer_pct ?? Math.max(0, (currentBalance - accountHardFloor) / (currentBalance * maxDdPct / 100) * 100);

    const displayHardFloor = ddType === 'TRAILING'
        ? (physics.account_hard_floor || currentBalance * (1 - maxDdPct / 100))
        : currentBalance * (1 - maxDdPct / 100);

    const hardFloorVal = displayHardFloor;
    const gibbsEnergy  = Math.max(0, currentBalance - hardFloorVal);

    // Tầng 2: Daily trailing giveback
    const dailyPeak              = physics.daily_peak || physics.peak_equity || currentBalance;
    const dailyProfitReached     = Math.max(0, dailyPeak - currentBalance);
    const dailyAllowedGiveback   = dailyProfitReached * (Number(profitLockPct) / 100);
    const dailyCurrentGiveback   = Math.max(0, dailyPeak - (globalStatus?.equity || currentBalance));
    const dailyGivebackPct       = dailyAllowedGiveback > 0
        ? Math.min(100, (dailyCurrentGiveback / dailyAllowedGiveback) * 100) : 0;

    // ── Tính toán Active Target ─────────────────────────────────────────────
    const activeTarget = isArmed && riskParams.target_profit > 0
        ? Number(riskParams.target_profit)
        : (Number(targetProfit) > 0 ? Number(targetProfit) : chartBudget * Number(expectedRR) * 0.85);
    const saturationPct = Math.min(100, activeTarget > 0 ? (Math.max(0, totalPnl) / activeTarget) * 100 : 0);
    const efficiencyColor = conversionRatio === Infinity ? COLORS.cyan
        : conversionRatio > 1.5 ? COLORS.green
        : (conversionRatio < 1.0 && floatingLoss > 0) ? COLORS.red : COLORS.cyan;

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

    // Khi mount với budgetMode='pct': chỉ snap về 50% nếu CHƯA có giá trị từ server
    // BUG FIX: Không snap khi server đã có daily_limit_money hợp lệ, hoặc khi contractLocked
    useEffect(() => {
        if (budgetMode === 'pct' && constitutionMaxDailyDd$ > 0) {
            const serverBudget = parseFloat(riskParams.daily_limit_money);
            if (serverBudget > 0) return;
            if (contractLocked) return;
            const pctOptions = [0.25, 0.5, 0.75, 1.0].map(p => Math.round(constitutionMaxDailyDd$ * p));
            if (!pctOptions.includes(dailyBudget)) {
                setDailyBudget(Math.round(constitutionMaxDailyDd$ * 0.5));
            }
        }
    }, [constitutionMaxDailyDd$]);

    // Sync dailyBudget khi riskParams thay đổi từ server (sau fetchData hoặc tải lại)
    // Chỉ sync khi KHÔNG contractLocked — không ghi đè giá trị user đang nhập
    useEffect(() => {
        if (!contractLocked) {
            const serverBudget = parseFloat(riskParams.daily_limit_money);
            if (serverBudget > 0) setDailyBudget(serverBudget);
        }
    }, [riskParams.daily_limit_money]);

    // BUG H FIX: contractLocked — chỉ Zone B bị lock, không phải toàn modal
    // Zone A (expectedWR, expectedRR, targetProfit, timeframe) KHÔNG bị ảnh hưởng
    useEffect(() => {
        const check = () => {
            const t = localStorage.getItem(`zarmor_hardlock_${accountId}`);
            setContractLocked(!!(t && parseInt(t) > Date.now()));
        };
        check();
        const intv = setInterval(check, 1000);
        return () => clearInterval(intv);
    }, [accountId]);

    // ── AI Simulation với race-condition guard ──────────
    const runAiSimulation = () => {
        if (calcTimerRef.current) clearTimeout(calcTimerRef.current);
        setIsCalculating(true);
        setAiReport(null);
        calcTimerRef.current = setTimeout(() => {
            const target = Number(targetProfit);
            const wr = Number(expectedWR) / 100;
            const rr = Number(expectedRR);
            if (target <= 0 || wr <= 0 || rr <= 0) {
                alert('⛔ Cần điền đủ Mục tiêu, WinRate và R:R!');
                setIsCalculating(false); return;
            }
            const daysMap = { DAY: 1, WEEK: 5, MONTH: 20, QUARTER: 60 };
            const days = daysMap[timeframe] || 20;
            const dailyTarget = target / days;
            let kellyFraction = wr - (1 - wr) / rr;
            // Phân loại 3 vùng edge:
            // POSITIVE  : kelly > 0.005 (>0.5%) — có lợi thế thực sự
            // BREAKEVEN : kelly >= -0.02         — hòa vốn / edge mỏng, cảnh báo nhưng cho phép ARM
            // NEGATIVE  : kelly < -0.02          — kỳ vọng âm rõ ràng, từ chối
            let edgeStatus;
            if (kellyFraction > 0.005)       edgeStatus = 'POSITIVE';
            else if (kellyFraction >= -0.02) edgeStatus = 'BREAKEVEN';
            else                             edgeStatus = 'NEGATIVE';
            const absoluteDailyLimit = (currentBalance * hardLimitPct) / 100;
            // Ngân sách tối thiểu: cần risk X/ngày để 1 lệnh win trung bình = dailyTarget
            // X * rr * winRate * efficiency = dailyTarget → X = dailyTarget / (rr * 0.85)
            const formulaA = dailyTarget / (rr * 0.85);
            let suggestedDaily, narrative;

            if (edgeStatus === 'NEGATIVE') {
                // Kỳ vọng âm rõ ràng: giới hạn ngân sách tối thiểu, block ARM
                suggestedDaily = absoluteDailyLimit * 0.10;
                narrative = `💀 KỲ VỌNG ÂM: Kelly ${(kellyFraction * 100).toFixed(1)}% — Mỗi $1 risk kỳ vọng lỗ về dài hạn. AI từ chối cấp phép. Cần tăng R:R hoặc cải thiện WinRate.`;
            } else if (edgeStatus === 'BREAKEVEN') {
                // Breakeven / edge mỏng: cho phép ARM nhưng cảnh báo, ngân sách bảo thủ
                suggestedDaily = Math.min(formulaA, absoluteDailyLimit * 0.50);
                const minRR = ((1 - wr) / wr + 0.1).toFixed(2);
                narrative = `⚠️ EDGE MỎNG: Kelly ${(kellyFraction * 100).toFixed(1)}% — Hệ thống gần hòa vốn kỳ vọng. Mục tiêu $${target} khó đạt ổn định. Ngân sách bảo thủ: $${Math.round(suggestedDaily)}/ngày. Nên tăng R:R lên >${minRR} để có edge dương.`;
            } else {
                // Edge dương: dùng formulaA, cap tại 85% daily limit
                suggestedDaily = Math.min(formulaA, absoluteDailyLimit * 0.85);
                if (suggestedDaily < 0 || isNaN(suggestedDaily)) suggestedDaily = currentBalance * 0.005;
                if (suggestedDaily >= absoluteDailyLimit * 0.84) {
                    narrative = `⚠️ QUÁ TẢI: Mục tiêu $${target} đòi hỏi vượt Max DD. AI hãm phanh ngân sách về $${Math.round(suggestedDaily)}/ngày.`;
                } else {
                    narrative = `✅ TOÁN HỌC ỦNG HỘ: Edge Dương | Kelly ${(kellyFraction * 100).toFixed(1)}%. Ngân sách tác chiến: $${Math.round(suggestedDaily)}/ngày.`;
                }
            }
            const rep = { suggestedDaily: Math.max(10, Math.round(suggestedDaily)), edgeStatus, kelly: (kellyFraction * 100).toFixed(1), message: narrative };
            setAiReport(rep);
            setChartBudget(rep.suggestedDaily);
            // FIX: Tự động sync dailyBudget khi AI tính xong (nếu Zone B chưa lock)
            // Tránh tình trạng user click ARM mà dailyBudget vẫn là giá trị cũ
            if (!contractLocked) setDailyBudget(rep.suggestedDaily);
            setIsCalculating(false);
        }, 800);
    };

    // ── ARM system ───────────────────────────────────────────
    const handleArmSystem = async () => {
        if (!aiReport || aiReport.edgeStatus === 'NEGATIVE') return;
        if (!window.confirm('☢️ LỜI THỀ ĐỘNG NĂNG\n\nCam kết giao dịch đúng R:R và Ngân sách này. Sẵn sàng?')) return;
        setIsSaving(true);
        const finalBudget = aiReport.suggestedDaily;
        // ── Helper: fetch với timeout ──────────────────────────
        const fetchWithTimeout = async (url, options, timeoutMs = 10000) => {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), timeoutMs);
            try {
                const res = await fetch(url, { ...options, signal: controller.signal });
                clearTimeout(timer);
                return res;
            } catch (err) {
                clearTimeout(timer);
                throw err;
            }
        };

        try {
            const currentUnit = (unitsConfig && unitsConfig[accountId]) || (unitsConfig && unitsConfig['MainUnit']) || {};
            // dailyBudget = giá trị user nhập / chọn — LUÔN ưu tiên cao nhất
            // finalBudget = AI-suggested — chỉ fallback khi dailyBudget = 0
            const resolvedBudget = dailyBudget || finalBudget;
            const payload = {
                unit_key:   accountId,
                mt5_login:  accountId,
                source: "MacroModal",
                arm: true,   // BUG FIX: báo backend đây là ARM thật → mới set is_locked=True
                risk_params: {
                    // MacroModal CHỈ ghi tactical fields — KHÔNG ghi dd_type, max_dd, max_daily_dd_pct
                    tactical_daily_money: resolvedBudget,
                    daily_limit_money:    resolvedBudget,
                    profit_lock_pct:      Number(profitLockPct),
                    target_profit:        Number(targetProfit),
                    target_timeframe:     timeframe,
                },
                neural_profile: {
                    ...(currentUnit.neural_profile || {}),
                    historical_win_rate: Number(expectedWR),
                    historical_rr:       Number(expectedRR),
                    optimization_bias:   'ACCEPT_AI'
                }
            };

            // ── Bước 1: update-unit-config ────────────────────────
            let res;
            try {
                res = await fetchWithTimeout(
                    `${API_BASE}/api/update-unit-config`,
                    { method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${_mmGetToken()}` }, body: JSON.stringify(payload) } // F-07
                );
            } catch (networkErr) {
                const isTimeout = networkErr.name === 'AbortError';
                alert(`❌ ${isTimeout ? 'Timeout (10s)' : 'Mất kết nối'} khi gọi /api/update-unit-config\n\nServer: ${API_BASE}\nLỗi: ${networkErr.message}\n\nKiểm tra: server có đang chạy không? Port 8000 có mở không?`);
                return;
            }

            if (!res.ok) {
                let detail = '';
                try { const j = await res.json(); detail = j.detail || JSON.stringify(j); } catch {}
                alert(`❌ Server lỗi HTTP ${res.status} tại /api/update-unit-config\n\n${detail}`);
                return;
            }

            // ── Bước 2: panic-kill (non-critical, không block ARM) ─
            try {
                await fetchWithTimeout(
                    `${API_BASE}/api/panic-kill`,
                    { method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${_mmGetToken()}` }, body: JSON.stringify({ account_id: accountId }) }, // F-07
                    5000
                );
            } catch (pkErr) {
                console.warn('[ARM] panic-kill failed (non-critical):', pkErr.message);
            }

            // ── Bước 3: ARM thành công ─────────────────────────────
            const rollover = Number(riskParams.rollover_hour) || 0;
            const next = new Date(); next.setHours(rollover, 0, 0, 0);
            if (Date.now() >= next.getTime()) next.setDate(next.getDate() + 1);
            localStorage.setItem('zarmor_id', accountId);
            localStorage.setItem(`zarmor_hardlock_${accountId}`, next.getTime().toString());

            // BUG E FIX: Dùng openSession từ aiAgentEngine.js (đã import)
            // Signature: openSession(accountId, setupContract, macroContract)
            // setupContract = hard limits từ SetupModal (Hiến Pháp)
            // macroContract = tactical + neural từ MacroModal (Lời thề)
            openSession(
                accountId,
                // setupContract — snapshot Hiến Pháp tại thời điểm ARM
                {
                    daily_limit_money:  resolvedBudget,
                    max_dd:             parseFloat(riskParams.max_dd) || 10,
                    dd_type:            riskParams.dd_type || 'STATIC',
                    max_daily_dd_pct:   constitutionMaxDailyDdPct,
                    profit_lock_pct:    Number(profitLockPct),
                },
                // macroContract — neural + balance info
                {
                    historical_win_rate: Number(expectedWR),
                    historical_rr:       Number(expectedRR),
                    trader_archetype:    (currentUnit.neural_profile || {}).trader_archetype || 'SNIPER',
                    optimization_bias:   (currentUnit.neural_profile || {}).optimization_bias || 'HALF_KELLY',
                    current_balance:     currentBalance,
                }
            );
            setIsArmed(true);
            setChartBudget(resolvedBudget);
            setArmedBudget(resolvedBudget);   // FIX: lưu để header + contract box không bị fetchData ghi đè

        } catch (e) {
            console.error('[ARM] Unexpected error:', e);
            alert(`❌ Lỗi không xác định:\n${e.message}\n\nMở Console (F12) để xem chi tiết.`);
        } finally {
            setIsSaving(false);
            if (fetchData) await fetchData();
        }
    };

    // ── ADMIN OVERRIDE — mở khóa Contract để chỉnh lại thông số ──────
    const handleAdminOverride = async () => {
        if (!window.confirm(
            '⚠️ ADMIN OVERRIDE\n\n' +
            'Mở khóa Contract để chỉnh Budget/Lock.\n' +
            'Session hiện tại sẽ bị hủy ARM.\n\n' +
            'Xác nhận?'
        )) return;

        // 1. Xóa hardlock localStorage
        localStorage.removeItem(`zarmor_hardlock_${accountId}`);

        // 2. Gọi API unlock
        try {
            await fetch(`${API_BASE}/api/unlock-unit`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${_mmGetToken()}` }, // F-07
                body: JSON.stringify({ account_id: accountId })
            });
        } catch (e) {
            console.warn('[ADMIN OVERRIDE] unlock-unit failed:', e.message);
        }

        // 3. Reset states về giá trị hiện tại từ DB
        setIsArmed(false);
        setContractLocked(false);
        // Reload budget từ riskParams (đã được sync từ DB qua fetchData)
        const currentBudget = parseFloat(riskParams.daily_limit_money) || actualDailyLimit;
        setDailyBudget(currentBudget);
        setChartBudget(currentBudget);
        setAiReport(null);

        if (fetchData) await fetchData();
    };

    // ── CHART REFS ────────────────────────────────────────────
    const tfConfig = { M15: { past: 60, future: 30, noise: 0.3 }, H1: { past: 40, future: 20, noise: 0.6 }, H4: { past: 30, future: 15, noise: 1.2 }, D1: { past: 15, future: 8, noise: 2.5 } };
    const matrixRef = useRef(null);    const matrixInst = useRef(null);
    const monteRef  = useRef(null);    const monteInst  = useRef(null);
    const contRef   = useRef(null);    const contInst   = useRef(null);

    // ── Matrix + Monte Carlo ──────────────────────────────────
    useEffect(() => {
        if (matrixInst.current) { matrixInst.current.destroy(); matrixInst.current = null; }
        if (monteInst.current)  { monteInst.current.destroy();  monteInst.current = null; }
        if (activeRightTab !== 'charts') return;

        const wrDec = Number(expectedWR) / 100;
        const isEdgePositive = (wrDec * Number(expectedRR) - (1 - wrDec)) > 0;

        if (matrixRef.current) {
            const breakeven = [];
            for (let w = 15; w <= 95; w += 5) { const r = (1 - w / 100) / (w / 100); if (r <= 5) breakeven.push({ x: w, y: r }); }
            const historicalPoints = sessions.slice(-10).map(s => ({
                x: s.actual_wr || 0, y: s.actual_rr_avg || 0,
                pnl: s.pnl || 0
            })).filter(p => p.x > 0);

            matrixInst.current = new Chart(matrixRef.current.getContext('2d'), {
                type: 'scatter',
                data: {
                    datasets: [
                        ...(historicalPoints.length ? [{
                            label: 'LỊCH SỬ', data: historicalPoints,
                            backgroundColor: historicalPoints.map(p => p.pnl >= 0 ? `${COLORS.green}55` : `${COLORS.red}55`),
                            borderColor: historicalPoints.map(p => p.pnl >= 0 ? COLORS.green : COLORS.red),
                            borderWidth: 1, pointRadius: 5
                        }] : []),
                        { label: 'EDGE', data: [{ x: Number(expectedWR), y: Number(expectedRR) }], backgroundColor: isEdgePositive ? COLORS.cyan : COLORS.red, borderColor: '#fff', borderWidth: 2, pointRadius: 9, pointStyle: 'star' },
                        { type: 'line', data: breakeven, borderColor: '#444', borderWidth: 1.5, borderDash: [5, 4], fill: { target: 'origin', above: 'rgba(255,42,109,0.06)' }, tension: 0.4, pointRadius: 0, label: '' }
                    ]
                },
                options: { animation: false, responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ctx.dataset.label === 'LỊCH SỬ' ? `Session: WR=${ctx.raw.x.toFixed(0)}% R:R=${ctx.raw.y.toFixed(1)}` : `Edge: WR=${ctx.raw.x}% R:R=${ctx.raw.y}` } } }, scales: { x: { min: 10, max: 100, title: { display: true, text: 'Win Rate (%)', color: '#444' }, grid: { color: '#111' }, ticks: { color: '#555' } }, y: { min: 0, max: 5, title: { display: true, text: 'R:R Ratio', color: '#444' }, grid: { color: '#111' }, ticks: { color: '#555' } } } }
            });
        }

        if (monteRef.current) {
            const paths = [];
            for (let s = 0; s < 10; s++) {
                let b = currentBalance; const path = [b];
                for (let t = 0; t < 30; t++) { b += Math.random() < wrDec ? chartBudget * Number(expectedRR) : -chartBudget; path.push(b); }
                paths.push(path);
            }
            const datasets = paths.map(p => ({ data: p, borderColor: isEdgePositive ? `${COLORS.cyan}33` : `${COLORS.red}33`, borderWidth: 1.5, tension: 0.2, pointRadius: 0, fill: false }));
            datasets.push({ label: '🎯', data: Array(31).fill(currentBalance + activeTarget), borderColor: COLORS.green, borderDash: [4, 4], borderWidth: 2, pointRadius: 0, fill: false });
            datasets.push({ label: '☠️', data: Array(31).fill(hardFloorVal), borderColor: COLORS.red, borderDash: [2, 2], borderWidth: 2, pointRadius: 0, fill: false });
            monteInst.current = new Chart(monteRef.current.getContext('2d'), {
                type: 'line', data: { labels: Array.from({ length: 31 }, (_, i) => `T${i}`), datasets },
                options: { animation: false, responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid: { color: '#0f0f0f' }, ticks: { color: '#444' } }, y: { grid: { color: '#111' }, ticks: { color: '#555', callback: v => '$' + v.toLocaleString() } } } }
            });
        }
        return () => {
            if (matrixInst.current) { matrixInst.current.destroy(); matrixInst.current = null; }
            if (monteInst.current)  { monteInst.current.destroy();  monteInst.current = null; }
        };
    }, [expectedWR, expectedRR, activeTarget, chartBudget, currentBalance, hardFloorVal, activeRightTab, COLORS, sessions]);

    // ── Continuum (3 vùng) ────────────────────────────────────
    useEffect(() => {
        if (!contRef.current || activeRightTab !== 'charts') return;
        if (contInst.current) { contInst.current.destroy(); contInst.current = null; }
        const cfg = tfConfig[continuumTf];
        const pastN = cfg.past, futureN = cfg.future, noise = cfg.noise;
        const wrDec = Number(expectedWR) / 100;

        let pastEquity = [];
        const recentSessions = sessions.slice(-pastN);
        if (recentSessions.length >= 3) {
            let b = recentSessions[0].opening_balance || currentBalance;
            pastEquity = recentSessions.map(s => { b += (s.pnl || 0); return b; });
            while (pastEquity.length < pastN) pastEquity.unshift(pastEquity[0] - (Math.random() * 50 - 25));
            pastEquity = pastEquity.slice(-pastN);
        } else {
            let b = currentBalance - gibbsEnergy * 0.3;
            for (let i = 0; i < pastN; i++) { pastEquity.push(b); b += Math.random() * chartBudget * 2 * noise - chartBudget * noise; }
        }
        pastEquity.push(currentBalance);

        const labels = [];
        for (let i = pastN; i > 0; i--) labels.push(`-${i}${continuumTf}`);
        labels.push('NOW▼');
        for (let i = 1; i <= futureN; i++) labels.push(`+${i}${continuumTf}`);

        const nullPad = Array(pastN).fill(null);
        const datasets = [];

        datasets.push({ label: 'LỊCH SỬ', data: [...pastEquity, ...Array(futureN).fill(null)], borderColor: COLORS.cyan, backgroundColor: `${COLORS.cyan}18`, borderWidth: 2.5, tension: 0.2, fill: true, pointRadius: 0, order: 10 });

        for (let s = 0; s < 5; s++) {
            let b = currentBalance; const fp = [b];
            for (let t = 0; t < futureN; t++) { b += Math.random() < wrDec ? chartBudget * Number(expectedRR) : -chartBudget; fp.push(b); }
            datasets.push({ data: [...nullPad, ...fp], borderColor: `${COLORS.cyan}28`, borderWidth: 1, tension: 0.2, pointRadius: 0, fill: false });
        }
        let bBest = currentBalance; const bestPath = [bBest];
        for (let t = 0; t < futureN; t++) { bBest += Math.random() < Math.min(wrDec * 1.15, 0.9) ? chartBudget * Number(expectedRR) : -chartBudget * 0.8; bestPath.push(bBest); }
        datasets.push({ label: 'AI BEST', data: [...nullPad, ...bestPath], borderColor: `${COLORS.green}88`, borderWidth: 2, borderDash: [6, 3], tension: 0.3, pointRadius: 0, fill: false });

        // Reference lines
        // =========================================================
        // 🚀 VẼ ĐƯỜNG CONG VẬN TỐC (VELOCITY CURVE / COMPOUNDING)
        // =========================================================
        const targetValue = currentBalance + activeTarget;
        
        // 1. Tính gia tốc tăng trưởng cần thiết cho mỗi nến trong tương lai (futureN)
        // Công thức: Rate = (Target / Balance) ^ (1 / N) - 1
        const velocityRate = Math.pow(targetValue / currentBalance, 1 / futureN) - 1;
        
        const velocityCurve = Array(pastN).fill(null); // Quá khứ để trống (null)
        velocityCurve.push(currentBalance); // Bắt đầu uốn cong từ điểm NOW▼
        
        let dynamicEquity = currentBalance;
        for (let t = 1; t <= futureN; t++) {
            // Vốn nảy nở theo gia tốc kép (Compounding Velocity)
            dynamicEquity = dynamicEquity * (1 + velocityRate);
            velocityCurve.push(dynamicEquity);
        }

        // 2. Vẽ quỹ đạo Động năng cong vút (Màu Tím Lượng Tử)
        datasets.push({ 
            label: 'VELOCITY PATH', 
            data: velocityCurve, 
            borderColor: COLORS.purple, 
            borderWidth: 2.5, 
            borderDash: [4, 2], 
            tension: 0.4, // Tạo độ lơi mượt mà cho đường cong
            pointRadius: 0, 
            fill: false 
        });

        // 3. Vẫn giữ lại vạch đích nằm ngang mờ mờ để dễ ngắm
        datasets.push({ 
            data: Array(pastN + 1 + futureN).fill(targetValue), 
            borderColor: `${COLORS.green}44`, 
            borderDash: [2, 4], 
            borderWidth: 1, 
            pointRadius: 0, 
            fill: false 
        });
        datasets.push({ data: Array(pastN + 1 + futureN).fill(hardFloorVal), borderColor: `${COLORS.red}88`, borderDash: [2, 2], borderWidth: 1.5, pointRadius: 0, fill: false });

        contInst.current = new Chart(contRef.current.getContext('2d'), {
            type: 'line', data: { labels, datasets },
            options: {
                animation: { duration: 400, easing: 'easeOutQuart' }, responsive: true, maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: { legend: { display: false }, tooltip: { filter: item => item.dataset.label !== undefined } },
                scales: {
                    x: {
                        grid: { color: ctx => ctx.index === pastN ? `${COLORS.yellow}88` : '#0f0f0f' },
                        ticks: { color: ctx => ctx.index === pastN ? COLORS.yellow : '#444', maxRotation: 0 }
                    },
                    y: { grid: { color: '#111' }, ticks: { color: '#555', callback: v => '$' + v.toLocaleString() } }
                }
            }
        });
        return () => { if (contInst.current) { contInst.current.destroy(); contInst.current = null; } };
    }, [continuumTf, expectedWR, expectedRR, activeTarget, chartBudget, currentBalance, hardFloorVal, activeRightTab, COLORS, sessions, gibbsEnergy]);

    // ── STYLES ────────────────────────────────────────────────
    const inputStyle = `width:100%; background:#05070a; border:1px solid #222; color:${COLORS.cyan}; padding:10px 12px; outline:none; font-family:monospace; font-size:15px; font-weight:bold; box-sizing:border-box; transition:0.3s; margin-top:4px; border-radius:3px;`;
    const selectStyle = inputStyle;
    const tabBtn = (id) => `padding:5px 8px; border:none; border-bottom:2px solid ${activeRightTab === id ? COLORS.cyan : 'transparent'}; background:transparent; color:${activeRightTab === id ? COLORS.cyan : '#444'}; font-size:9px; font-weight:900; letter-spacing:0.2px; cursor:pointer; transition:0.2s; white-space:nowrap; flex-shrink:0;`;
    const tfBtn = (tf) => `background:${continuumTf === tf ? COLORS.cyan : 'transparent'}; color:${continuumTf === tf ? '#000' : '#555'}; border:none; padding:4px 9px; font-size:9px; font-weight:bold; border-radius:2px; cursor:pointer;`;

    const topColor = isArmed ? COLORS.green : COLORS.red;

    // ── RENDER ────────────────────────────────────────────────
    return html`
    <div style="position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.96);display:flex;align-items:center;justify-content:center;z-index:10000;backdrop-filter:blur(10px);">
    <div style="background:#080a0f;border:1px solid ${topColor}44;width:98vw;max-width:1800px;height:95vh;display:flex;flex-direction:column;border-radius:4px;box-shadow:0 0 80px ${topColor}18;overflow:hidden;">

        <div style="display:flex;justify-content:space-between;align-items:center;padding:13px 22px;background:#020305;border-bottom:1px solid #1a1a1a;flex-shrink:0;position:relative;z-index:10001;">
            <div style="font-size:19px;color:${COLORS.cyan};font-weight:900;letter-spacing:2px;">🚀 WAR ROOM — MACRO STRATEGY BUILDER</div>
            <div style="display:flex;align-items:center;gap:20px;">
                ${dna ? html`
                    <div style="display:flex;align-items:center;gap:6px;background:#0a0c10;border:1px solid #1a1a1a;padding:6px 14px;border-radius:3px;">
                        <span style="font-size:9px;color:#555;font-weight:bold;">DNA SCORE</span>
                        <span style="font-size:18px;color:${dna.overall >= 75 ? COLORS.green : dna.overall >= 50 ? COLORS.yellow : COLORS.red};font-weight:900;font-family:monospace;">${dna.overall}</span>
                        <span style="font-size:9px;color:#333;">/100</span>
                    </div>
                ` : null}

                <button onClick=${onClose} style="background:none;border:none;color:#ccc;font-size:20px;cursor:pointer;line-height:1;padding:5px 12px;border-radius:3px;border:1px solid #333;background:#0a0a0a;position:relative;z-index:10002;">×</button>
            </div>
        </div>

        <div style="padding:10px 22px;background:${topColor}08;border-bottom:1px solid ${topColor}22;flex-shrink:0;display:flex;align-items:center;justify-content:space-between;">
            <div>
                <span style="color:${topColor};font-weight:900;font-size:13px;letter-spacing:1px;">${isArmed ? '🟢 ARMED — LỜI THỀ ĐÃ ĐƯỢC KHÓA CỨNG' : '🔴 DISARMED — CẦN THIẾT LẬP KẾ HOẠCH'}</span>
                <span style="color:#555;font-size:10px;margin-left:15px;">${isArmed ? 'AI đang áp đặt kỷ luật đến kỳ Rollover tiếp theo.' : 'Hoàn thành Bản vẽ Toán học để Tòa án AI cấp phép giao dịch.'}</span>
            </div>
            ${isArmed ? html`
                <div style="display:flex;gap:20px;font-family:monospace;font-size:11px;">
                    <span style="color:#555;">TARGET: <span style="color:${COLORS.cyan};font-weight:bold;">$${riskParams.target_profit}</span></span>
                    <span style="color:#555;">WR: <span style="color:${COLORS.cyan};font-weight:bold;">${neural.historical_win_rate}%</span></span>
                    <span style="color:#555;">R:R: <span style="color:${COLORS.cyan};font-weight:bold;">1:${neural.historical_rr}</span></span>
                    <span style="color:#555;">BUDGET: <span style="color:${COLORS.green};font-weight:bold;">$${isArmed ? armedBudget : riskParams.daily_limit_money}/DAY</span></span>
                    <span style="color:#555;">DD: <span style="color:${riskParams.dd_type === 'TRAILING' ? COLORS.red : '#888'};font-weight:bold;">${riskParams.dd_type || 'STATIC'} ${riskParams.max_dd || 10}%</span></span>
                    <span style="color:#555;">LOCK: <span style="color:${COLORS.yellow};font-weight:bold;">${riskParams.profit_lock_pct || 40}%</span></span>
                </div>
            ` : null}

        </div>

        <div style="display:grid;grid-template-columns:400px 1fr;gap:0;flex:1;overflow:hidden;">

            <div style="display:flex;flex-direction:column;gap:0;border-right:1px solid #1a1a1a;overflow-y:auto;position:relative;">

                ${isArmed ? html`
                    <!-- BUG H FIX: Overlay compact — KHÔNG che Zone A (Sandbox) -->
                    <!-- Chỉ hiển thị summary + thông báo Zone B bị lock -->
                    <!-- Zone A (WR, RR, Target, Timeframe) vẫn chỉnh được bên dưới -->
                    <div style="position:sticky;top:0;left:0;width:100%;z-index:10;background:#05070a;border-bottom:1px solid ${COLORS.green}33;padding:10px 14px;display:flex;align-items:center;justify-content:space-between;gap:10px;">
                        <div style="display:flex;align-items:center;gap:10px;flex:1;">
                            <div style="font-size:20px;">🔒</div>
                            <div>
                                <div style="color:${COLORS.green};font-weight:900;font-size:11px;letter-spacing:1px;">CONTRACT LOCKED</div>
                                <div style="color:#333;font-size:8px;margin-top:2px;">Budget & Profit Lock đến Rollover · Sandbox vẫn chỉnh được</div>
                            </div>
                        </div>
                        <div style="display:flex;align-items:center;gap:10px;flex-shrink:0;">
                            <div style="font-family:monospace;font-size:10px;color:#555;text-align:right;line-height:1.8;">
                                <div>💰 <span style="color:${COLORS.green};">$${armedBudget || dailyBudget}</span>/ngày</div>
                                <div>🛡 Lock <span style="color:${COLORS.yellow};">${riskParams.profit_lock_pct || profitLockPct}%</span></div>
                            </div>
                            <!-- ADMIN OVERRIDE: mở khóa để chỉnh lại thông số -->
                            <button
                                onClick=${handleAdminOverride}
                                title="Admin: Mở khóa Contract để chỉnh lại Budget/Lock"
                                style="background:#1a0a00;border:1px solid ${COLORS.yellow}44;color:${COLORS.yellow};padding:6px 10px;font-size:9px;font-weight:bold;cursor:pointer;border-radius:3px;white-space:nowrap;letter-spacing:0.5px;transition:0.2s;"
                                onMouseEnter=${e => e.currentTarget.style.background = COLORS.yellow + '18'}
                                onMouseLeave=${e => e.currentTarget.style.background = '#1a0a00'}>
                                🔓 OVERRIDE
                            </button>
                        </div>
                    </div>
                ` : null}


                <!-- ══ [0] DAILY BUDGET — Zone B (Contract) — lock sau ARM ══ -->
                <div style="padding:18px;border-bottom:1px solid #111;background:#05070a;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                        <div style="font-size:11px;color:${COLORS.yellow};font-weight:900;letter-spacing:1px;">[0] DAILY BUDGET — NGÂN SÁCH TÁC CHIẾN</div>
                        ${contractLocked ? html`<div style="font-size:8px;color:${COLORS.green};padding:2px 8px;border:1px solid ${COLORS.green}44;border-radius:2px;">🔒 CONTRACT</div>` : null}
                    </div>
                    <div style="font-size:9px;color:#444;font-style:italic;margin-bottom:12px;line-height:1.5;">
                        Số tiền tối đa cho phép risk mỗi ngày. Được tính bởi AI Validator (mục [3]) hoặc nhập thủ công.<br/>
                        <span style="color:#2a2a2a;">Khác với Max Daily DD% ở Hiến Pháp — đó là rào cản vật lý, đây là kế hoạch chiến thuật.</span>
                    </div>

                    <!-- Hiến Pháp reference (chỉ đọc) -->
                    <div style="background:#080a0f;border:1px dashed #1a1a1a;border-left:3px solid ${COLORS.red}55;padding:8px 12px;border-radius:3px;margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;">
                        <div>
                            <div style="font-size:8px;color:#333;font-weight:bold;letter-spacing:0.5px;">⚔️ HIẾN PHÁP (từ SetupModal — chỉ đọc)</div>
                            <div style="font-size:9px;color:${COLORS.red}88;font-family:monospace;margin-top:2px;">
                                Max Daily DD: <span style="color:${COLORS.red};font-weight:bold;">${constitutionMaxDailyDdPct}%</span>
                                <span style="color:#333;margin:0 6px;">=</span>
                                <span style="color:${COLORS.red};font-weight:bold;">$${constitutionMaxDailyDd$.toLocaleString('en-US',{maximumFractionDigits:0})}</span>
                                <span style="font-size:8px;color:#2a2a2a;"> / ngày tại balance hiện tại</span>
                            </div>
                        </div>
                        <div style="font-size:8px;color:#1a1a1a;text-align:right;">Budget phải<br/>≤ Hard Floor</div>
                    </div>

                    <!-- ── 3-SOURCE BUDGET SELECTOR ─────────────────────── -->
                    <!-- Tab chọn nguồn: % Hiến Pháp | AI Validator | Tự điền -->
                    <div style="display:flex;gap:4px;margin-bottom:10px;">
                        ${[
                            { key: 'pct',    icon: '⚖️', label: '% Hiến Pháp' },
                            { key: 'ai',     icon: '🤖', label: 'AI Validator' },
                            { key: 'manual', icon: '✏️', label: 'Tự điền'      },
                        ].map(({ key, icon, label }) => {
                            const active = budgetMode === key;
                            const disabled = contractLocked || (key === 'ai' && !aiReport);
                            return html`<button
                                onClick=${() => {
                                    if (contractLocked) return;
                                    if (key === 'ai' && !aiReport) return;
                                                    setBudgetMode(key);
                                    if (key === 'ai' && aiReport) {
                                        setDailyBudget(aiReport.suggestedDaily);
                                    } else if (key === 'pct') {
                                        // Auto-apply 50% nếu giá trị hiện tại không khớp bất kỳ card nào
                                        const pctOptions = [0.25, 0.5, 0.75, 1.0].map(p => Math.round(constitutionMaxDailyDd$ * p));
                                        if (!pctOptions.includes(dailyBudget)) {
                                            setDailyBudget(Math.round(constitutionMaxDailyDd$ * 0.5));
                                        }
                                    }
                                }}
                                disabled=${disabled}
                                title=${key === 'ai' && !aiReport ? 'Cần chạy AI Validator [3] trước' : ''}
                                style="flex:1;padding:6px 4px;background:${active ? COLORS.yellow + '22' : '#0a0c10'};border:1px solid ${active ? COLORS.yellow : (disabled ? '#111' : '#222')};color:${disabled ? '#2a2a2a' : (active ? COLORS.yellow : '#555')};font-size:8px;font-weight:${active ? 'bold' : 'normal'};cursor:${disabled ? 'not-allowed' : 'pointer'};border-radius:3px;transition:0.15s;letter-spacing:0.3px;">
                                ${icon}<br/>${label}
                            </button>`;
                        })}
                    </div>

                    <!-- Nguồn 1: % Hiến Pháp — dropdown 4 mốc -->
                    ${budgetMode === 'pct' ? html`
                        <div>
                            <label style="font-size:9px;color:${contractLocked ? '#333' : COLORS.yellow};font-weight:bold;display:block;margin-bottom:6px;">CHỌN % SO VỚI MAX DAILY DD</label>
                            <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
                                ${[
                                    { pct: 0.25, label: '25% — Bảo thủ',  color: '#00bfff' },
                                    { pct: 0.50, label: '50% — Thận trọng', color: COLORS.green },
                                    { pct: 0.75, label: '75% — Tiêu chuẩn', color: COLORS.yellow },
                                    { pct: 1.00, label: '100% — Tối đa',   color: COLORS.red },
                                ].map(({ pct, label, color }) => {
                                    const val = Math.round(constitutionMaxDailyDd$ * pct);
                                    const active = Math.abs(dailyBudget - val) < 1;
                                    return html`<button
                                        onClick=${() => !contractLocked && setDailyBudget(val)}
                                        disabled=${contractLocked}
                                        style="padding:8px 10px;background:${active ? color + '22' : '#080a0f'};border:1px solid ${active ? color : '#1a1a1a'};border-radius:3px;cursor:${contractLocked ? 'not-allowed' : 'pointer'};transition:0.15s;text-align:left;">
                                        <div style="font-size:8px;color:${active ? color : '#444'};">${label}</div>
                                        <div style="font-family:monospace;font-size:13px;font-weight:bold;color:${active ? color : '#666'};margin-top:2px;">$${val.toLocaleString()}</div>
                                        <div style="font-size:7px;color:${active ? color + 'aa' : '#2a2a2a'};margin-top:1px;">${Math.round(pct * 100)}% × $${Math.round(constitutionMaxDailyDd$)}</div>
                                    </button>`;
                                })}
                            </div>
                        </div>
                    ` : null}


                    <!-- Nguồn 2: AI Validator -->
                    ${budgetMode === 'ai' ? html`
                        <div style="background:#08100a;border:1px solid ${COLORS.green}33;border-radius:3px;padding:12px;">
                            ${aiReport ? html`
                                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                                    <div>
                                        <div style="font-size:8px;color:#555;font-weight:bold;margin-bottom:2px;">🤖 AI ĐỀ XUẤT (Kelly ${aiReport.kelly}%)</div>
                                        <div style="font-family:monospace;font-size:22px;font-weight:900;color:${aiReport.edgeStatus === 'POSITIVE' ? COLORS.green : COLORS.yellow};">
                                            $${aiReport.suggestedDaily.toLocaleString()}
                                        </div>
                                        <div style="font-size:8px;color:#444;margin-top:2px;">= ${((aiReport.suggestedDaily / constitutionMaxDailyDd$) * 100).toFixed(0)}% Max Daily DD</div>
                                    </div>
                                    <div style="text-align:right;">
                                        <div style="font-size:9px;padding:3px 8px;border-radius:2px;font-weight:bold;background:${aiReport.edgeStatus === 'POSITIVE' ? COLORS.green + '22' : COLORS.yellow + '22'};color:${aiReport.edgeStatus === 'POSITIVE' ? COLORS.green : COLORS.yellow};">
                                            ${aiReport.edgeStatus}
                                        </div>
                                        <div style="font-size:7px;color:#333;margin-top:4px;">Chạy lại [3] để cập nhật</div>
                                    </div>
                                </div>
                                <div style="font-size:8px;color:#2a4030;font-style:italic;border-top:1px dashed #0f1f14;padding-top:6px;">${aiReport.message}</div>
                            ` : html`
                                <div style="text-align:center;padding:12px 0;">
                                    <div style="font-size:24px;margin-bottom:6px;">🤖</div>
                                    <div style="font-size:9px;color:#333;">Chưa có kết quả AI</div>
                                    <div style="font-size:8px;color:#222;margin-top:4px;">Điền [1] Mục tiêu + [2] WR/RR rồi bấm<br/><b style="color:#444;">[3] PHÂN TÍCH AI</b> để lấy đề xuất</div>
                                </div>
                            `}
                        </div>
                    ` : null}


                    <!-- Nguồn 3: Tự điền -->
                    ${budgetMode === 'manual' ? html`
                        <div>
                            <label style="font-size:9px;color:${contractLocked ? '#333' : COLORS.yellow};font-weight:bold;display:block;margin-bottom:4px;">NHẬP THỦ CÔNG ($)</label>
                            <div style="position:relative;">
                                <input type="number"
                                    style="width:100%;background:${contractLocked ? '#080a0f' : '#0a0c10'};border:1px solid ${contractLocked ? '#1a1a1a' : (dailyBudget > constitutionMaxDailyDd$ ? COLORS.red + '88' : COLORS.yellow + '44')};color:${contractLocked ? '#2a2a2a' : (dailyBudget > constitutionMaxDailyDd$ ? COLORS.red : COLORS.yellow)};padding:9px 48px 9px 11px;outline:none;font-family:monospace;font-size:16px;box-sizing:border-box;border-radius:3px;font-weight:bold;cursor:${contractLocked ? 'not-allowed' : 'text'};"
                                    value=${dailyBudget}
                                    onInput=${e => !contractLocked && setDailyBudget(Number(e.target.value))}
                                    disabled=${contractLocked}
                                    min="1" step="5" />
                                <div style="position:absolute;right:10px;top:50%;transform:translateY(-50%);font-size:9px;color:#555;pointer-events:none;">${contractLocked ? '🔒' : '/ngày'}</div>
                            </div>
                            <!-- Quick fill từ % -->
                            <div style="display:flex;gap:4px;margin-top:6px;">
                                ${[0.25, 0.5, 0.75, 1.0].map(p => {
                                    const v = Math.round(constitutionMaxDailyDd$ * p);
                                    return html`<button
                                        onClick=${() => !contractLocked && setDailyBudget(v)}
                                        disabled=${contractLocked}
                                        style="flex:1;padding:4px 2px;background:#0a0c10;border:1px solid #1a1a1a;color:#444;font-size:8px;font-family:monospace;cursor:${contractLocked ? 'not-allowed' : 'pointer'};border-radius:2px;">
                                        ${Math.round(p*100)}%
                                    </button>`;
                                })}
                            </div>
                        </div>
                    ` : null}


                    <!-- Giá trị hiện tại + validation -->
                    <div style="margin-top:10px;padding:8px 10px;background:#080a0f;border:1px solid ${dailyBudget > constitutionMaxDailyDd$ ? COLORS.red + '44' : '#111'};border-radius:3px;display:flex;justify-content:space-between;align-items:center;">
                        <div>
                            <div style="font-size:8px;color:#333;">NGÂN SÁCH ĐÃ CHỌN</div>
                            <div style="font-family:monospace;font-size:15px;font-weight:bold;color:${dailyBudget > constitutionMaxDailyDd$ ? COLORS.red : COLORS.yellow};">$${(dailyBudget||0).toLocaleString()}<span style="font-size:9px;color:#444;">/ngày</span></div>
                        </div>
                        <div style="text-align:right;font-size:8px;">
                            ${dailyBudget > constitutionMaxDailyDd$ ? html`
                                <div style="color:${COLORS.red};font-weight:bold;">⛔ VƯỢT HIẾN PHÁP</div>
                                <div style="color:#333;">${dailyBudget} > ${Math.round(constitutionMaxDailyDd$)}</div>
                            ` : html`
                                <div style="color:#444;">= ${constitutionMaxDailyDd$ > 0 ? ((dailyBudget / constitutionMaxDailyDd$) * 100).toFixed(0) : 0}% Max DD</div>
                                <div style="color:${dailyBudget / constitutionMaxDailyDd$ > 0.85 ? COLORS.yellow : '#2a2a2a'};">${dailyBudget / constitutionMaxDailyDd$ > 0.85 ? '⚠️ Sát giới hạn' : '✓ Hợp lệ'}</div>
                            `}
                        </div>
                    </div>
                </div>

                <!-- ══ [1] NHIỆM VỤ TÁC CHIẾN — Zone A Sandbox (không bao giờ lock) ══ -->
                <div style="padding:18px;border-bottom:1px solid #111;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                        <div style="font-size:11px;color:${COLORS.cyan};font-weight:900;letter-spacing:1px;">[1] NHIỆM VỤ TÁC CHIẾN — THE GOAL</div>
                        <div style="font-size:8px;color:${COLORS.cyan}55;padding:2px 8px;border:1px solid ${COLORS.cyan}22;border-radius:2px;">🧪 SANDBOX</div>
                    </div>
                    <div style="font-size:9px;color:#444;font-style:italic;margin-bottom:12px;line-height:1.5;">Định lượng chính xác số tiền muốn kiếm và thời hạn. Đích đến càng xa, Năng lượng đòi hỏi càng lớn.</div>
                    <label style="font-size:9px;color:#666;font-weight:bold;">MỤC TIÊU LỢI NHUẬN ($)</label>
                    <input type="number" style=${inputStyle} value=${targetProfit} onInput=${e => setTargetProfit(e.target.value)} />
                    <label style="font-size:9px;color:#666;font-weight:bold;display:block;margin-top:10px;">CHU KỲ BÁO CÁO</label>
                    <select style=${selectStyle} value=${timeframe} onChange=${e => setTimeframe(e.target.value)}>
                        <option value="DAY">HÔM NAY (1 Ngày)</option>
                        <option value="WEEK">TUẦN NÀY (5 Ngày)</option>
                        <option value="MONTH">THÁNG NÀY (20 Ngày)</option>
                        <option value="QUARTER">QUÝ NÀY (60 Ngày)</option>
                    </select>
                </div>

                <!-- ══ [2] HỒ SƠ NĂNG LỰC — Zone A Sandbox (không bao giờ lock) ══ -->
                <div style="padding:18px;border-bottom:1px solid #111;">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                        <div style="font-size:11px;color:${COLORS.yellow};font-weight:900;letter-spacing:1px;">[2] HỒ SƠ NĂNG LỰC — THE EDGE</div>
                        <div style="font-size:8px;color:${COLORS.cyan}55;padding:2px 8px;border:1px solid ${COLORS.cyan}22;border-radius:2px;">🧪 SANDBOX</div>
                    </div>
                    <div style="font-size:9px;color:#444;font-style:italic;margin-bottom:12px;line-height:1.5;">Khai báo trung thực. Nếu khai khống tỷ lệ thắng, bản vẽ này sẽ thành mồ chôn tài khoản.</div>
                    ${dna ? html`
                        <div style="background:#05070a;border:1px solid #1a1a1a;padding:8px 12px;border-radius:3px;margin-bottom:12px;display:flex;gap:20px;">
                            <div style="text-align:center;">
                                <div style="font-size:8px;color:#444;font-weight:bold;">WR THỰC TẾ</div>
                                <div style="font-size:16px;color:${COLORS.green};font-weight:900;font-family:monospace;">${dna.actualWR}%</div>
                                <div style="font-size:8px;color:#333;">${dna.tradeCount} lệnh</div>
                            </div>
                            <div style="text-align:center;">
                                <div style="font-size:8px;color:#444;font-weight:bold;">R:R THỰC TẾ</div>
                                <div style="font-size:16px;color:${COLORS.green};font-weight:900;font-family:monospace;">${dna.avgRR}</div>
                                <div style="font-size:8px;color:#333;">${dna.sessionCount} phiên</div>
                            </div>
                        </div>
                    ` : null}

                    <label style="font-size:9px;color:#666;font-weight:bold;">WIN RATE THỰC TẾ (%)</label>
                    <input type="number" style=${inputStyle} value=${expectedWR} onInput=${e => setExpectedWR(e.target.value)} min="1" max="99" />
                    <label style="font-size:9px;color:#666;font-weight:bold;display:block;margin-top:10px;">TỶ LỆ R:R</label>
                    <input type="number" style=${inputStyle} value=${expectedRR} onInput=${e => setExpectedRR(e.target.value)} step="0.1" min="0.1" />
                </div>

                <!-- ══ [4] RISK SHIELD — PHÒNG THỦ 2 TẦNG ══ -->
                <div style="padding:18px;border-bottom:1px solid #111;">
                    <div style="font-size:11px;color:${COLORS.red};font-weight:900;letter-spacing:1px;margin-bottom:4px;">
                        [4] RISK SHIELD — PHÒNG THỦ 2 TẦNG
                    </div>
                    <div style="font-size:9px;color:#444;font-style:italic;margin-bottom:14px;line-height:1.5;">
                        Tầng 1 (Bức tường Thép) bảo vệ vốn tổng — không bao giờ reset.<br/>
                        Tầng 2 (Van Điều Áp) bảo vệ lợi nhuận ngày — reset theo Rollover.
                    </div>

                    <!-- BUG H FIX: Tầng 1 — READONLY display, owner là SetupModal -->
                    <!-- Xóa input maxDdPct + select ddType — không còn là state của MacroModal -->
                    <div style="background:#05070a;border:1px solid #1a1a1a;border-left:3px solid ${COLORS.red};padding:13px;border-radius:3px;margin-bottom:12px;">
                        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                            <div style="font-size:9px;color:${COLORS.red};font-weight:900;letter-spacing:1px;">🔴 TẦNG 1 — ACCOUNT HARD LIMIT</div>
                            <div style="display:flex;gap:6px;align-items:center;">
                                <div style="font-size:8px;padding:2px 8px;border-radius:2px;
                                    background:${ddType === 'TRAILING' ? COLORS.red + '22' : '#111'};
                                    border:1px solid ${ddType === 'TRAILING' ? COLORS.red + '88' : '#333'};
                                    color:${ddType === 'TRAILING' ? COLORS.red : '#444'};">
                                    ${ddType === 'TRAILING' ? '📉 TRAILING ACTIVE' : '🔒 STATIC MODE'}
                                </div>
                                <div style="font-size:8px;color:#1a1a1a;padding:2px 8px;border:1px dashed #1a1a1a;border-radius:2px;">SetupModal</div>
                            </div>
                        </div>

                        <!-- Readonly display — giá trị thực từ DB qua riskParams -->
                        <div style="display:flex;gap:10px;margin-bottom:10px;">
                            <div style="flex:1;background:#030406;border:1px solid #1a1a1a;padding:10px;border-radius:3px;text-align:center;">
                                <div style="font-size:8px;color:#333;font-weight:bold;margin-bottom:4px;">MAX DRAWDOWN</div>
                                <div style="font-size:20px;color:${COLORS.red};font-weight:900;font-family:monospace;">${maxDdPct}%</div>
                                <div style="font-size:7px;color:#222;margin-top:2px;">Chỉnh tại SetupModal</div>
                            </div>
                            <div style="flex:1;background:#030406;border:1px solid #1a1a1a;padding:10px;border-radius:3px;text-align:center;">
                                <div style="font-size:8px;color:#333;font-weight:bold;margin-bottom:4px;">DD MODE</div>
                                <div style="font-size:13px;color:${ddType === 'TRAILING' ? COLORS.red : '#888'};font-weight:900;font-family:monospace;">${ddType}</div>
                                <div style="font-size:7px;color:#222;margin-top:2px;">Chỉnh tại SetupModal</div>
                            </div>
                        </div>

                        <div style="margin-top:10px;padding:8px 10px;background:#030406;border-radius:2px;border:1px dashed #1a1a1a;font-size:8px;color:#555;line-height:1.9;">
                            ${ddType === 'TRAILING' ? html`
                                <div>📍 Sàn hiện tại (server): <span style="color:${COLORS.red};font-weight:bold;font-family:monospace;">
                                    $${accountHardFloor.toLocaleString('en-US',{maximumFractionDigits:0})}
                                </span></div>
                                <div>📈 Đỉnh tài khoản: <span style="color:${COLORS.yellow};font-family:monospace;">
                                    $${accountPeak.toLocaleString('en-US',{maximumFractionDigits:0})}
                                </span></div>
                                <div style="color:#333;font-style:italic;margin-top:2px;">
                                    Sàn tự nâng khi equity đạt đỉnh mới. Phù hợp prop firm challenge.
                                </div>
                            ` : html`
                                <div>📍 Sàn cố định: <span style="color:${COLORS.red};font-weight:bold;font-family:monospace;">
                                    $${(currentBalance * (1 - Number(maxDdPct)/100)).toLocaleString('en-US',{maximumFractionDigits:0})}
                                </span> = Balance × (1 − ${maxDdPct}%)</div>
                                <div style="color:#333;font-style:italic;margin-top:2px;">
                                    Phù hợp funded account tiêu chuẩn, giai đoạn đã pass challenge.
                                </div>
                            `}
                        </div>

                        <div style="margin-top:10px;">
                            <div style="display:flex;justify-content:space-between;font-size:8px;color:#555;margin-bottom:4px;">
                                <span>BUFFER ĐẾN ACCOUNT FLOOR</span>
                                <span style="color:${accountBufferPct < 30 ? COLORS.red : accountBufferPct < 60 ? COLORS.yellow : COLORS.green};font-family:monospace;">
                                    ${accountBufferPct.toFixed(1)}% còn lại
                                </span>
                            </div>
                            <div style="width:100%;height:6px;background:#111;border-radius:3px;overflow:hidden;border:1px solid #1a1a1a;">
                                <div style="width:${Math.min(100, 100 - accountBufferPct)}%;height:100%;
                                    background:${accountBufferPct < 30 ? COLORS.red : accountBufferPct < 60 ? COLORS.yellow : '#1a1a2a'};
                                    transition:width 0.5s;"></div>
                            </div>
                        </div>
                    </div>

                    <div style="background:#05070a;border:1px solid #1a1a1a;border-left:3px solid ${COLORS.yellow};padding:13px;border-radius:3px;">
                        <div style="font-size:9px;color:${COLORS.yellow};font-weight:900;letter-spacing:1px;margin-bottom:10px;">
                            🟡 TẦNG 2 — DAILY PROFIT LOCK (VAN ĐIỀU ÁP)
                        </div>

                        <label style="font-size:9px;color:${contractLocked ? '#333' : '#666'};font-weight:bold;">
                            PROFIT LOCK — % LỢI NHUẬN NGÀY ĐƯỢC PHÉP TRẢ LẠI
                            ${contractLocked ? html`<span style="color:${COLORS.green};margin-left:6px;">🔒 CONTRACT</span>` : null}
                        </label>
                        <input type="number" style="width:100%;background:${contractLocked ? '#080a0f' : '#0a0c10'};border:1px solid ${contractLocked ? '#1a1a1a' : '#333'};color:${contractLocked ? '#2a2a2a' : '#ccc'};padding:9px 11px;outline:none;font-family:monospace;font-size:13px;box-sizing:border-box;border-radius:3px;cursor:${contractLocked ? 'not-allowed' : 'text'};"
                            value=${profitLockPct}
                            onInput=${e => !contractLocked && setProfitLockPct(e.target.value)}
                            disabled=${contractLocked}
                            min="10" max="80" step="5" />

                        <div style="margin-top:10px;padding:8px 10px;background:#030406;border-radius:2px;border:1px dashed #1a1a1a;font-size:8px;color:#555;line-height:1.9;">
                            <div>🏔️ Đỉnh ngày hôm nay: <span style="color:${COLORS.cyan};font-family:monospace;">
                                $${dailyPeak.toLocaleString('en-US',{maximumFractionDigits:0})}
                            </span>${dailyProfitReached > 0 ? html` (+$${dailyProfitReached.toFixed(0)})` : ' (chưa có lợi nhuận)'}</div>
                            <div>🛡️ Giveback tối đa: <span style="color:${COLORS.yellow};font-family:monospace;">
                                $${dailyAllowedGiveback.toFixed(0)}
                            </span> (${profitLockPct}% của lợi nhuận đã đạt)</div>
                            <div style="color:#333;font-style:italic;margin-top:2px;">
                                Đây là nguồn tính D.TRAIL bar trên Z-Pressure. 100% → TURBULENT/BREACH.
                            </div>
                        </div>

                        <div style="margin-top:10px;">
                            <div style="display:flex;justify-content:space-between;font-size:8px;color:#555;margin-bottom:4px;">
                                <span>TRAIL PRESSURE HÔM NAY</span>
                                <span style="color:${dailyGivebackPct >= 85 ? COLORS.red : dailyGivebackPct >= 50 ? COLORS.yellow : COLORS.green};font-family:monospace;">
                                    ${dailyGivebackPct.toFixed(0)}%
                                </span>
                            </div>
                            <div style="width:100%;height:6px;background:#111;border-radius:3px;overflow:hidden;border:1px solid #1a1a1a;">
                                <div style="width:${Math.min(100, dailyGivebackPct)}%;height:100%;
                                    background:${dailyGivebackPct >= 85 ? COLORS.red : dailyGivebackPct >= 50 ? COLORS.yellow : COLORS.green};
                                    transition:width 0.5s;"></div>
                            </div>
                        </div>
                    </div>
                </div>

                <div style="padding:18px;border-bottom:1px solid #111;">
                    <div style="font-size:11px;color:#b565ff;font-weight:900;letter-spacing:1px;margin-bottom:4px;">[3] QUANTUM VALIDATOR — TÒA ÁN LƯỢNG TỬ</div>
                    <div style="font-size:9px;color:#444;font-style:italic;margin-bottom:12px;line-height:1.5;">AI dùng Kelly Criterion phản biện dữ liệu bạn vừa nhập. Edge âm → cấm giao dịch.</div>
                    <button onClick=${runAiSimulation} disabled=${isCalculating}
                        style="width:100%;padding:13px;background:${isCalculating ? '#111' : COLORS.cyan + '18'};border:1px dashed ${COLORS.cyan};color:${COLORS.cyan};font-size:11px;font-weight:900;cursor:${isCalculating ? 'wait' : 'pointer'};letter-spacing:1px;transition:0.3s;border-radius:3px;">
                        ${isCalculating ? '⚡ AI ĐANG TÍNH TOÁN...' : '🔍 YÊU CẦU AI THẨM ĐỊNH'}
                    </button>
                    ${aiReport ? html`
                        <div style="margin-top:14px;background:#05070a;border:1px solid ${aiReport.edgeStatus === 'POSITIVE' ? COLORS.green : aiReport.edgeStatus === 'BREAKEVEN' ? COLORS.yellow : COLORS.red}33;padding:14px;border-radius:3px;">
                            <div style="font-size:10px;font-family:monospace;color:${aiReport.edgeStatus === 'POSITIVE' ? COLORS.green : aiReport.edgeStatus === 'BREAKEVEN' ? COLORS.yellow : COLORS.red};margin-bottom:12px;line-height:1.6;">> ${aiReport.message}</div>
                            ${aiReport.edgeStatus !== 'NEGATIVE' ? html`
                                <div style="background:#0a0c10;padding:10px;border:1px dashed #222;margin-bottom:12px;border-radius:3px;">
                                    <div style="font-size:9px;color:#555;font-weight:bold;margin-bottom:6px;">AI ĐỀ XUẤT NGÂN SÁCH</div>
                                    <div style="display:flex;align-items:center;gap:10px;">
                                        <div style="text-align:center;flex:1;">
                                            <div style="color:#fff;font-size:24px;font-weight:900;font-family:monospace;">$${aiReport.suggestedDaily}</div>
                                            <div style="font-size:8px;color:#444;">Kelly: ${aiReport.kelly}%</div>
                                        </div>
                                        <button onClick=${() => { setDailyBudget(aiReport.suggestedDaily); setChartBudget(aiReport.suggestedDaily); }}
                                            style="flex:1;padding:8px;background:${COLORS.cyan}18;border:1px solid ${COLORS.cyan}55;color:${COLORS.cyan};font-size:9px;font-weight:bold;cursor:pointer;border-radius:3px;transition:0.2s;">
                                            ← ÁP DỤNG VÀO<br/>DAILY BUDGET [0]
                                        </button>
                                    </div>
                                    <div style="font-size:8px;color:#1a1a1a;margin-top:6px;font-style:italic;">Hoặc giữ nguyên giá trị đã nhập tại [0].</div>
                                </div>
                                <button onClick=${handleArmSystem} disabled=${isSaving}
                                    style="width:100%;padding:15px;background:${aiReport.edgeStatus === 'POSITIVE' ? COLORS.green : COLORS.yellow};color:#000;font-weight:900;border:none;cursor:pointer;font-size:14px;letter-spacing:1px;border-radius:3px;box-shadow:0 0 20px ${aiReport.edgeStatus === 'POSITIVE' ? COLORS.green : COLORS.yellow}44;transition:0.2s;">
                                    ${isSaving ? '⏳ ĐANG KHÓA VÀO LÕI MT5...' : aiReport.edgeStatus === 'BREAKEVEN' ? '⚠️ HIỂU RÕ RỦI RO & BẬT RADAR' : '✔ KÝ LỜI THỀ & BẬT RADAR'}
                                </button>
                                <div style="font-size:9px;color:#333;font-style:italic;margin-top:8px;text-align:center;">Lời thề sẽ trở thành Kỷ luật Thép trên MT5 đến kỳ Rollover.</div>
                            ` : html`<div style="color:${COLORS.red};text-align:center;font-weight:900;padding-top:10px;border-top:1px dashed #330000;">❌ CẤM MỞ KHÓA: KỲ VỌNG ÂM</div>`}
                        </div>
                    ` : null}

                </div>

                <div style="padding:14px;display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                    ${[
                        { label: '🔋 GIBBS ENERGY', sub: 'Năng lượng bảo vệ mốc Tử thủ', val: `$${fmt(gibbsEnergy)}`, color: gibbsEnergy > 0 ? COLORS.green : COLORS.red },
                        { label: '⚔️ TACTICAL BUDGET', sub: 'Ngân sách ngày (MacroModal)', val: `$${fmt(isArmed ? dailyBudget : chartBudget)}`, color: isArmed ? COLORS.green : '#444' },
                        { label: '🎯 SATURATION', sub: `Tiến độ $${fmt(activeTarget)} target`, val: `${saturationPct.toFixed(1)}%`, color: saturationPct >= 100 ? COLORS.green : '#00bfff', progress: saturationPct },
                        { label: '⚡ KINETIC', sub: 'Risk → Profit conversion', val: conversionRatio === Infinity ? '∞' : `1:${conversionRatio.toFixed(1)}`, color: efficiencyColor }
                    ].map(c => html`
                        <div style="background:#05070a;border:1px solid #111;border-top:2px solid ${c.color};padding:12px;border-radius:3px;">
                            <div style="font-size:9px;color:#555;font-weight:bold;margin-bottom:2px;">${c.label}</div>
                            <div style="font-size:8px;color:#333;font-style:italic;margin-bottom:6px;line-height:1.3;">${c.sub}</div>
                            <div style="font-size:20px;color:${c.color};font-weight:900;font-family:monospace;">${c.val}</div>
                            ${c.progress !== undefined ? html`
                                <div style="width:100%;height:3px;background:#111;border-radius:2px;margin-top:6px;overflow:hidden;">
                                    <div style="width:${Math.min(100, c.progress)}%;height:100%;background:${c.color};transition:width 0.5s;"></div>
                                </div>
                            ` : null}

                        </div>
                    `)}
                </div>
            </div>

            <div style="display:flex;flex-direction:column;overflow:hidden;">

                <div style="display:flex;align-items:center;gap:4px;border-bottom:1px solid #1a1a1a;background:#020305;padding:0 6px;flex-shrink:0;overflow:hidden;">
                    <div style="display:flex;overflow-x:auto;flex:1;min-width:0;scrollbar-width:none;-ms-overflow-style:none;">
                        <button style=${tabBtn('charts')} onClick=${() => setActiveRightTab('charts')}>📊 CHARTS</button>
                        <button style=${tabBtn('heatmap')} onClick=${() => setActiveRightTab('heatmap')}>🗓 PATTERN HEATMAP</button>
                        <button style=${tabBtn('dna')} onClick=${() => setActiveRightTab('dna')}>🧬 STRATEGY DNA</button>
                        <button style=${tabBtn('regime')} onClick=${() => setActiveRightTab('regime')}>⚔️ REGIME</button>
                        <button style=${tabBtn('simulation')} onClick=${() => setActiveRightTab('simulation')}>🔬 SIMULATION</button>
                        <button style=${tabBtn('stress')} onClick=${() => setActiveRightTab('stress')}>📐 STRESS TEST</button>
                    </div>
                    ${activeRightTab === 'charts' ? html`
                        <div style="display:flex;gap:2px;background:#0a0c10;padding:3px;border-radius:3px;border:1px solid #1a1a1a;">
                            ${Object.keys(tfConfig).map(tf => html`
                                <button onClick=${() => setContinuumTf(tf)} style=${tfBtn(tf)}>${tf}</button>
                            `)}
                        </div>
                    ` : null}

                </div>

                ${activeRightTab === 'charts' ? html`
                    <div style="display:flex;flex-direction:column;gap:0;flex:1;padding:16px;gap:14px;overflow-y:auto;">

                        <div style="display:flex;gap:14px;height:280px;flex-shrink:0;">
                            <div style="flex:1;background:#05070a;border:1px solid #111;border-radius:3px;padding:12px;display:flex;flex-direction:column;">
                                <div style="font-size:10px;color:#888;font-weight:bold;letter-spacing:1px;margin-bottom:4px;">[A] MA TRẬN KỲ VỌNG</div>
                                <div style="font-size:8px;color:#333;font-style:italic;margin-bottom:8px;">Edge phải nằm trên đường breakeven. Vùng đỏ = tự sát. Chấm nhỏ = lịch sử sessions.</div>
                                <div style="flex:1;position:relative;"><canvas ref=${matrixRef}></canvas></div>
                            </div>
                            <div style="flex:2;background:#05070a;border:1px solid #111;border-radius:3px;padding:12px;display:flex;flex-direction:column;">
                                <div style="font-size:10px;color:#888;font-weight:bold;letter-spacing:1px;margin-bottom:4px;">[B] NÓN MONTE CARLO (10 kịch bản)</div>
                                <div style="font-size:8px;color:#333;font-style:italic;margin-bottom:8px;">Phóng chiếu 10 tương lai từ WinRate & R:R. Rủi ro đâm thủng ☠️ trước khi chạm 🎯.</div>
                                <div style="flex:1;position:relative;"><canvas ref=${monteRef}></canvas></div>
                            </div>
                        </div>

                        <div style="flex:1;min-height:260px;background:#05070a;border:1px solid #111;border-radius:3px;padding:12px;display:flex;flex-direction:column;">
                            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                                <div style="font-size:10px;color:${COLORS.cyan};font-weight:bold;letter-spacing:1px;">[C] THE CONTINUUM — DÒNG THỜI GIAN</div>
                                <div style="display:flex;gap:10px;font-size:8px;">
                                    <span style="color:${COLORS.cyan};">─── Quá khứ (thực tế)</span>
                                    <span style="color:${COLORS.cyan}44;">─── Monte Carlo</span>
                                    <span style="color:${COLORS.green}88;">- - AI Best Path</span>
                                </div>
                            </div>
                            <div style="font-size:8px;color:#333;font-style:italic;margin-bottom:8px;">Đường vàng NOW▼ phân chia Quá khứ | Tương lai. ${sessions.length >= 3 ? `Dùng ${Math.min(sessions.length, tfConfig[continuumTf].past)} phiên thực tế.` : 'Chưa đủ dữ liệu — dùng mô phỏng.'}</div>
                            <div style="flex:1;position:relative;"><canvas ref=${contRef}></canvas></div>
                        </div>
                    </div>
                ` : null}


                ${activeRightTab === 'heatmap' ? html`
                    <div style="flex:1;padding:20px;overflow-y:auto;">
                        <div style="font-size:11px;color:#888;font-weight:bold;letter-spacing:1px;margin-bottom:6px;">🗓 TRADE PATTERN HEATMAP — GIỜ × NGÀY</div>
                        <div style="font-size:9px;color:#444;font-style:italic;margin-bottom:20px;">WinRate theo từng giờ và từng ngày. Đỏ = giờ nguy hiểm, Xanh = giờ vàng. Tránh giao dịch trong vùng đỏ đậm.</div>
                        ${trades.length < 5 ? html`
                            <div style="text-align:center;padding:60px 20px;color:#333;border:1px dashed #1a1a1a;border-radius:4px;">
                                <div style="font-size:32px;margin-bottom:10px;">📊</div>
                                Cần tối thiểu 5 lệnh để vẽ heatmap.<br/>
                                <span style="color:#222;">Hiện có: ${trades.length} lệnh</span>
                            </div>
                        ` : html`
                            <div style="overflow-x:auto;">
                                <table style="border-collapse:collapse;font-size:9px;width:100%;">
                                    <thead>
                                        <tr>
                                            <th style="padding:4px 8px;color:#444;text-align:left;min-width:30px;"></th>
                                            ${Array.from({length:24},(_,h)=>html`<th style="padding:3px 2px;color:#333;text-align:center;min-width:28px;">${h}</th>`)}
                                        </tr>
                                    </thead>
                                    <tbody>
                                        ${DAY_LABELS.map((day, d) => html`
                                            <tr>
                                                <td style="padding:4px 8px;color:#555;font-weight:bold;">${day}</td>
                                                ${Array.from({length:24},(_,h) => {
                                                    const cell = heatmap[`${d}_${h}`];
                                                    const wr = cell ? cell.wins / cell.total : null;
                                                    const bg = wr === null ? '#0a0c10' : wr >= 0.65 ? `${COLORS.green}55` : wr >= 0.45 ? '#1a1a1a' : `${COLORS.red}44`;
                                                    const tc = wr === null ? '#1a1a1a' : wr >= 0.65 ? COLORS.green : wr >= 0.45 ? '#555' : COLORS.red;
                                                    return html`
                                                        <td title="${cell ? `${cell.wins}W/${cell.total}T = ${(wr*100).toFixed(0)}%` : 'Không có dữ liệu'}"
                                                            style="background:${bg};color:${tc};text-align:center;padding:5px 2px;font-weight:bold;font-size:8px;border:1px solid #0a0c10;cursor:default;">
                                                            ${cell ? `${Math.round(wr * 100)}` : ''}
                                                        </td>
                                                    `;
                                                })}
                                            </tr>
                                        `)}
                                    </tbody>
                                </table>
                            </div>
                            <div style="display:flex;gap:16px;margin-top:16px;justify-content:center;">
                                <span style="font-size:9px;color:${COLORS.green};">■ ≥65% Giờ vàng</span>
                                <span style="font-size:9px;color:#555;">■ 45-64% Trung lập</span>
                                <span style="font-size:9px;color:${COLORS.red};">■ <45% Nguy hiểm</span>
                                <span style="font-size:9px;color:#222;">■ Chưa có dữ liệu</span>
                            </div>
                            <div style="margin-top:20px;padding:14px;background:#05070a;border:1px solid #1a1a1a;border-radius:3px;">
                                <div style="font-size:9px;color:#888;font-weight:bold;margin-bottom:10px;">🏆 GIỜ VÀNG (WR ≥ 65%)</div>
                                <div style="display:flex;flex-wrap:wrap;gap:6px;">
                                    ${Object.entries(heatmap)
                                        .filter(([,v]) => v.total >= 2 && v.wins/v.total >= 0.65)
                                        .sort(([,a],[,b]) => b.wins/b.total - a.wins/a.total)
                                        .slice(0,8)
                                        .map(([k,v]) => {
                                            const [d,h] = k.split('_').map(Number);
                                            return html`<span style="background:${COLORS.green}22;border:1px solid ${COLORS.green}44;color:${COLORS.green};padding:4px 8px;border-radius:3px;font-size:9px;font-weight:bold;">${DAY_LABELS[d]} ${h}h — ${(v.wins/v.total*100).toFixed(0)}%</span>`;
                                        })
                                    }
                                    ${Object.entries(heatmap).filter(([,v]) => v.total >= 2 && v.wins/v.total >= 0.65).length === 0 ? html`<span style="color:#333;font-size:9px;font-style:italic;">Chưa đủ mẫu để xác định giờ vàng</span>` : null}
                                </div>
                            </div>
                        `}
                    </div>
                ` : null}


                ${activeRightTab === 'dna' ? html`
                    <div style="flex:1;padding:20px;overflow-y:auto;">
                        <div style="font-size:11px;color:#888;font-weight:bold;letter-spacing:1px;margin-bottom:6px;">🧬 STRATEGY DNA FINGERPRINT</div>
                        <div style="font-size:9px;color:#444;font-style:italic;margin-bottom:20px;">Hồ sơ năng lực thực tế từ ${sessions.length} phiên / ${trades.length} lệnh đã lưu. Đây là căn cứ để AI Guard điều chỉnh Constitution.</div>

                        ${!dna ? html`
                            <div style="text-align:center;padding:60px 20px;color:#333;border:1px dashed #1a1a1a;border-radius:4px;">
                                <div style="font-size:32px;margin-bottom:10px;">🌱</div>
                                AI chưa có dữ liệu phân tích.<br/>
                                <span style="color:#222;">Bắt đầu giao dịch và hệ thống sẽ tự học.</span>
                            </div>
                        ` : html`
                            <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
                                <div style="background:#05070a;border:1px solid #1a1a1a;border-radius:4px;padding:20px;text-align:center;grid-row:span 2;">
                                    <div style="font-size:10px;color:#555;font-weight:bold;margin-bottom:10px;">OVERALL DNA SCORE</div>
                                    <div style="font-size:64px;color:${dna.overall >= 75 ? COLORS.green : dna.overall >= 50 ? COLORS.yellow : COLORS.red};font-weight:900;font-family:monospace;line-height:1;">${dna.overall}</div>
                                    <div style="font-size:11px;color:#333;margin:4px 0 16px;">/100</div>
                                    <div style="font-size:9px;color:#444;margin-bottom:20px;">${dna.sessionCount} phiên · ${dna.tradeCount} lệnh</div>
                                    ${[
                                        { label: 'CONSISTENCY', val: dna.consistency, color: COLORS.cyan },
                                        { label: 'DISCIPLINE', val: dna.discipline, color: COLORS.purple },
                                        { label: 'TIMING', val: dna.timing, color: COLORS.yellow },
                                        { label: 'RECOVERY', val: dna.recovery, color: COLORS.green },
                                        { label: 'EDGE STRENGTH', val: dna.edgeStrength, color: '#00bfff' },
                                        { label: 'RISK CONTROL', val: dna.riskControl, color: COLORS.red },
                                    ].map(d => html`
                                        <div style="margin-bottom:10px;text-align:left;">
                                            <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
                                                <span style="font-size:8px;color:#555;font-weight:bold;">${d.label}</span>
                                                <span style="font-size:8px;color:${d.color};font-weight:bold;">${Math.round(d.val)}</span>
                                            </div>
                                            <div style="width:100%;height:4px;background:#111;border-radius:2px;overflow:hidden;">
                                                <div style="width:${d.val}%;height:100%;background:${d.color};border-radius:2px;transition:width 1s;"></div>
                                            </div>
                                        </div>
                                    `)}
                                </div>
                                <div style="background:#05070a;border:1px solid #1a1a1a;border-radius:4px;padding:16px;">
                                    <div style="font-size:9px;color:#555;font-weight:bold;margin-bottom:10px;">THỐNG KÊ THỰC TẾ</div>
                                    ${[
                                        { l: 'Win Rate Thực', v: `${dna.actualWR}%`, c: parseFloat(dna.actualWR) >= (neural.historical_win_rate || 55) ? COLORS.green : COLORS.red },
                                        { l: 'R:R Thực Tế', v: dna.avgRR, c: parseFloat(dna.avgRR) >= (neural.historical_rr || 2) * 0.85 ? COLORS.green : COLORS.red },
                                        { l: 'Tổng Phiên', v: dna.sessionCount, c: '#fff' },
                                        { l: 'Tổng Lệnh', v: dna.tradeCount, c: '#fff' },
                                    ].map(item => html`
                                        <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #0f0f0f;">
                                            <span style="font-size:9px;color:#444;">${item.l}</span>
                                            <span style="font-size:10px;color:${item.c};font-weight:bold;font-family:monospace;">${item.v}</span>
                                        </div>
                                    `)}
                                </div>
                                <div style="background:#05070a;border:1px solid #1a1a1a;border-radius:4px;padding:16px;">
                                    <div style="font-size:9px;color:#555;font-weight:bold;margin-bottom:10px;">5 PHIÊN GẦN NHẤT</div>
                                    ${sessions.slice(-5).reverse().map(s => html`
                                        <div style="display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid #0f0f0f;">
                                            <span style="font-size:8px;color:#444;">${s.date || '—'}</span>
                                            <div style="display:flex;gap:8px;align-items:center;">
                                                <span style="font-size:8px;color:${s.compliance_score >= 80 ? COLORS.green : COLORS.yellow};">${s.compliance_score || 0}%</span>
                                                <span style="font-size:9px;color:${s.pnl >= 0 ? COLORS.green : COLORS.red};font-weight:bold;font-family:monospace;">${s.pnl >= 0 ? '+' : ''}$${(s.pnl || 0).toFixed(0)}</span>
                                            </div>
                                        </div>
                                    `)}
                                </div>
                            </div>
                        `}
                    </div>
                ` : null}


                ${activeRightTab === 'regime' ? html`
                    ${StrategyRegimeZone({ z: physics.z_pressure || 0, state: physics.state, marginPct: physics.fre_pct || 0, dbuPct: physics.dbu_pct || 0, COLORS })}
                ` : null}


                ${activeRightTab === 'simulation' ? html`
                    ${SimulationZone({
                        snapshot: {
                            equity:       globalStatus?.equity || currentBalance,
                            dailyBudget:  chartBudget,
                            accountFloor: hardFloorVal,
                            z:            physics.z_pressure || 0,
                            state:        physics.state || 'OPTIMAL_FLOW',
                            marginPct:    physics.fre_pct || 0,
                            winRate:      expectedWR,
                            rr:           expectedRR,
                            wLoss:    (physics.adaptive_weights || {}).daily_loss || 0.4,
                            wGive:    (physics.adaptive_weights || {}).giveback   || 0.2,
                            wAccount: (physics.adaptive_weights || {}).account    || 0.3,
                            wMargin:  (physics.adaptive_weights || {}).margin     || 0.1,
                        },
                        COLORS
                    })}
                ` : null}


                ${activeRightTab === 'stress' ? html`
                    ${StrategyStressTestZone({
                        snapshot: {
                            equity:       globalStatus?.equity || currentBalance,
                            dailyBudget:  chartBudget,
                            accountFloor: hardFloorVal,
                            z:            physics.z_pressure || 0,
                            marginPct:    physics.fre_pct || 0,
                            wLoss:    (physics.adaptive_weights || {}).daily_loss || 0.4,
                            wGive:    (physics.adaptive_weights || {}).giveback   || 0.2,
                            wAccount: (physics.adaptive_weights || {}).account    || 0.3,
                            wMargin:  (physics.adaptive_weights || {}).margin     || 0.1,
                            giveComp: Math.min(1.0, physics.daily_trailing_pressure || 0),
                            accComp:  Math.min(1.0, (physics.account_proximity_pressure || 0) / 0.15),
                        },
                        COLORS
                    })}
                ` : null}


            </div>
        </div>
    </div>
    </div>
    `;
}