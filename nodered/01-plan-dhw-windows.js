// ─────────────────────────────────────────────────────────────────────────────
// Node-RED function node:  "Calculate Windows + Percentiles" (adaptive)
// Drop-in replacement — emits the SAME msg.payload the downstream Store /
// Morning Found? / Evening Found? nodes consume, so the HA helpers
// (input_number.current_price_percentile, input_datetime.*_dhw_start, …) and the
// dashboard keep working unchanged.
//
// WHAT CHANGED (docs/recommendations.md #2): the window search. The old code
// used two hard-coded bands (morning 18:00→06:30, evening 12:00→18:00). Those
// are right in deep winter (cheap hours 01–04) and wrong from March (cheap hours
// 10–13). This searches the cheapest window between now and each draw deadline,
// so it adapts by itself. Everything else — percentiles, price level, the output
// shape — is preserved.
//
// Output contract kept identical:
//   msg.payload.percentiles = { p20,p40,p80,p90, maxPrice, minPrice }
//   msg.payload.currentPercentile, .priceLevel, .currentPrice
//   msg.payload.morningDHW = { start, end, avgPrice }   (null if none)
//   msg.payload.eveningDHW = { start, end, avgPrice }
// Plus, new, for the decision node:
//   flow.dhwPlan = { morning, evening, percentiles, builtAt }
// ─────────────────────────────────────────────────────────────────────────────

const FILL_MINUTES     = 150;             // 2.5 h — reheat is ~14 K/h, so this fills fully
const MORNING_DEADLINE = { h: 6,  m: 30 };
const EVENING_DEADLINE = { h: 17, m: 0  };
const MAX_LOOKBACK_H   = 18;

const prices = (msg.payload && msg.payload.prices) || [];
if (prices.length < 2) { node.warn("[DHW] no price data — keeping previous plan"); return null; }

const now = new Date();
const interval = (new Date(prices[1].start_time) - new Date(prices[0].start_time)) / 60000;
const slotsNeeded = Math.max(1, Math.round(FILL_MINUTES / interval));

// ---- percentiles (same keys as before) --------------------------------------
const sorted = prices.map(p => p.price).sort((a, b) => a - b);
const at = f => sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * f))];
const percentiles = {
    p20: at(0.2), p40: at(0.4), p80: at(0.8), p90: at(0.9),
    maxPrice: sorted[sorted.length - 1], minPrice: sorted[0]
};

// ---- current price → percentile + level (same logic as the old node) --------
const currentPrice = parseFloat(global.get(
    'homeassistant.homeAssistant.states["sensor.edlauers_electricity_price"].state'));
let currentPercentile = 50, priceLevel = 'normal';
if (!isNaN(currentPrice)) {
    const lower = sorted.filter(p => p < currentPrice).length;
    currentPercentile = (lower / (sorted.length - 1)) * 100;
    priceLevel = currentPercentile < 20 ? 'very_cheap'
               : currentPercentile < 40 ? 'cheap'
               : currentPercentile < 80 ? 'normal'
               : currentPercentile < 90 ? 'expensive' : 'very_expensive';
}

// ---- adaptive window search -------------------------------------------------
function nextDeadline(spec) {
    const d = new Date(now); d.setHours(spec.h, spec.m, 0, 0);
    if (d <= now) d.setDate(d.getDate() + 1);
    return d;
}
function cheapestBefore(deadline, label) {
    const earliest = new Date(Math.max(now.getTime(), deadline.getTime() - MAX_LOOKBACK_H * 3600e3));
    let best = null;
    for (let i = 0; i + slotsNeeded <= prices.length; i++) {
        const start = new Date(prices[i].start_time);
        const end   = new Date(new Date(prices[i + slotsNeeded - 1].start_time).getTime() + interval * 60000);
        if (start < earliest || end > deadline) continue;
        let sum = 0; for (let j = i; j < i + slotsNeeded; j++) sum += prices[j].price;
        const avg = sum / slotsNeeded;
        if (!best || avg < best.avgPrice)
            best = { start: prices[i].start_time, end: end.toISOString(), avgPrice: avg.toFixed(4) };
    }
    node.warn(best
        ? `[DHW] ${label}: ${new Date(best.start).toLocaleString()} → ${new Date(best.end).toLocaleTimeString()} @ ${best.avgPrice}`
        : `[DHW] ${label}: no window before ${deadline.toLocaleString()}`);
    return best;
}
const morningDHW = cheapestBefore(nextDeadline(MORNING_DEADLINE), "morning window");
const eveningDHW = cheapestBefore(nextDeadline(EVENING_DEADLINE), "evening window");

// ---- persist for the decision node, and for the space-heating flow ----------
flow.set('dhwPlan', { morning: morningDHW, evening: eveningDHW, percentiles: percentiles, builtAt: now.toISOString() });
global.set('priceData', { prices: prices, maxPrice: percentiles.maxPrice, minPrice: percentiles.minPrice, lastUpdated: now.toISOString() });

// ---- output: exactly the shape the downstream nodes expect ------------------
msg.payload = {
    percentiles: percentiles,
    currentPercentile: currentPercentile,
    priceLevel: priceLevel,
    currentPrice: currentPrice,
    morningDHW: morningDHW,
    eveningDHW: eveningDHW
};
return msg;
