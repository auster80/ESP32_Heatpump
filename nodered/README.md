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
standing loss, **14.4 K/h** reheat, a **~530 L** effective store, and the real
draw events at their observed times and sizes.

The reheat rate is measured two independent ways that agree: per-episode sensor
rise over episode duration gives a median of **14.4 K/h** (typical full reheats
17–19), and DHW heat delivered over compressor runtime gives **8.9 kW thermal**,
which at 14.4 K/h implies 0.62 kWh/K — a ~530 L effective volume, consistent
with the TSBC Integralspeicher.

```bash
node replay.js <price.csv> <draws.csv> "label" [--old]
```

Same draws, same prices, old bands vs new logic:

| Period | OLD | NEW | Saving | Below 40 °C |
|---|---|---|---|---|
| Nov–Dec 2025 | 4 % vs flat, €234 | 4 %, €234 | **€0** | 12 % → **10 %** |
| March 2026 | 14 %, €99 | **25 %, €85** | **€14/month** | 5 % → 7 % |
| Aug–Sep 2026 | 5 %, €83 | **25 %, €65** | **€18/6 weeks** | 4 % → 4 % |

Read honestly:

- **Winter gains nothing.** The Nov–Dec spread is too narrow for any scheduler
  to exploit — consistent with the €14 winter prize in the findings. Do not
  expect this to pay for itself between November and February.
- **The gain is real from March onward**, roughly €12–14/month across the
  wide-spread months, so of order **€85/year**.
- **Comfort is not degraded** — time below 40 °C is unchanged or slightly better
  than the old logic. If hot water ever does run short, raise
  `PRICE_FLOOR_TEMP` (43 °C); it releases the price gate earlier.

## Two errors this harness caught, and one it caused

**Open-loop replay was wrong.** Replaying the recorded tank temperature feeds
back a trajectory produced by the *old* control, which never responds to new
decisions. It reported the new logic commanding heat 55 % of the time. The tank
has to be simulated.

**The reheat rate was 3× too low.** An early estimate of 4.5 K/h came from
regressing logged temperature over windows up to 180 minutes, which stitched
across idle gaps and diluted the rate. The true figure is **14.4 K/h**, checked
against 8.9 kW of measured thermal output.

**That wrong rate then caused a wrong "fix".** Believing a 20 K fill needed
4.4 h, `FILL_MIN` was raised from 150 to 285 minutes. With the correct rate a
20 K fill takes ~85 minutes, and the longer window is **actively worse** — it
drags the fill across more hours and therefore pricier ones (March 21 % vs 25 %,
Aug–Sep 20 % vs 25 %). The original 150 minutes was right, and has been
restored.

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
