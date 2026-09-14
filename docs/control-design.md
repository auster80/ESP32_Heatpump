# Control design

Three objectives — cost, cycling, comfort — against a plant whose own
controller we do not replace. What follows is what the WPM actually does, the
one structural idea that makes the objectives agree rather than compete, and
the questions last winter's data has to answer before any of it is trusted.

## 1. The plant: what the WPM3i actually controls

From the TTF installation manual, because we are manipulating this controller's
input rather than replacing it:

- **It regulates return temperature, not flow.** The heating curve maps outdoor
  temperature to a return setpoint with slope `S` (`Steigung Heizkurve`,
  holding 1503). Changing the room setpoint is a *parallel shift* of that curve.
- **A buffer tank is in the loop.** This house has a TSBC Integralspeicher, and
  the manual is explicit that buffer temperature is regulated *solely* via the
  return sensor. If only the direct HK1 runs, setpoints drop by 5 K.
- **Optional room influence**, factor `K` = 1…20:
  `Δϑ_R = (ϑ_R,set − ϑ_R,actual) · S · K`. The manual notes this acts on the
  return setpoint exactly as the outdoor sensor does, only 1–20× stronger. So
  the room sensor and our shift are the *same lever* at different gains — worth
  knowing, because a high `K` would fight us.
- **Minimum standstill.** `RESTSTILLSTAND` (minutes) is visible in diagnostics;
  the compressor cannot restart inside it.
- **Outdoor averaging exists**, as `GEBÄUDEDÄMPFUNG`: 24 h / 48 h / 72 h. The
  manual presents it as one of the *two parameters of the summer-switching
  function*, which suggests the heating curve itself sees a faster value — but
  this is inference and §4 makes it the first question for the data. If the
  curve is damped over 24 h or more, intraday shifting is futile and this
  project stops.
- **Summer switchover** at averaged outdoor ≥ threshold (settable 10–30 °C),
  hysteresis −1 K.

## 2. The idea: plan blocks, not slots

The naive reading is that cost and compressor life are in tension — chasing
cheap quarter-hours means moving the shift constantly, and every move disturbs
the pump. That is true of the naive implementation and false of the problem.

An on/off compressor behind a buffer cycles like this:

```
on  = buffer / (capacity − demand)        off = buffer / demand
starts/h = demand · (capacity − demand) / (buffer · capacity)
```

**Cycling is worst at half load and falls to zero at both ends.** So a
controller that pushes the pump towards *off* or towards *near-capacity* cycles
it less than one that holds it at a comfortable middle. That is the same shape
price-blocking wants: long off stretches through expensive hours, long hard
runs through cheap ones.

`CyclingModel` in `curve.py` carries this. For a 6 kW pump with 0.5 kWh of
usable buffer and a 20-minute standstill, delivering the same 24 kWh/day:

| Delivery | Starts/day |
|---|---|
| flat, 1.0 kW all day | 40 |
| 8 h blocks at 3.0 kW | 16 |
| 6 h blocks at 4.0 kW | **10** |

Four times fewer starts, and cheaper. The objectives agree — *provided the
decision variable is a block, not a slot*.

**So the planner changes shape**: instead of a shift per 15-minute price slot,
plan a piecewise-constant shift with a minimum dwell of one to two hours and a
bounded number of changes per day. `merge_slots()` already coarsens price slots
and is the natural hook; the DP keeps the fine price resolution for costing
while the control moves on the coarse grid.

This also suits the hardware: §5 of the sensor design puts a first-order lag on
the presented temperature anyway, and the house is floor heating with hours of
time constant. Nothing in the chain wants 15-minute control.

## 3. What the current planner is missing

`plan_curve()` minimises price cost + band-violation penalty + comfort penalty
+ a small switching penalty. Three gaps:

1. **No cycling term at all.** `switch_penalty` stops the *control signal*
   dithering; it says nothing about compressor starts. `CyclingModel` now
   exists but is not yet wired into the DP cost.
2. **No dwell constraint.** The DP may change shift every slot.
3. **`PowerModel` is linear** in outdoor and shift. Raising the shift raises the
   return setpoint by `S · shift`, which lowers COP — roughly 2–2.5 %/K of flow
   temperature. A linear `kw_per_k_shift` fitted from data absorbs the average
   slope but not the curvature, so it will under-penalise large shifts. Whether
   that matters is question 5 below.

## 4. What last winter's data has to answer

InfluxDB is configured with no include/exclude filter, so every entity HA sees
is in it, including the Tecalor sensors, the SG Ready state, room temperature
and the price percentile. Each question below decides something specific.

1. **Does the heating curve see raw or damped outdoor temperature?**
   Cross-correlate the ISG's reported outdoor temperature against an
   independent weather series and measure the lag. *Decides whether this
   project is viable at all.* A lag of minutes is fine; 24 h+ kills it.
2. **Is the compressor on/off or modulating?** The run-length distribution
   answers it instantly — bimodal fixed runs versus long variable ones.
   *Decides whether `CyclingModel` is the right model.*
3. **How bad is cycling today, and where does it peak?** Starts per day against
   outdoor temperature, and the run-length histogram. *Gives `buffer_kwh` and
   `capacity_kw` by fitting the curve above, and sets the baseline to beat.*
4. **What is the house's passive response?** Fit `a`, `c`, `d` of `HouseModel`
   from indoor, outdoor and heat output. Note the honest limit: last winter has
   **no shift data**, so `b` — the gain from shift to indoor temperature —
   cannot be fitted from it. It has to be bootstrapped from the curve slope `S`
   and then learned online once the emulator runs.
5. **How much does COP fall with flow temperature?** Daily `Wärmemenge VD
   heizen` over daily `Leistungsaufnahme VD heizen` gives a daily COP; regress
   it against average outdoor temperature and against the resulting curve
   setpoint. *Decides whether `PowerModel` needs a non-linear term.*
6. **How large is the prize?** Distribute last winter's compressor energy over
   the price series and compute what the same energy would have cost if shifted
   into the cheapest windows subject to the comfort band. *Decides whether any
   of this is worth building.* Do this one first — it is a pure data question
   and needs no model.
7. **What is `RESTSTILLSTAND` set to, and `GEBÄUDEDÄMPFUNG`, and `K`?** Read
   from the WPM menu rather than the data.

## 5. Risks this design carries

- **Summer-mode trip.** A negative shift (pretend milder) can push the damped
  outdoor temperature over the summer threshold and stop heating entirely.
  Guard: forbid negative shifts whenever the damped outdoor is within
  `max_shift` of the threshold.
- **Room influence fighting us.** If `K` is large, the WPM's own room
  correction will partly cancel our shift. Read `K` before tuning; if it is
  high, either accept the reduced authority or reduce it deliberately.
- **The COP penalty is real.** A +4 K shift on `S = 0.6` raises the return
  setpoint 2.4 K, costing roughly 5–6 % efficiency. The price spread has to beat
  that before a shift pays, and Tibber spreads usually do — but the optimiser
  must carry the term or it will over-shift.
- **DHW already owns SG Ready.** Space heating via the emulator and hot water
  via the existing Node-RED flows must not both believe they are in charge.
  See `existing-home-assistant-control.md`.
