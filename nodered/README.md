# Node-RED replacements for the DHW control

Implements items 2, 3 and 4 of `../docs/recommendations.md`. Paste each file
into the corresponding function node; nothing else in the flow changes.

| File | Replaces | Implements |
|---|---|---|
| `01-plan-dhw-windows.js` | window half of *Calculate Windows + Percentiles* | #2 adaptive search |
| `02-dhw-decision.js` | *DHW Decision Logic (FIXED)* | #3 Ordered fill, #4 price gate |
| `replay.js` | — | closed-loop validation harness |

## Validation

`replay.js` simulates the tank rather than replaying its history — the recorded
temperature was produced by the *old* control, so feeding it back would never
respond to new decisions. The model uses the measured values: **0.15 K/h**
standing loss, **4.5 K/h** reheat, and the real draw events at their observed
times and sizes.

```bash
node replay.js <price.csv> <draws.csv> "label" [--old]
```

Same draws, same prices, old bands vs new logic:

| Period | OLD | NEW | Saving | Below 40 °C |
|---|---|---|---|---|
| Nov–Dec 2025 | 5 % vs flat, €132 | 5 %, €131 | ~€1 | 15 % → 18 % |
| March 2026 | 15 %, €55 | **23 %, €49** | **€6/month** | 9 % → 11 % |
| Aug–Sep 2026 | 6 %, €46 | **24 %, €36** | **€10/6 weeks** | 5 % → 6 % |

Read honestly:

- **Winter gains nothing.** The Nov–Dec spread is too narrow for any scheduler
  to exploit — consistent with the €14 winter prize in the findings. Do not
  expect this to pay for itself between November and February.
- **The gain is real from March onward**, roughly €6–8/month across the
  wide-spread months, so of order **€50/year**.
- **The tank runs slightly leaner** — time below 40 °C rises by 1–3 points. That
  is still usable water, but if hot water ever runs short, raise
  `PRICE_FLOOR_TEMP` (43 °C) first; it releases the price gate earlier.

## The bug this harness caught

The first version kept the old 150-minute (2.5 h) window. At 4.5 K/h that
cannot fill 40 → 60 °C, which needs 4.4 h, so the tank never reached target and
the new logic came out **worse than the old bands** in winter. Sizing the window
to the fill is why `FILL_MIN_EVENING` is 285 minutes. An open-loop replay hid
this completely.

## Tunables (top of `02-dhw-decision.js`)

| Constant | Value | Meaning |
|---|---|---|
| `SAFETY_TEMP` | 46 | Unchanged. Never fired in the whole record |
| `EMERGENCY_TEMP` | 38 | Heat at any price below this |
| `PRICE_FLOOR_TEMP` | 43 | Below this a raise ignores the price gate |
| `COMFORTABLE_TEMP` | 48 | Above this, blocking is allowed |
| `PRICE_GATE_PCT` | 40 | Refuse raises above this percentile |
| `BLOCK_PCT` | 70 | Actively block above this percentile |

## Before deploying

1. Check the **mixing valve** is set for 60 °C at the tap — the evening fill
   uses Ordered.
2. Deploy `01` first and watch `dhwPlan` in the debug pane for a day; the
   windows should track the cheap hours (overnight in winter, midday from
   March).
3. Then deploy `02`. Watch the tank for a week and raise `PRICE_FLOOR_TEMP` if
   anyone runs out of hot water.
