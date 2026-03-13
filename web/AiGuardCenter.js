import { h } from 'preact';
import { useState, useEffect, useMemo } from 'preact/hooks';
import htm from 'htm';

const html = htm.bind(h);

const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://127.0.0.1:8000'
    : `http://${window.location.hostname}:8000`;

// ============================================================
// AI AGENT ENGINE — Não bộ phân tích
// ============================================================
function analyzeTraderDNA(sessions = [], trades = []) {
    if (sessions.length === 0) return null;

    // 1. Compliance Score trung bình
    const avgCompliance = sessions.reduce((s, sess) => s + (sess.compliance_score || 80), 0) / sessions.length;

    // 2. WinRate thực tế
    const totalTrades = trades.length;
    const wins = trades.filter(t => t.result === 'WIN').length;
    const actualWR = totalTrades > 0 ? (wins / totalTrades) * 100 : 0;

    // 3. R:R trung bình thực tế
    const rrTrades = trades.filter(t => t.actual_rr > 0);
    const actualRR = rrTrades.length > 0 ? rrTrades.reduce((s, t) => s + t.actual_rr, 0) / rrTrades.length : 0;

    // 4. Consistency: std deviation của R:R (thấp = nhất quán)
    const rrMean = actualRR;
    const rrStd = rrTrades.length > 1
        ? Math.sqrt(rrTrades.reduce((s, t) => s + Math.pow(t.actual_rr - rrMean, 2), 0) / rrTrades.length)
        : 0;
    const consistency = Math.max(0, Math.min(100, 100 - (rrStd * 20)));

    // 5. Risk Control: % phiên không vi phạm Max DD
    const riskControl = sessions.length > 0
        ? (sessions.filter(s => (s.actual_max_dd_hit || 0) < (s.contract?.max_dd || 10)).length / sessions.length) * 100
        : 100;

    // 6. Edge Strength: Kelly Factor trung bình
    const kellyValues = sessions.map(s => {
        const wr = (s.actual_wr || 50) / 100;
        const rr = s.actual_rr_avg || 1.5;
        return wr - (1 - wr) / rr;
    });
    const edgeStrength = Math.max(0, Math.min(100, (kellyValues.reduce((a, b) => a + b, 0) / kellyValues.length) * 200));

    // 7. Recovery: Phiên sau losing session có recover không?
    let recoveryScore = 75;
    for (let i = 1; i < sessions.length; i++) {
        if (sessions[i - 1].pnl < 0) {
            recoveryScore += sessions[i].pnl > 0 ? 5 : -5;
        }
    }
    recoveryScore = Math.max(0, Math.min(100, recoveryScore));

    // 8. Timing Score: Win% theo giờ tốt nhất vs xấu nhất
    const hourBuckets = {};
    trades.forEach(t => {
        const h = t.hour_of_day || 0;
        if (!hourBuckets[h]) hourBuckets[h] = { wins: 0, total: 0 };
        hourBuckets[h].total++;
        if (t.result === 'WIN') hourBuckets[h].wins++;
    });
    const hourWRs = Object.values(hourBuckets).map(b => b.wins / b.total);
    const timingScore = hourWRs.length > 1
        ? Math.min(100, (Math.max(...hourWRs) - Math.min(...hourWRs)) * 100 + 50)
        : 60;

    // 9. Phát hiện Bad Habits
    const badHabits = [];

    // Revenge trading: 2+ lệnh thua liên tiếp rồi thêm lệnh > budget thường
    const avgRisk = totalTrades > 0 ? trades.reduce((s, t) => s + (t.risk_amount || 0), 0) / totalTrades : 0;
    let consecutiveLosses = 0;
    let revengeTrades = 0;
    trades.forEach(t => {
        if (t.result === 'LOSS') consecutiveLosses++;
        else consecutiveLosses = 0;
        if (consecutiveLosses >= 2 && t.risk_amount > avgRisk * 1.3) revengeTrades++;
    });
    if (totalTrades > 0 && revengeTrades / totalTrades > 0.1) {
        badHabits.push({ id: 'REVENGE_TRADING', label: 'REVENGE TRADING', severity: 'HIGH', detail: `Phát hiện ${revengeTrades} lần tăng risk sau chuỗi thua.`, advice: 'Đặt quy tắc cứng: sau 2 lệnh thua liên tiếp, dừng giao dịch 30 phút.' });
    }

    // Overtrading: số lệnh trung bình/phiên so với target
    const avgTradesPerSession = sessions.reduce((s, sess) => s + (sess.trades_count || 0), 0) / sessions.length;
    if (avgTradesPerSession > 7) {
        badHabits.push({ id: 'OVERTRADING', label: 'OVERTRADING', severity: 'MEDIUM', detail: `TB ${avgTradesPerSession.toFixed(1)} lệnh/phiên. Nhiều lệnh không đồng nghĩa lợi nhuận cao hơn.`, advice: 'Giới hạn max 5 lệnh/ngày trong MacroModel settings.' });
    }

    // 10. AI Recommendations
    const recommendations = [];

    const latestSessions = sessions.slice(-5);
    const latestWR = latestSessions.length > 0
        ? latestSessions.reduce((s, sess) => s + (sess.actual_wr || 0), 0) / latestSessions.length : 0;
    const latestPlannedWR = latestSessions.length > 0
        ? latestSessions.reduce((s, sess) => s + (sess.contract?.planned_wr || 55), 0) / latestSessions.length : 55;

    if (latestWR > latestPlannedWR + 8) {
        recommendations.push({
            type: 'UPGRADE_KELLY',
            priority: 'HIGH',
            label: 'Nâng Kelly Mode',
            detail: `WinRate thực tế (${latestWR.toFixed(0)}%) vượt kế hoạch ${(latestWR - latestPlannedWR).toFixed(0)}% trong 5 phiên liên tiếp.`,
            action: 'Có thể chuyển HALF_KELLY → FULL_KELLY để tối ưu tăng trưởng.'
        });
    }

    const latestRR = latestSessions.reduce((s, sess) => s + (sess.actual_rr_avg || 0), 0) / latestSessions.length;
    const plannedRR = latestSessions.reduce((s, sess) => s + (sess.contract?.planned_rr || 2.0), 0) / latestSessions.length;
    if (latestRR < plannedRR * 0.8) {
        recommendations.push({
            type: 'FIX_RR_DRIFT',
            priority: 'HIGH',
            label: 'Sửa R:R Drift',
            detail: `R:R thực tế (${latestRR.toFixed(2)}) thấp hơn ${((1 - latestRR / plannedRR) * 100).toFixed(0)}% so với kế hoạch MacroModel.`,
            action: 'Xem lại thói quen di chuyển TP sớm. Hãy để lệnh chạy theo kế hoạch ban đầu.'
        });
    }

    // Worst trading hours
    const worstHours = Object.entries(hourBuckets)
        .filter(([, b]) => b.total >= 2 && b.wins / b.total < 0.35)
        .map(([h]) => parseInt(h));
    if (worstHours.length > 0) {
        recommendations.push({
            type: 'AVOID_HOURS',
            priority: 'MEDIUM',
            label: 'Tránh giờ xấu',
            detail: `AI phát hiện tỷ lệ thắng <35% trong các giờ: ${worstHours.join('h, ')}h.`,
            action: 'Cân nhắc không giao dịch trong các khung giờ này.'
        });
    }

    const overallDNA = Math.round((consistency + avgCompliance + riskControl + edgeStrength + recoveryScore + timingScore) / 6);

    return {
        dna: { consistency, discipline: avgCompliance, timing: timingScore, recovery: recoveryScore, edgeStrength, riskControl },
        overallDNA,
        actualWR: actualWR.toFixed(1),
        actualRR: actualRR.toFixed(2),
        avgCompliance: avgCompliance.toFixed(0),
        badHabits,
        recommendations,
        sessionCount: sessions.length,
        totalTrades
    };
}

// ============================================================
// COMPONENT CHÍNH
// ============================================================
export default function AiGuardCenter({ activeSetup, unitsConfig, globalStatus, onClose, COLORS, fetchData }) {
    const unitKey     = activeSetup || 'MainUnit';
    const currentUnit = unitsConfig[unitKey] || {};

    // BUG J FIX: Dùng useMemo để tránh stale riskParams sau ARM + fetchData
    // Trước đây risk = currentUnit.risk_params || {} — không có dependency rõ ràng
    // → AiGuardCenter đọc config cũ nếu ARM và poll xảy ra cùng lúc
    const risk   = useMemo(() => currentUnit.risk_params    || {}, [JSON.stringify(currentUnit.risk_params)]);
    const neural = useMemo(() => currentUnit.neural_profile || {}, [JSON.stringify(currentUnit.neural_profile)]);

    // --- Constitution State (giữ từ bản cũ) ---
    const ARCHETYPE_INFO = {
        'SNIPER': { title: "XẠ THỦ (SNIPER)", desc: "Ưu tiên chất lượng hơn số lượng. Kiên nhẫn chờ Setup đẹp nhất. Rủi ro mỗi lệnh thấp, nhưng R:R phải cao.", impact: "AI siết tiêu chuẩn Edge bên Macro Model." },
        'SCALPER': { title: "XUNG KÍCH (SCALPER)", desc: "Tận dụng biến động nhỏ tần suất cao. Yêu cầu Winrate cao, chấp nhận R:R thấp hơn.", impact: "AI nới lỏng tần suất lệnh, siết Stoploss tuyệt đối." },
        'SWING': { title: "CHIẾN LƯỢC GIA (SWING)", desc: "Nắm giữ vị thế theo xu hướng lớn. Chấp nhận biến động ngắn hạn để ăn trọn sóng.", impact: "AI cho phép biên độ Drawdown lớn hơn trong phiên." }
    };
    const KELLY_INFO = {
        'HALF_KELLY': { title: "HALF-KELLY (AN TOÀN)", desc: "Chỉ đặt cược 50% mức tối ưu. Giảm 75% biến động, tâm lý vững vàng.", impact: "Ngân sách = 0.5 × Optimal." },
        'FULL_KELLY': { title: "FULL-KELLY (TĂNG TRƯỞNG)", desc: "Đặt cược tối đa theo toán học. Tăng trưởng nhanh nhất nhưng rủi ro cao.", impact: "Ngân sách = 1.0 × Optimal (Max Risk)." }
    };

    const safeArchetype = ARCHETYPE_INFO[neural.trader_archetype] ? neural.trader_archetype : 'SNIPER';
    const safeKelly = KELLY_INFO[neural.optimization_bias] ? neural.optimization_bias : 'HALF_KELLY';

    const [archetype, setArchetype] = useState(safeArchetype);
    const [kellyMode, setKellyMode] = useState(safeKelly);
    const [maxDrawdown, setMaxDrawdown] = useState(risk.max_dd || 10.0);
    const [drawdownMode, setDrawdownMode] = useState(risk.dd_type || 'STATIC');
    const [isSaving, setIsSaving] = useState(false);

    // --- AI Agent State ---
    const [activeTab, setActiveTab] = useState('memory'); // memory | analysis | directives

    // Load lịch sử từ localStorage
    const sessions = useMemo(() => {
        try { return JSON.parse(localStorage.getItem(`zarmor_sessions_${unitKey}`) || '[]'); } catch { return []; }
    }, [unitKey]);

    const trades = useMemo(() => {
        try { return JSON.parse(localStorage.getItem(`zarmor_trades_${unitKey}`) || '[]'); } catch { return []; }
    }, [unitKey]);

    // Dữ liệu compliance hôm nay từ globalStatus
    const todaySession = {
        pnl: globalStatus?.total_pnl || 0,
        budget_used_pct: risk.daily_limit_money > 0
            ? Math.min(100, ((globalStatus?.total_stl || 0) / risk.daily_limit_money) * 100) : 0,
        current_dd: risk.max_dd > 0
            ? Math.min(100, ((globalStatus?.current_dd || 0) / risk.max_dd) * 100) : 0,
        violations: (globalStatus?.today_violations || [])
    };

    // Chạy AI Analysis
    const aiAnalysis = useMemo(() => analyzeTraderDNA(sessions, trades), [sessions, trades]);

    // DNA Radar chart đơn giản bằng CSS (không dùng canvas để tránh bug mount)
    const renderDNABar = (label, value, color) => html`
        <div style="margin-bottom:10px;">
            <div style="display:flex; justify-content:space-between; margin-bottom:3px;">
                <span style="font-size:9px; color:#888; font-weight:bold;">${label}</span>
                <span style="font-size:9px; color:${color}; font-weight:bold;">${Math.round(value)}/100</span>
            </div>
            <div style="width:100%; height:5px; background:#1a1a1a; border-radius:3px; overflow:hidden;">
                <div style="width:${value}%; height:100%; background:${color}; border-radius:3px; transition:width 0.8s ease;"></div>
            </div>
        </div>
    `;

    const severityColor = { HIGH: COLORS.red, MEDIUM: COLORS.yellow, LOW: COLORS.cyan };
    const priorityIcon = { HIGH: '🔴', MEDIUM: '🟡', LOW: '🟢' };

    const handleSaveConstitution = async () => {
        const confirmSave = window.confirm("⚠ XÁC NHẬN THIẾT LẬP HIẾN PHÁP?\n\nNhững thay đổi này sẽ định hình lại toàn bộ cách AI tính toán rủi ro bên Macro Model.");
        if (!confirmSave) return;
        setIsSaving(true);
        try {
            const payload = {
                unit_key:   unitKey,
                mt5_login:  unitKey,
                // AiGuardCenter chỉnh dd/archetype → đây là hành động SetupModal-level
                source:     "SetupModal",
                risk_params: {
                    ...risk,
                    max_dd:  parseFloat(maxDrawdown),
                    dd_type: drawdownMode
                },
                neural_profile: {
                    ...neural,
                    trader_archetype:  archetype,
                    optimization_bias: kellyMode
                }
            };
            const res = await fetch(`${API_BASE}/api/update-unit-config`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
            });
            if (res.ok) {
                alert("✅ HIẾN PHÁP ĐÃ ĐƯỢC THÔNG QUA!");
                await fetchData();
                onClose();
            } else { alert("❌ Lỗi từ máy chủ!"); }
        } catch (e) { alert("Lỗi kết nối!"); }
        finally { setIsSaving(false); }
    };

    // ── STYLES ──
    const tabStyle = (tab) => `padding:8px 16px; border:none; border-bottom:2px solid ${activeTab === tab ? COLORS.cyan : 'transparent'}; background:transparent; color:${activeTab === tab ? COLORS.cyan : '#555'}; font-weight:900; font-size:10px; letter-spacing:1px; cursor:pointer; transition:0.2s;`;
    const colStyle = `background:#0a0c10; border:1px solid #1a1a1a; border-radius:4px; padding:20px; display:flex; flex-direction:column; gap:16px; overflow-y:auto; max-height:calc(85vh - 140px);`;
    const sectionTitle = (color, icon, text) => html`
        <div style="font-size:11px; color:${color}; font-weight:900; letter-spacing:1px; display:flex; align-items:center; gap:6px; border-bottom:1px solid #1a1a1a; padding-bottom:8px;">
            <span>${icon}</span> ${text}
        </div>
    `;
    const cardStyle = `background:#05070a; border:1px solid #1a1a1a; border-radius:4px; padding:12px;`;

    const noDataBanner = html`
        <div style="text-align:center; padding:30px 10px; color:#333; font-size:11px; font-style:italic; border:1px dashed #1a1a1a; border-radius:4px;">
            <div style="font-size:24px; margin-bottom:8px;">🌱</div>
            Chưa có dữ liệu lịch sử.<br/>AI sẽ bắt đầu học sau phiên đầu tiên.
        </div>
    `;

    return html`
        <div style="position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.95); display:flex; align-items:center; justify-content:center; z-index:10000; backdrop-filter:blur(8px);">
            <div style="background:#080a0f; border:1px solid ${COLORS.cyan}44; width:1100px; max-height:92vh; display:flex; flex-direction:column; border-radius:6px; box-shadow:0 0 80px ${COLORS.cyan}18; overflow:hidden;">

                <!-- HEADER -->
                <div style="display:flex; justify-content:space-between; align-items:center; padding:16px 24px; background:#020305; border-bottom:1px solid #1a1a1a; flex-shrink:0;">
                    <div style="display:flex; align-items:center; gap:16px;">
                        <div>
                            <div style="font-size:18px; color:${COLORS.cyan}; font-weight:900; letter-spacing:2px;">⚖️ AI GUARD CENTER</div>
                            <div style="font-size:9px; color:#444; margin-top:2px; letter-spacing:1px;">CONSCIENCE ENGINE — MEMORY · ANALYSIS · DIRECTIVES</div>
                        </div>
                        ${aiAnalysis ? html`
                            <div style="background:#0a0c10; border:1px solid #222; border-left:3px solid ${aiAnalysis.overallDNA >= 75 ? COLORS.green : aiAnalysis.overallDNA >= 50 ? COLORS.yellow : COLORS.red}; padding:8px 14px; border-radius:4px;">
                                <div style="font-size:9px; color:#555; font-weight:bold;">STRATEGY DNA SCORE</div>
                                <div style="font-size:22px; color:${aiAnalysis.overallDNA >= 75 ? COLORS.green : aiAnalysis.overallDNA >= 50 ? COLORS.yellow : COLORS.red}; font-weight:900; font-family:monospace;">${aiAnalysis.overallDNA}<span style="font-size:11px; color:#555;">/100</span></div>
                            </div>
                            <div style="background:#0a0c10; border:1px solid #222; padding:8px 14px; border-radius:4px;">
                                <div style="font-size:9px; color:#555; font-weight:bold;">SESSIONS ANALYZED</div>
                                <div style="font-size:22px; color:#fff; font-weight:900; font-family:monospace;">${aiAnalysis.sessionCount}</div>
                            </div>
                        ` : html`
                            <div style="background:#0a0c10; border:1px dashed #1a1a1a; padding:8px 14px; border-radius:4px; font-size:9px; color:#333; font-style:italic;">AI chưa có dữ liệu để phân tích</div>
                        `}
                    </div>
                    <button onClick=${onClose} style="background:none; border:none; color:#444; font-size:28px; cursor:pointer; line-height:1;">×</button>
                </div>

                <!-- TAB BAR (mobile-friendly) -->
                <div style="display:flex; border-bottom:1px solid #1a1a1a; flex-shrink:0; background:#020305;">
                    <button style=${tabStyle('memory')} onClick=${() => setActiveTab('memory')}>🧠 MEMORY BANK</button>
                    <button style=${tabStyle('analysis')} onClick=${() => setActiveTab('analysis')}>⚡ LIVE ANALYSIS</button>
                    <button style=${tabStyle('directives')} onClick=${() => setActiveTab('directives')}>📋 DIRECTIVES & CONSTITUTION</button>
                </div>

                <!-- CONTENT AREA -->
                <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:16px; padding:16px; flex:1; overflow:hidden;">

                    <!-- ══════════════════════════════════ -->
                    <!-- COL 1: MEMORY BANK                -->
                    <!-- ══════════════════════════════════ -->
                    <div style="${colStyle} ${activeTab !== 'memory' && window.innerWidth < 1000 ? 'display:none;' : ''}">
                        ${sectionTitle(COLORS.purple, '🧠', 'MEMORY BANK')}

                        <!-- Session Timeline -->
                        <div style="${cardStyle}">
                            <div style="font-size:10px; color:#888; font-weight:bold; margin-bottom:10px;">SESSION TIMELINE (${sessions.length} phiên)</div>
                            ${sessions.length > 0 ? html`
                                <div style="display:flex; flex-direction:column; gap:6px; max-height:180px; overflow-y:auto;">
                                    ${[...sessions].reverse().slice(0, 7).map(s => html`
                                        <div style="display:flex; align-items:center; gap:8px; padding:7px; background:#0a0c10; border-radius:3px; border-left:3px solid ${s.compliance_score >= 85 ? COLORS.green : s.compliance_score >= 60 ? COLORS.yellow : COLORS.red};">
                                            <div style="font-size:9px; color:#555; min-width:40px;">${s.date || '—'}</div>
                                            <div style="flex:1; height:4px; background:#1a1a1a; border-radius:2px; overflow:hidden;">
                                                <div style="width:${s.compliance_score || 0}%; height:100%; background:${s.compliance_score >= 85 ? COLORS.green : s.compliance_score >= 60 ? COLORS.yellow : COLORS.red};"></div>
                                            </div>
                                            <div style="font-size:9px; color:${s.compliance_score >= 85 ? COLORS.green : s.compliance_score >= 60 ? COLORS.yellow : COLORS.red}; font-weight:bold; min-width:30px;">${s.compliance_score || 0}%</div>
                                            <div style="font-size:9px; color:${s.pnl >= 0 ? COLORS.green : COLORS.red}; min-width:45px; text-align:right; font-family:monospace;">${s.pnl >= 0 ? '+' : ''}$${(s.pnl || 0).toFixed(0)}</div>
                                            ${(s.violations && s.violations.length > 0) ? html`<span>⚠️</span>` : null}
                                        </div>
                                    `)}
                                </div>
                            ` : noDataBanner}


                        </div>

                        <!-- Bad Habits -->
                        <div style="${cardStyle}">
                            <div style="font-size:10px; color:#888; font-weight:bold; margin-bottom:10px;">BAD HABITS DETECTED</div>
                            ${!aiAnalysis || aiAnalysis.badHabits.length === 0 ? html`
                                <div style="text-align:center; padding:15px; color:#2a4a2a; font-size:10px; border:1px dashed #1a3a1a; border-radius:3px;">
                                    ✅ Không phát hiện thói quen xấu
                                </div>
                            ` : aiAnalysis.badHabits.map(h => html`
                                <div style="background:#0a0c10; border:1px solid ${severityColor[h.severity]}33; border-left:3px solid ${severityColor[h.severity]}; padding:10px; border-radius:3px; margin-bottom:8px;">
                                    <div style="font-size:10px; color:${severityColor[h.severity]}; font-weight:900; margin-bottom:4px;">${h.label}</div>
                                    <div style="font-size:9px; color:#888; line-height:1.5;">${h.detail}</div>
                                    <div style="font-size:9px; color:#555; margin-top:5px; font-style:italic;">💡 ${h.advice}</div>
                                </div>
                            `)}
                        </div>

                        <!-- Strategy DNA Score -->
                        <div style="${cardStyle}">
                            <div style="font-size:10px; color:#888; font-weight:bold; margin-bottom:12px;">STRATEGY DNA FINGERPRINT</div>
                            ${aiAnalysis ? html`
                                ${renderDNABar('CONSISTENCY (R:R)', aiAnalysis.dna.consistency, COLORS.cyan)}
                                ${renderDNABar('DISCIPLINE (Tuân thủ)', aiAnalysis.dna.discipline, COLORS.purple)}
                                ${renderDNABar('TIMING (Chọn giờ)', aiAnalysis.dna.timing, COLORS.yellow)}
                                ${renderDNABar('RECOVERY (Phục hồi)', aiAnalysis.dna.recovery, COLORS.green)}
                                ${renderDNABar('EDGE STRENGTH (Kelly)', aiAnalysis.dna.edgeStrength, '#00bfff')}
                                ${renderDNABar('RISK CONTROL (DD)', aiAnalysis.dna.riskControl, COLORS.red)}
                            ` : noDataBanner}

                        </div>
                    </div>

                    <!-- ══════════════════════════════════ -->
                    <!-- COL 2: LIVE ANALYSIS              -->
                    <!-- ══════════════════════════════════ -->
                    <div style="${colStyle}">
                        ${sectionTitle(COLORS.yellow, '⚡', 'LIVE ANALYSIS')}

                        <!-- Compliance Today -->
                        <div style="${cardStyle}">
                            <div style="font-size:10px; color:#888; font-weight:bold; margin-bottom:10px;">RISK AUDIT — PHIÊN HÔM NAY</div>
                            <div style="display:flex; flex-direction:column; gap:10px;">
                                <div>
                                    <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                                        <span style="font-size:9px; color:#888;">BUDGET USED</span>
                                        <span style="font-size:9px; color:${todaySession.budget_used_pct >= 90 ? COLORS.red : COLORS.cyan}; font-weight:bold;">${todaySession.budget_used_pct.toFixed(1)}%</span>
                                    </div>
                                    <div style="width:100%; height:6px; background:#1a1a1a; border-radius:3px; overflow:hidden;">
                                        <div style="width:${Math.min(100, todaySession.budget_used_pct)}%; height:100%; background:${todaySession.budget_used_pct >= 90 ? COLORS.red : COLORS.cyan}; transition:width 0.5s;"></div>
                                    </div>
                                </div>
                                <div>
                                    <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                                        <span style="font-size:9px; color:#888;">DRAWDOWN CAPACITY</span>
                                        <span style="font-size:9px; color:${todaySession.current_dd >= 80 ? COLORS.red : todaySession.current_dd >= 50 ? COLORS.yellow : COLORS.green}; font-weight:bold;">${todaySession.current_dd.toFixed(1)}%</span>
                                    </div>
                                    <div style="width:100%; height:6px; background:#1a1a1a; border-radius:3px; overflow:hidden;">
                                        <div style="width:${Math.min(100, todaySession.current_dd)}%; height:100%; background:${todaySession.current_dd >= 80 ? COLORS.red : todaySession.current_dd >= 50 ? COLORS.yellow : COLORS.green}; transition:width 0.5s;"></div>
                                    </div>
                                </div>
                                <div style="display:flex; justify-content:space-between; padding-top:8px; border-top:1px dashed #1a1a1a;">
                                    <div>
                                        <div style="font-size:9px; color:#555;">PnL HÔM NAY</div>
                                        <div style="font-size:18px; color:${todaySession.pnl >= 0 ? COLORS.green : COLORS.red}; font-weight:900; font-family:monospace;">${todaySession.pnl >= 0 ? '+' : ''}$${(todaySession.pnl).toFixed(2)}</div>
                                    </div>
                                    <div style="text-align:right;">
                                        <div style="font-size:9px; color:#555;">VIOLATIONS</div>
                                        <div style="font-size:18px; color:${todaySession.violations.length > 0 ? COLORS.red : COLORS.green}; font-weight:900; font-family:monospace;">${todaySession.violations.length}</div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Edge Drift Monitor -->
                        <div style="${cardStyle}">
                            <div style="font-size:10px; color:#888; font-weight:bold; margin-bottom:10px;">EDGE DRIFT MONITOR</div>
                            ${aiAnalysis ? html`
                                <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
                                    <div style="background:#0a0c10; padding:10px; border-radius:3px; text-align:center;">
                                        <div style="font-size:9px; color:#555; margin-bottom:4px;">WIN RATE</div>
                                        <div style="font-size:8px; color:#444; margin-bottom:2px;">Kế hoạch: ${neural.historical_win_rate || 55}%</div>
                                        <div style="font-size:20px; font-weight:900; font-family:monospace; color:${parseFloat(aiAnalysis.actualWR) >= (neural.historical_win_rate || 55) ? COLORS.green : COLORS.red};">
                                            ${aiAnalysis.actualWR}%
                                        </div>
                                        <div style="font-size:9px; color:${parseFloat(aiAnalysis.actualWR) >= (neural.historical_win_rate || 55) ? COLORS.green : COLORS.red}; margin-top:2px;">
                                            ${parseFloat(aiAnalysis.actualWR) >= (neural.historical_win_rate || 55) ? '▲' : '▼'} ${Math.abs(parseFloat(aiAnalysis.actualWR) - (neural.historical_win_rate || 55)).toFixed(1)}%
                                        </div>
                                    </div>
                                    <div style="background:#0a0c10; padding:10px; border-radius:3px; text-align:center;">
                                        <div style="font-size:9px; color:#555; margin-bottom:4px;">R:R RATIO</div>
                                        <div style="font-size:8px; color:#444; margin-bottom:2px;">Kế hoạch: ${neural.historical_rr || 2.0}</div>
                                        <div style="font-size:20px; font-weight:900; font-family:monospace; color:${parseFloat(aiAnalysis.actualRR) >= (neural.historical_rr || 2.0) * 0.85 ? COLORS.green : COLORS.red};">
                                            ${aiAnalysis.actualRR}
                                        </div>
                                        <div style="font-size:9px; color:${parseFloat(aiAnalysis.actualRR) >= (neural.historical_rr || 2.0) * 0.85 ? COLORS.green : COLORS.red}; margin-top:2px;">
                                            ${parseFloat(aiAnalysis.actualRR) >= (neural.historical_rr || 2.0) ? '▲' : '▼'} ${Math.abs(parseFloat(aiAnalysis.actualRR) - (neural.historical_rr || 2.0)).toFixed(2)}
                                        </div>
                                    </div>
                                </div>
                                <div style="margin-top:10px; font-size:9px; color:#555; font-style:italic; line-height:1.5;">
                                    Dữ liệu từ ${aiAnalysis.totalTrades} lệnh · ${aiAnalysis.sessionCount} phiên
                                </div>
                            ` : noDataBanner}

                        </div>

                        <!-- Compliance Heatmap (7 ngày gần nhất × trạng thái) -->
                        <div style="${cardStyle}">
                            <div style="font-size:10px; color:#888; font-weight:bold; margin-bottom:10px;">COMPLIANCE HEATMAP (7 PHIÊN)</div>
                            ${sessions.length > 0 ? html`
                                <div style="display:flex; gap:4px; flex-wrap:wrap;">
                                    ${[...sessions].reverse().slice(0, 7).map((s, i) => html`
                                        <div title="session data"
                                            style="flex:1; min-width:35px; height:60px; background:${s.compliance_score >= 85 ? COLORS.green + '33' : s.compliance_score >= 60 ? COLORS.yellow + '33' : COLORS.red + '33'}; border:1px solid ${s.compliance_score >= 85 ? COLORS.green + '55' : s.compliance_score >= 60 ? COLORS.yellow + '55' : COLORS.red + '55'}; border-radius:3px; display:flex; flex-direction:column; align-items:center; justify-content:center; cursor:default;">
                                            <div style="font-size:10px; color:${s.compliance_score >= 85 ? COLORS.green : s.compliance_score >= 60 ? COLORS.yellow : COLORS.red}; font-weight:900;">${s.compliance_score || 0}%</div>
                                            <div style="font-size:8px; color:#555; margin-top:2px;">${s.date ? s.date.slice(5) : 'D-' + i}</div>
                                        </div>
                                    `)}
                                </div>
                                <div style="display:flex; gap:10px; margin-top:8px; justify-content:center;">
                                    <span style="font-size:8px; color:${COLORS.green};">■ ≥85% Tốt</span>
                                    <span style="font-size:8px; color:${COLORS.yellow};">■ 60-84% TB</span>
                                    <span style="font-size:8px; color:${COLORS.red};">■ <60% Xấu</span>
                                </div>
                            ` : noDataBanner}

                        </div>
                    </div>

                    <!-- ══════════════════════════════════════ -->
                    <!-- COL 3: DIRECTIVES & CONSTITUTION     -->
                    <!-- ══════════════════════════════════════ -->
                    <div style="${colStyle}">
                        ${sectionTitle(COLORS.cyan, '📋', 'DIRECTIVES & CONSTITUTION')}

                        <!-- AI Recommendations -->
                        <div style="${cardStyle}">
                            <div style="font-size:10px; color:#888; font-weight:bold; margin-bottom:10px;">
                                AI RECOMMENDATIONS
                                ${aiAnalysis ? html`<span style="color:#333; font-weight:normal;"> · ${aiAnalysis.recommendations.length} gợi ý</span>` : ''}
                            </div>
                            ${!aiAnalysis || aiAnalysis.recommendations.length === 0 ? html`
                                <div style="text-align:center; padding:15px; color:#2a4a2a; font-size:10px; border:1px dashed #1a3a1a; border-radius:3px;">
                                    ✅ AI không có gợi ý điều chỉnh.<br/>Hệ thống đang vận hành tốt.
                                </div>
                            ` : aiAnalysis.recommendations.map(r => html`
                                <div style="background:#0a0c10; border:1px solid #1a1a1a; border-top:2px solid ${r.priority === 'HIGH' ? COLORS.red : r.priority === 'MEDIUM' ? COLORS.yellow : COLORS.cyan}; padding:10px; border-radius:3px; margin-bottom:8px;">
                                    <div style="display:flex; justify-content:space-between; margin-bottom:5px;">
                                        <span style="font-size:10px; color:#fff; font-weight:900;">${priorityIcon[r.priority]} ${r.label}</span>
                                        <span style="font-size:8px; color:${r.priority === 'HIGH' ? COLORS.red : COLORS.yellow}; font-weight:bold;">${r.priority}</span>
                                    </div>
                                    <div style="font-size:9px; color:#888; line-height:1.5; margin-bottom:5px;">${r.detail}</div>
                                    <div style="font-size:9px; color:${COLORS.cyan}; font-style:italic;">→ ${r.action}</div>
                                </div>
                            `)}
                        </div>

                        <!-- Active Alerts -->
                        <div style="${cardStyle}">
                            <div style="font-size:10px; color:#888; font-weight:bold; margin-bottom:10px;">ACTIVE ALERTS</div>
                            <div style="display:flex; flex-direction:column; gap:6px;">
                                <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 8px; background:#0a0c10; border-radius:3px; border:1px solid #1a1a1a;">
                                    <span style="font-size:9px; color:#888;">R:R Drift</span>
                                    <span style="font-size:9px; font-weight:bold; color:${aiAnalysis && parseFloat(aiAnalysis.actualRR) < (neural.historical_rr || 2) * 0.85 ? COLORS.yellow : COLORS.green};">
                                        ${aiAnalysis && parseFloat(aiAnalysis.actualRR) < (neural.historical_rr || 2) * 0.85 ? '⚠ DRIFT' : '✅ ON TRACK'}
                                    </span>
                                </div>
                                <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 8px; background:#0a0c10; border-radius:3px; border:1px solid #1a1a1a;">
                                    <span style="font-size:9px; color:#888;">Daily Budget</span>
                                    <span style="font-size:9px; font-weight:bold; color:${todaySession.budget_used_pct >= 90 ? COLORS.red : COLORS.green};">
                                        ${todaySession.budget_used_pct >= 90 ? '🔴 NEAR LIMIT' : '🟢 OK'}
                                    </span>
                                </div>
                                <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 8px; background:#0a0c10; border-radius:3px; border:1px solid #1a1a1a;">
                                    <span style="font-size:9px; color:#888;">Drawdown</span>
                                    <span style="font-size:9px; font-weight:bold; color:${todaySession.current_dd >= 80 ? COLORS.red : todaySession.current_dd >= 50 ? COLORS.yellow : COLORS.green};">
                                        ${todaySession.current_dd >= 80 ? '🔴 CRITICAL' : todaySession.current_dd >= 50 ? '🟡 WARNING' : '🟢 SAFE'}
                                    </span>
                                </div>
                                ${aiAnalysis && aiAnalysis.badHabits.length > 0 ? html`
                                    <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 8px; background:#0a0c10; border-radius:3px; border:1px solid #1a1a1a;">
                                        <span style="font-size:9px; color:#888;">Bad Habits</span>
                                        <span style="font-size:9px; font-weight:bold; color:${COLORS.yellow};">🟡 ${aiAnalysis.badHabits.length} phát hiện</span>
                                    </div>
                                ` : null}
                            </div>
                        </div>

                        <!-- Constitution (Manual Override) -->
                        <div style="background:#0a0c10; border:1px solid #222; border-left:4px solid ${COLORS.purple}; padding:14px; border-radius:4px;">
                            <div style="font-size:10px; color:${COLORS.purple}; font-weight:900; letter-spacing:1px; margin-bottom:12px;">⚙️ CONSTITUTION (MANUAL)</div>

                            <!-- Archetype -->
                            <div style="margin-bottom:12px;">
                                <label style="font-size:9px; color:#555; font-weight:bold; display:block; margin-bottom:5px;">[1] IDENTITY — CỐT CÁCH</label>
                                <select value=${archetype} onChange=${e => setArchetype(e.target.value)}
                                    style="width:100%; background:#05070a; color:#fff; border:1px solid #333; padding:7px; border-radius:3px; font-size:10px; cursor:pointer; outline:none;">
                                    <option value="SNIPER">🛡️ SNIPER</option>
                                    <option value="SCALPER">⚔️ SCALPER</option>
                                    <option value="SWING">🌊 SWING</option>
                                </select>
                                <div style="font-size:9px; color:#555; margin-top:4px; font-style:italic;">${ARCHETYPE_INFO[archetype]?.impact || ""}</div>
                            </div>

                            <!-- Kelly -->
                            <div style="margin-bottom:12px;">
                                <label style="font-size:9px; color:#555; font-weight:bold; display:block; margin-bottom:5px;">[2] KELLY MODE</label>
                                <select value=${kellyMode} onChange=${e => setKellyMode(e.target.value)}
                                    style="width:100%; background:#05070a; color:#fff; border:1px solid #333; padding:7px; border-radius:3px; font-size:10px; cursor:pointer; outline:none;">
                                    <option value="HALF_KELLY">📉 HALF-KELLY (KHUYÊN DÙNG)</option>
                                    <option value="FULL_KELLY">📈 FULL-KELLY (RỦI RO CAO)</option>
                                </select>
                            </div>

                            <!-- Max DD -->
                            <div style="margin-bottom:12px;">
                                <label style="font-size:9px; color:#555; font-weight:bold; display:block; margin-bottom:5px;">[3] MAX DRAWDOWN — ĐÁY TỬ THỦ</label>
                                <div style="display:flex; align-items:center; gap:8px;">
                                    <input type="range" min="1" max="20" step="0.5" value=${maxDrawdown} onInput=${e => setMaxDrawdown(e.target.value)} style="flex:1; cursor:pointer;" />
                                    <div style="background:#05070a; border:1px solid ${COLORS.red}; color:${COLORS.red}; font-weight:bold; padding:6px 10px; border-radius:3px; font-family:monospace; font-size:12px; min-width:50px; text-align:center;">${maxDrawdown}%</div>
                                </div>
                            </div>

                            <!-- DD Mode -->
                            <div style="margin-bottom:14px;">
                                <label style="font-size:9px; color:#555; font-weight:bold; display:block; margin-bottom:5px;">[4] CAPACITY MODE</label>
                                <div style="display:flex; gap:6px;">
                                    <button onClick=${() => setDrawdownMode('STATIC')}
                                        style="flex:1; padding:7px; background:${drawdownMode === 'STATIC' ? COLORS.red + '22' : '#111'}; border:1px solid ${drawdownMode === 'STATIC' ? COLORS.red : '#333'}; color:${drawdownMode === 'STATIC' ? '#fff' : '#555'}; font-size:9px; font-weight:bold; cursor:pointer; border-radius:3px; transition:0.2s;">
                                        STATIC
                                    </button>
                                    <button onClick=${() => setDrawdownMode('TRAILING')}
                                        style="flex:1; padding:7px; background:${drawdownMode === 'TRAILING' ? '#ff8c0022' : '#111'}; border:1px solid ${drawdownMode === 'TRAILING' ? '#ff8c00' : '#333'}; color:${drawdownMode === 'TRAILING' ? '#fff' : '#555'}; font-size:9px; font-weight:bold; cursor:pointer; border-radius:3px; transition:0.2s;">
                                        TRAILING
                                    </button>
                                </div>
                            </div>

                            <button onClick=${handleSaveConstitution} disabled=${isSaving}
                                style="width:100%; padding:12px; background:${isSaving ? '#111' : COLORS.cyan}; color:#000; font-weight:900; border:none; cursor:pointer; border-radius:3px; font-size:11px; letter-spacing:1px; transition:0.3s; box-shadow:${isSaving ? 'none' : '0 0 15px ' + COLORS.cyan + '33'};">
                                ${isSaving ? '⏳ ĐANG KHẮC VÀO LÕI...' : '✔ LƯU HIẾN PHÁP'}
                            </button>
                        </div>

                    </div>
                </div>
            </div>
        </div>
    `;
}