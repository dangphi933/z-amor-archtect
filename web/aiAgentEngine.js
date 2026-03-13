/**
 * ZARMOR AI AGENT ENGINE
 * Bộ não trung tâm — xử lý học tập, phân tích và tuân thủ
 * 
 * Tích hợp vào: Cockpit (ghi lệnh) + AiGuardCenter (đọc phân tích)
 */

// ============================================================
// 1. TRADE LOGGER — Ghi lệnh vào bộ nhớ AI
// ============================================================

/**
 * Ghi một lệnh mới vào lịch sử
 * Gọi từ Cockpit khi có lệnh mới hoặc lệnh đóng
 */
export function logTrade(accountId, tradeData) {
    const key = `zarmor_trades_${accountId}`;
    let trades = [];
    try { trades = JSON.parse(localStorage.getItem(key) || '[]'); } catch {}
    
    const entry = {
        id: `trade_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
        session_id: getCurrentSessionId(accountId),
        timestamp: Date.now(),
        symbol: tradeData.symbol || '',
        direction: tradeData.direction || 'BUY',
        result: tradeData.result || 'PENDING', // WIN | LOSS | BE | PENDING
        risk_amount: parseFloat(tradeData.risk_amount || 0),
        actual_rr: parseFloat(tradeData.actual_rr || 0),
        planned_rr: parseFloat(tradeData.planned_rr || 0),
        hour_of_day: new Date().getHours(),
        day_of_week: new Date().getDay(),
        deviation_score: calcDeviationScore(tradeData),
        ...tradeData
    };
    
    trades.push(entry);
    // Giữ tối đa 500 lệnh gần nhất
    if (trades.length > 500) trades = trades.slice(-500);
    
    localStorage.setItem(key, JSON.stringify(trades));
    return entry;
}

/**
 * Cập nhật kết quả lệnh khi lệnh đóng
 */
export function updateTradeResult(accountId, tradeId, result, actualRR) {
    const key = `zarmor_trades_${accountId}`;
    let trades = [];
    try { trades = JSON.parse(localStorage.getItem(key) || '[]'); } catch {}
    
    const idx = trades.findIndex(t => t.id === tradeId);
    if (idx >= 0) {
        trades[idx].result = result;
        trades[idx].actual_rr = actualRR;
        trades[idx].closed_at = Date.now();
        localStorage.setItem(key, JSON.stringify(trades));
    }
}

// ============================================================
// 2. SESSION MANAGER — Quản lý phiên giao dịch
// ============================================================

/**
 * Mở phiên mới (gọi khi user ARM hệ thống trong MacroModal)
 */
export function openSession(accountId, setupContract, macroContract) {
    const sessionId = `session_${Date.now()}`;
    const session = {
        session_id: sessionId,
        date: new Date().toISOString().slice(0, 10),
        opened_at: Date.now(),
        opening_balance: macroContract.current_balance || 10000,
        contract: {
            daily_budget: setupContract.daily_limit_money || 150,
            max_dd: setupContract.max_dd || 10,
            dd_type: setupContract.dd_type || 'STATIC',
            planned_wr: macroContract.historical_win_rate || 55,
            planned_rr: macroContract.historical_rr || 2.0,
            archetype: macroContract.trader_archetype || 'SNIPER',
            kelly_mode: macroContract.optimization_bias || 'HALF_KELLY'
        },
        status: 'ACTIVE',
        trades_count: 0,
        wins: 0, losses: 0,
        actual_max_dd_hit: 0,
        pnl: 0,
        compliance_score: 100,
        violations: []
    };
    
    localStorage.setItem(`zarmor_current_session_${accountId}`, JSON.stringify(session));
    return session;
}

/**
 * Đóng phiên và lưu vào history (gọi khi Rollover)
 */
export function closeSession(accountId, finalPnL, maxDDHit) {
    const currentSession = getCurrentSession(accountId);
    if (!currentSession) return null;
    
    // Lấy trades của phiên này
    let trades = [];
    try { trades = JSON.parse(localStorage.getItem(`zarmor_trades_${accountId}`) || '[]'); } catch {}
    const sessionTrades = trades.filter(t => t.session_id === currentSession.session_id);
    
    const wins = sessionTrades.filter(t => t.result === 'WIN').length;
    const losses = sessionTrades.filter(t => t.result === 'LOSS').length;
    const rrTrades = sessionTrades.filter(t => t.actual_rr > 0);
    const avgRR = rrTrades.length > 0 ? rrTrades.reduce((s, t) => s + t.actual_rr, 0) / rrTrades.length : 0;
    
    const closedSession = {
        ...currentSession,
        closed_at: Date.now(),
        pnl: finalPnL,
        actual_max_dd_hit: maxDDHit,
        trades_count: sessionTrades.length,
        wins, losses,
        actual_wr: sessionTrades.length > 0 ? (wins / sessionTrades.length) * 100 : 0,
        actual_rr_avg: avgRR,
        compliance_score: calcSessionCompliance(currentSession, sessionTrades, maxDDHit),
        status: 'COMPLETED'
    };
    
    // Lưu vào history
    const historyKey = `zarmor_sessions_${accountId}`;
    let sessions = [];
    try { sessions = JSON.parse(localStorage.getItem(historyKey) || '[]'); } catch {}
    sessions.push(closedSession);
    if (sessions.length > 90) sessions = sessions.slice(-90); // Giữ 90 phiên
    localStorage.setItem(historyKey, JSON.stringify(sessions));
    
    // Xóa current session
    localStorage.removeItem(`zarmor_current_session_${accountId}`);
    
    return closedSession;
}

// ============================================================
// 3. COMPLIANCE MONITOR — Kiểm tra tuân thủ real-time
// ============================================================

/**
 * Kiểm tra một lệnh dự kiến có vi phạm không
 * Trả về: { approved, violations, warnings }
 */
export function checkCompliance(accountId, proposedTrade, currentMetrics) {
    const session = getCurrentSession(accountId);
    if (!session) return { approved: true, violations: [], warnings: ['Chưa có session contract'] };
    
    const contract = session.contract;
    const violations = [];
    const warnings = [];
    
    // 1. Budget violation
    const riskAmount = parseFloat(proposedTrade.risk_amount || 0);
    const usedToday = parseFloat(currentMetrics.daily_used || 0);
    if (riskAmount > contract.daily_budget) {
        violations.push({ type: 'OVER_BUDGET', severity: 'HIGH', detail: `Risk $${riskAmount} > Daily Budget $${contract.daily_budget}` });
    } else if (usedToday + riskAmount > contract.daily_budget * 0.9) {
        warnings.push({ type: 'NEAR_BUDGET', detail: `Sẽ dùng ${((usedToday + riskAmount) / contract.daily_budget * 100).toFixed(0)}% ngân sách ngày` });
    }
    
    // 2. R:R violation
    const proposedRR = parseFloat(proposedTrade.planned_rr || 0);
    if (proposedRR > 0 && proposedRR < contract.planned_rr * 0.7) {
        violations.push({ type: 'POOR_RR', severity: 'MEDIUM', detail: `R:R ${proposedRR} thấp hơn 30% so với kế hoạch (${contract.planned_rr})` });
    } else if (proposedRR > 0 && proposedRR < contract.planned_rr * 0.85) {
        warnings.push({ type: 'RR_DRIFT', detail: `R:R ${proposedRR} thấp hơn kế hoạch ${contract.planned_rr}` });
    }
    
    // 3. Drawdown warning
    const currentDD = parseFloat(currentMetrics.current_dd_pct || 0);
    if (currentDD >= contract.max_dd * 0.9) {
        violations.push({ type: 'NEAR_MAX_DD', severity: 'CRITICAL', detail: `Drawdown ${currentDD.toFixed(1)}% đang tiếp cận Max DD ${contract.max_dd}%` });
    } else if (currentDD >= contract.max_dd * 0.75) {
        warnings.push({ type: 'DD_WARNING', detail: `Drawdown ${currentDD.toFixed(1)}% — còn ${(contract.max_dd - currentDD).toFixed(1)}% buffer` });
    }
    
    // 4. Ghi vi phạm vào session
    if (violations.length > 0) {
        recordViolation(accountId, violations);
    }
    
    return {
        approved: violations.filter(v => v.severity === 'HIGH' || v.severity === 'CRITICAL').length === 0,
        violations,
        warnings
    };
}

/**
 * Ghi vi phạm vào current session
 */
function recordViolation(accountId, violations) {
    const session = getCurrentSession(accountId);
    if (!session) return;
    
    violations.forEach(v => {
        if (!session.violations.find(existing => existing.type === v.type)) {
            session.violations.push({ ...v, timestamp: Date.now() });
        }
    });
    
    // Cập nhật compliance score
    session.compliance_score = Math.max(0, 100 - session.violations.length * 15);
    localStorage.setItem(`zarmor_current_session_${accountId}`, JSON.stringify(session));
}

// ============================================================
// 4. HELPER FUNCTIONS
// ============================================================

function getCurrentSessionId(accountId) {
    const session = getCurrentSession(accountId);
    return session?.session_id || 'no_session';
}

function getCurrentSession(accountId) {
    try {
        return JSON.parse(localStorage.getItem(`zarmor_current_session_${accountId}`) || 'null');
    } catch { return null; }
}

function calcDeviationScore(tradeData) {
    // 0 = tuân thủ hoàn toàn, 1 = vi phạm hoàn toàn
    if (!tradeData.planned_rr || !tradeData.actual_rr) return 0;
    const rrDiff = Math.abs(tradeData.actual_rr - tradeData.planned_rr) / tradeData.planned_rr;
    return Math.min(1, rrDiff);
}

function calcSessionCompliance(session, trades, maxDDHit) {
    let score = 100;
    const contract = session.contract;
    
    // Trừ điểm theo vi phạm
    score -= session.violations.length * 10;
    
    // Trừ điểm nếu DD vượt ngưỡng
    if (maxDDHit > contract.max_dd * 0.8) score -= 15;
    
    // Trừ điểm R:R drift
    const avgRR = trades.length > 0
        ? trades.filter(t => t.actual_rr > 0).reduce((s, t) => s + t.actual_rr, 0) / trades.length
        : contract.planned_rr;
    if (avgRR < contract.planned_rr * 0.8) score -= 10;
    
    return Math.max(0, Math.min(100, Math.round(score)));
}

// ============================================================
// 5. DEBRIEFING — Tự động tổng kết cuối phiên
// ============================================================

/**
 * Tạo báo cáo tổng kết phiên (dùng để gửi Telegram)
 */
export function generateDebrief(closedSession) {
    const s = closedSession;
    const status = s.pnl >= 0 ? '✅ THẮNG LỢI' : '❌ THUA LỖ';
    const compliance = s.compliance_score >= 85 ? '🏆 XUẤT SẮC' : s.compliance_score >= 60 ? '⚠️ TRUNG BÌNH' : '🚨 KÉM';
    
    return `
📊 *ZARMOR SESSION DEBRIEF — ${s.date}*

${status} | P&L: ${s.pnl >= 0 ? '+' : ''}$${(s.pnl || 0).toFixed(2)}
📈 Win Rate: ${(s.actual_wr || 0).toFixed(0)}% (KH: ${s.contract.planned_wr}%)
⚖️ R:R Thực: ${(s.actual_rr_avg || 0).toFixed(2)} (KH: ${s.contract.planned_rr})
📉 Max DD: ${(s.actual_max_dd_hit || 0).toFixed(1)}% / ${s.contract.max_dd}%

${compliance} Điểm Kỷ Luật: ${s.compliance_score}/100
🎯 ${s.trades_count} Lệnh | ${s.wins}W ${s.losses}L

${s.violations.length > 0 ? '⚠️ Vi phạm: ' + s.violations.map(v => v.type).join(', ') : '✅ Không vi phạm'}
`.trim();
}