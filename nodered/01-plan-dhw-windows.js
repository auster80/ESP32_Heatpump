// ─────────────────────────────────────────────────────────────────────────────
// Node-RED function node:  "Plan DHW Windows (adaptive)"
// Replaces the window-selection half of "Calculate Windows + Percentiles".
//
// WHY THIS CHANGED (docs/recommendations.md #2):
//   The old code searched two hard-coded bands — morning 18:00→06:30 and
//   evening 12:00→18:00. Measured against the price record those bands are
//   correct in deep winter (cheapest hours are 01–04) and wrong from March
//   onward (cheapest hours move to 10–13). Rather than switch bands by season,
//   this searches the whole span from now to the next draw deadline, so it
//   adapts on its own.
//
// INPUT   msg.payload.prices = [{ start_time, price }, ...]
// OUTPUT  flow "dhwPlan" = { morning, evening, percentiles, builtAt }
//         msg.payload    = the same plan (for debug / storing in HA)
// ─────────────────────────────────────────────────────────────────────────────

// 2.5 h, unchanged from the original — and it is the right value.
// Measured reheat is 14.4 K/h median (8.9 kW thermal into a ~530 L effective
// store), so a full 40 -> 60 C fill of 20 K completes in about 85 minutes and
// fits comfortably. Lengthening the window is actively harmful: it drags the
// fill across more hours and therefore pricier ones. Closed-loop replay at the
// correct reheat rate: 150 min gives 25 % vs flat in March, 285 min only 21 %.
const FILL_MIN_EVENING  = 150;
const FILL_MIN_MORNING  = 150;
const MORNING_DEADLINE  = { h: 6,  m: 30 };  // tank must be full before the morning draw
const EVENING_DEADLINE  = { h: 17, m: 0  };  // evening draws observed 17:00–22:00
const MAX_LOOKBACK_H    = 18;   // don't fill more than this far ahead of a deadline

const prices = (msg.payload && msg.payload.prices) || [];
if (prices.length < 2) {
    node.warn("No price data — keeping the previous plan");
    return null;
}

const now = new Date();
const interval = (new Date(prices[1].start_time) - new Date(prices[0].start_time)) / 60000;
const slotsEvening = Math.max(1, Math.round(FILL_MIN_EVENING / interval));
const slotsMorning = Math.max(1, Math.round(FILL_MIN_MORNING / interval));

// ---- percentiles (unchanged behaviour, still consumed by the space-heating flow)
const sorted = prices.map(p => p.price).sort((a, b) => a - b);
const at = f => sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * f))];
const percentiles = { p20: at(0.2), p40: at(0.4), p80: at(0.8), p90: at(0.9),
                      min: sorted[0], max: sorted[sorted.length - 1] };

// ---- next occurrence of a given wall-clock time, strictly in the future
function nextDeadline(spec) {
    const d = new Date(now);
    d.setHours(spec.h, spec.m, 0, 0);
    if (d <= now) d.setDate(d.getDate() + 1);
    return d;
}

// ---- cheapest contiguous block of slotsNeeded that ENDS at or before `deadline`
function cheapestBefore(deadline, slotsNeeded, label) {
    const earliest = new Date(Math.max(now.getTime(),
                                       deadline.getTime() - MAX_LOOKBACK_H * 3600e3));
    let best = null;
    for (let i = 0; i + slotsNeeded <= prices.length; i++) {
        const start = new Date(prices[i].start_time);
        const end   = new Date(new Date(prices[i + slotsNeeded - 1].start_time).getTime()
                               + interval * 60000);
        if (start < earliest || end > deadline) continue;
        let sum = 0;
        for (let j = i; j < i + slotsNeeded; j++) sum += prices[j].price;
        const avg = sum / slotsNeeded;
        if (!best || avg < best.avgPrice) {
            best = { start: start.toISOString(), end: end.toISOString(), avgPrice: avg };
        }
    }
    if (best) {
        node.warn(`[DHW] ${label}: ${new Date(best.start).toLocaleString()} → ` +
                  `${new Date(best.end).toLocaleTimeString()} @ ${best.avgPrice.toFixed(4)}`);
    } else {
        node.warn(`[DHW] ${label}: no window found before ${deadline.toLocaleString()}`);
    }
    return best;
}

const plan = {
    // morning fill uses Comfort (55 °C) — a morning draw follows soon after
    morning:  cheapestBefore(nextDeadline(MORNING_DEADLINE), slotsMorning, "morning window"),
    // evening fill uses Ordered (60 °C) — see 02-dhw-decision.js
    evening:  cheapestBefore(nextDeadline(EVENING_DEADLINE), slotsEvening, "evening window"),
    percentiles: percentiles,
    builtAt: now.toISOString()
};

flow.set("dhwPlan", plan);
global.set("priceData", { prices: prices, minPrice: percentiles.min,
                          maxPrice: percentiles.max, lastUpdated: now.toISOString() });

msg.payload = plan;
return msg;
