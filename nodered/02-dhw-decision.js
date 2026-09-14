// ─────────────────────────────────────────────────────────────────────────────
// Node-RED function node:  "DHW Decision (adaptive)"
// Replaces "DHW Decision Logic (FIXED)".
//
// WHAT CHANGED vs the old node (docs/recommendations.md #3 and #4):
//   #3  The evening fill now uses ORDERED (SG Ready state 4 = 60 °C) instead of
//       Comfort (55 °C). No register change is needed — state 4 already commands
//       60 °C. Measured effect on evening draws that punch through the 40 °C
//       floor:  Nov–Dec 14/46 → 6/46,  Aug 3/11 → 0/11.
//   #4  Every raise is now PRICE-GATED. In August, 37 % of the raises that fired
//       in the expensive third had the tank already at 50–55 °C — pure waste.
//       A raise above PRICE_GATE_PCT is refused unless the tank is genuinely low.
//   Also new: an explicit BLOCK during expensive hours while the tank is healthy.
//
// INPUTS (set these on msg by the preceding api-current-state nodes)
//   msg.dhw_temp        tank temperature °C
//   msg.current_state   'Blocked' | 'Normal' | 'Comfort' | 'Ordered'
//   msg.auto_mode       'on' | 'off'
// OUTPUTS
//   output 1 → { payload: { targetState, reason } }  only when a change is due
//   output 2 → { payload: { action: 'on'|'off' } }   DHW priority lock
// ─────────────────────────────────────────────────────────────────────────────

// ---- thresholds, all derived from the measured record -----------------------
const SAFETY_HOURS      = [5, 16];  // guarantee hot water before the two draws
const SAFETY_TEMP       = 46;       // never fired in the whole record; kept as a net
const EMERGENCY_TEMP    = 38;       // below this, heat at any price
const PRICE_FLOOR_TEMP  = 43;       // below this, a raise ignores the price gate
const COMFORTABLE_TEMP  = 48;       // above this the tank is healthy enough to block
const PRICE_GATE_PCT    = 40;       // refuse raises above this percentile …
const BLOCK_PCT         = 70;       // … and actively block above this one

const now       = new Date();
const temp      = parseFloat(msg.dhw_temp);
const current   = msg.current_state || 'Normal';
const plan      = flow.get('dhwPlan') || {};
const pct       = parseFloat(global.get(
    'homeassistant.homeAssistant.states["input_number.current_price_percentile"].state'));
const pricePct  = isNaN(pct) ? 50 : pct;

if (isNaN(temp)) { node.warn("[DHW] no tank temperature — no action"); return [null, null]; }
if (msg.auto_mode === 'off') {
    node.warn("[DHW] auto mode off — releasing");
    return [null, { payload: { action: 'off' } }];
}

function inWindow(w) {
    if (!w) return false;
    const s = new Date(w.start), e = new Date(w.end);
    return now >= s && now <= e;
}

let target = null, reason = 'no action', dhwActive = false;

// ── 1. SAFETY — guarantee hot water before the morning and evening draws ─────
if (SAFETY_HOURS.indexOf(now.getHours()) !== -1 && temp < SAFETY_TEMP) {
    target = 'Ordered';
    reason = `SAFETY: ${temp.toFixed(1)}°C below ${SAFETY_TEMP}°C at ${now.getHours()}:00`;
    dhwActive = true;
}
// ── 2. EMERGENCY — tank genuinely cold, price is irrelevant ──────────────────
else if (temp < EMERGENCY_TEMP) {
    target = 'Comfort';
    reason = `EMERGENCY: tank ${temp.toFixed(1)}°C below ${EMERGENCY_TEMP}°C`;
    dhwActive = true;
}
// ── 3. EVENING FILL — Ordered/60 °C so the tank survives the evening draw ────
else if (inWindow(plan.evening)) {
    if (pricePct <= PRICE_GATE_PCT || temp < PRICE_FLOOR_TEMP) {
        target = 'Ordered';
        reason = `evening fill to 60°C (P${pricePct.toFixed(0)}, tank ${temp.toFixed(1)}°C)`;
        dhwActive = true;
    } else {
        reason = `evening window open but P${pricePct.toFixed(0)} > ${PRICE_GATE_PCT} and tank ok — waiting`;
    }
}
// ── 4. MORNING FILL — Comfort/55 °C is enough before the smaller morning draw ─
else if (inWindow(plan.morning)) {
    if (pricePct <= PRICE_GATE_PCT || temp < PRICE_FLOOR_TEMP) {
        target = 'Comfort';
        reason = `morning fill to 55°C (P${pricePct.toFixed(0)}, tank ${temp.toFixed(1)}°C)`;
        dhwActive = true;
    } else {
        reason = `morning window open but P${pricePct.toFixed(0)} > ${PRICE_GATE_PCT} and tank ok — waiting`;
    }
}
// ── 5. BLOCK — expensive, and the tank has enough in it to coast ─────────────
else if (pricePct >= BLOCK_PCT && temp >= COMFORTABLE_TEMP) {
    target = 'Blocked';
    reason = `expensive (P${pricePct.toFixed(0)}) and tank ${temp.toFixed(1)}°C — blocking`;
}
// ── 6. otherwise release to Normal, so the pump's own ECO floor governs ──────
else if (current === 'Blocked' || current === 'Ordered' || current === 'Comfort') {
    target = 'Normal';
    reason = `releasing to Normal (P${pricePct.toFixed(0)}, tank ${temp.toFixed(1)}°C)`;
}

node.warn(`[DHW] ${temp.toFixed(1)}°C P${pricePct.toFixed(0)} ${current} → ${target || current}: ${reason}`);

let stateMsg = null;
if (target && target !== current) {
    flow.set('dhw_decision', { state: target, reason: reason, at: now.toISOString() });
    stateMsg = { payload: { targetState: target, reason: reason, dhwTemp: temp, pricePct: pricePct } };
}
return [stateMsg, { payload: { action: dhwActive ? 'on' : 'off' } }];
